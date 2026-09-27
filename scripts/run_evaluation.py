"""Run the fixed retrieval evaluation suites against a running CoursePilot instance.

Usage:
    python scripts/run_evaluation.py
    python scripts/run_evaluation.py --top-k 3 5 10
    python scripts/run_evaluation.py --suite 机器学习 --top-k 5
    python scripts/run_evaluation.py --refusal

The case file may hold several suites (one per course). Every case can carry a
ground-truth annotation - the chunks that actually answer the question - which
is what Recall@k, Precision@k and NDCG@k are computed against.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CASES = Path(__file__).with_name("evaluation_cases.json")


def load_suites(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "suites" in payload:
        return payload["suites"]
    return [
        {
            "name": payload.get("name", "default"),
            "course_name": payload.get("course_name", ""),
            "cases": payload.get("cases", []),
        }
    ]


def resolve_course(client: httpx.Client, course_id: str | None, course_name: str) -> str:
    if course_id:
        return course_id
    courses = client.get("/api/courses").json()
    if not courses:
        raise SystemExit("No course found. Create a course and upload documents first.")
    for course in courses:
        if course["name"] == course_name:
            return course["id"]
    if len(courses) == 1:
        return courses[0]["id"]
    raise SystemExit(
        "Course %r not found. Available: %s"
        % (course_name, ", ".join(c["name"] for c in courses))
    )


def corpus_index(client: httpx.Client, course_id: str) -> dict[str, set[int]]:
    """Map document name -> set of chunk indexes, so annotations can be checked."""
    documents = client.get("/api/courses/%s/documents" % course_id).json()
    index: dict[str, set[int]] = {}
    for document in documents:
        chunks = client.get("/api/documents/%s/chunks" % document["id"]).json()
        index[document["original_name"]] = {int(chunk["chunk_index"]) for chunk in chunks}
    return index


def validate_annotations(index: dict[str, set[int]], cases: list[dict]) -> list[str]:
    problems: list[str] = []
    for case in cases:
        expected = [term.strip() for term in case.get("expected_terms", []) if term.strip()]
        answerable = case.get("answerable", True)
        for annotation in case.get("relevant", []):
            document = annotation["document"]
            chunk_index = int(annotation["chunk_index"])
            if document not in index:
                problems.append("%s -> 文档不存在: %s" % (case["question"], document))
            elif chunk_index not in index[document]:
                problems.append("%s -> 切片不存在: %s#%s" % (case["question"], document, chunk_index))
        if not answerable and case.get("relevant"):
            problems.append("%s -> 不可回答的用例不应标注标准答案切片" % case["question"])
        if answerable and not case.get("relevant") and not expected:
            problems.append("%s -> 可回答用例缺少标注和期望词" % case["question"])
    return problems


def annotation_report(client: httpx.Client, course_id: str, cases: list[dict]) -> list[str]:
    """Check the ground truth: terms live in annotated chunks, and nothing is missed.

    A too-narrow annotation makes Recall@k look worse than reality, so we also flag
    chunks that contain every expected term but were not annotated.
    """
    documents = client.get("/api/courses/%s/documents" % course_id).json()
    contents: dict[tuple[str, int], str] = {}
    for document in documents:
        for chunk in client.get("/api/documents/%s/chunks" % document["id"]).json():
            contents[(document["original_name"], int(chunk["chunk_index"]))] = chunk["content"]

    warnings: list[str] = []
    for case in cases:
        terms = [term.lower() for term in case.get("expected_terms", []) if term.strip()]
        if not terms:
            continue
        annotated_keys = {
            (a["document"], int(a["chunk_index"])) for a in case.get("relevant", [])
        }
        annotated_texts = [contents.get(key, "").lower() for key in annotated_keys]
        for term in terms:
            if annotated_texts and not any(term in text for text in annotated_texts):
                warnings.append("%s -> 期望词 %r 不在标注切片里" % (case["question"], term))

        if annotated_keys:
            missed = [
                key
                for key, text in contents.items()
                if key not in annotated_keys and all(term in text.lower() for term in terms)
            ]
            if missed:
                shown = ", ".join("%s#%s" % key for key in missed[:3])
                more = "" if len(missed) <= 3 else " 等 %d 个" % len(missed)
                warnings.append(
                    "%s -> 可能有遗漏标注（同样包含全部期望词）: %s%s"
                    % (case["question"], shown, more)
                )
    return warnings


def print_case_table(cases: list[dict]) -> None:
    print("| # | 判定 | 预期 | Recall | P@k | NDCG | Top1 | 延迟 | 问题 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for index, case in enumerate(cases, start=1):
        print(
            "| {i} | {decision} | {expect} | {recall:.2f} | {precision:.2f} | {ndcg:.2f} | "
            "{score:.3f} | {lat}ms | {question} |".format(
                i=index,
                decision=case["decision"],
                expect="可答" if case["answerable"] else "应拒答",
                recall=case["recall_at_k"],
                precision=case["precision_at_k"],
                ndcg=case["ndcg_at_k"],
                score=case["top_score"],
                lat=case["latency_ms"],
                question=case["question"],
            )
        )


def run_suite(
    client: httpx.Client,
    suite: dict,
    top_k_values: list[int],
    with_refusal: bool,
    offline: bool = False,
) -> int:
    course_id = resolve_course(client, suite.get("course_id"), suite.get("course_name", ""))
    cases = suite["cases"]
    print("\n=== 套件: %s  (course=%s, %d 条用例) ===" % (suite["name"], course_id, len(cases)))

    problems = validate_annotations(corpus_index(client, course_id), cases)
    if problems:
        print("!! 标注校验未通过：")
        for problem in problems:
            print("   -", problem)
        return 1
    print("标注校验通过（%d 条用例）" % len(cases))

    for warning in annotation_report(client, course_id, cases):
        print("   [warn]", warning)

    for top_k in top_k_values:
        response = client.post(
            "/api/evaluations/run",
            json={
                "course_id": course_id,
                "cases": cases,
                "top_k": top_k,
                "offline": offline,
            },
        )
        if response.status_code != 200:
            print("\n!! 评测失败：HTTP %s %s" % (response.status_code, response.text[:300]))
            return 1
        data = response.json()
        print("\n--- top_k = %d ---" % top_k)
        print_case_table(data["cases"])
        print(
            "\nRecall@k = {recall:.1%}   Precision@k = {precision:.1%}   NDCG@k = {ndcg:.3f}   "
            "MRR = {mrr:.3f}   Hit Rate = {hit:.1%}   词覆盖率 = {cov:.2f}\n"
            "判定准确率 = {dec:.1%}   平均检索延迟 = {lat:.0f} ms".format(
                recall=data["recall_at_k"],
                precision=data["precision_at_k"],
                ndcg=data["ndcg_at_k"],
                mrr=data["mrr"],
                hit=data["hit_rate"],
                cov=data["average_term_coverage"],
                dec=data["decision_accuracy"],
                lat=data["average_latency_ms"],
            )
        )

    if with_refusal:
        unanswerable = [case for case in cases if not case.get("answerable", True)]
        if unanswerable:
            print("\n--- 端到端拒答检查（走完整 /api/chat 链路）---")
            for case in unanswerable:
                response = client.post(
                    "/api/chat",
                    json={"course_id": course_id, "question": case["question"]},
                )
                if response.status_code != 200:
                    print("!! chat failed: HTTP %s %s" % (response.status_code, response.text[:200]))
                    return 1
                data = response.json()
                print(
                    "decision={decision} retrieved={count} | {q}".format(
                        decision=data["trace"]["decision"],
                        count=data["trace"]["retrieval_count"],
                        q=case["question"],
                    )
                )
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover - Python < 3.7
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--suite", action="append", default=None, help="suite name, repeatable")
    parser.add_argument("--top-k", type=int, nargs="+", default=[3, 5])
    parser.add_argument("--refusal", action="store_true", help="also run end-to-end refusal checks")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip query rewrite and rerank; uses cached query vectors only",
    )
    args = parser.parse_args()

    suites = load_suites(args.cases)
    if args.suite:
        wanted = set(args.suite)
        suites = [suite for suite in suites if suite["name"] in wanted]
        if not suites:
            raise SystemExit("No suite matched %s" % ", ".join(sorted(wanted)))

    exit_code = 0
    with httpx.Client(base_url=args.base_url, timeout=300.0) as client:
        for suite in suites:
            exit_code = max(
                exit_code,
                run_suite(client, suite, args.top_k, args.refusal, args.offline),
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
