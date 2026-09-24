"""Run the fixed retrieval evaluation set against a running CoursePilot instance.

Usage:
    python scripts/run_evaluation.py
    python scripts/run_evaluation.py --top-k 5 --refusal
    python scripts/run_evaluation.py --course-id <id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_CASES = Path(__file__).with_name("evaluation_cases.json")


def resolve_course(client: httpx.Client, course_id: str | None, course_name: str) -> str:
    if course_id:
        return course_id
    courses = client.get("/api/courses").json()
    if not courses:
        raise SystemExit("No course found. Create a course and upload documents first.")
    for course in courses:
        if course["name"] == course_name:
            return course["id"]
    return courses[0]["id"]


def print_table(cases: list[dict]) -> None:
    print("| # | 命中 | RR | 词覆盖 | Top1分数 | 延迟(ms) | 问题 | 命中文档 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for index, case in enumerate(cases, start=1):
        print(
            "| {i} | {hit} | {rr:.2f} | {cov:.2f} | {score:.3f} | {lat} | {q} | {doc} |".format(
                i=index,
                hit="Y" if case["hit"] else "N",
                rr=case["reciprocal_rank"],
                cov=case["term_coverage"],
                score=case["top_score"],
                lat=case["latency_ms"],
                q=case["question"],
                doc=case["top_document"] or "-",
            )
        )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover - Python < 3.7
        pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--course-id", default=None)
    parser.add_argument("--top-k", type=int, nargs="+", default=[3, 5])
    parser.add_argument("--refusal", action="store_true", help="also run the off-topic refusal checks")
    args = parser.parse_args()

    payload = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = payload["cases"]
    refusal_cases = payload.get("refusal_cases", [])

    with httpx.Client(base_url=args.base_url, timeout=300.0) as client:
        course_id = resolve_course(client, args.course_id, payload.get("course_name", ""))
        print("course:", course_id)
        print("cases:", len(cases))

        for top_k in args.top_k:
            response = client.post(
                "/api/evaluations/run",
                json={"course_id": course_id, "cases": cases, "top_k": top_k},
            )
            if response.status_code != 200:
                print("\n!! evaluation failed: HTTP %s %s" % (response.status_code, response.text[:300]))
                return 1
            data = response.json()
            print("\n=== top_k = %d ===" % top_k)
            print_table(data["cases"])
            print(
                "\nHit Rate = {hr:.1%}   MRR = {mrr:.3f}   平均词覆盖率 = {cov:.2f}   平均检索延迟 = {lat} ms".format(
                    hr=data["hit_rate"],
                    mrr=data["mrr"],
                    cov=data["average_term_coverage"],
                    lat=data["average_latency_ms"],
                )
            )

        if args.refusal and refusal_cases:
            print("\n=== refusal check (expect decision=refuse) ===")
            for question in refusal_cases:
                response = client.post("/api/chat", json={"course_id": course_id, "question": question})
                if response.status_code != 200:
                    print("!! chat failed: HTTP %s %s" % (response.status_code, response.text[:200]))
                    return 1
                data = response.json()
                print(
                    "decision={decision} retrieved={count} citations={cites} | {q}".format(
                        decision=data["trace"]["decision"],
                        count=data["trace"]["retrieval_count"],
                        cites=len(data["citations"]),
                        q=question,
                    )
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
