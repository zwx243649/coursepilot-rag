from __future__ import annotations

import math
import re
from collections import Counter


_WORD_RE = re.compile(r"[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """English words plus CJK unigrams and bigrams.

    A bigram pass gives Chinese text usable term statistics without pulling in a
    segmentation dependency; it is the same idea the local scorer already uses.
    """
    lowered = text.lower()
    tokens = _WORD_RE.findall(lowered)
    for run in _CJK_RE.findall(lowered):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


class BM25Index:
    """Minimal Okapi BM25 over an in-memory document set."""

    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.freqs = [Counter(tokenize(document)) for document in documents]
        self.lengths = [sum(freq.values()) for freq in self.freqs]
        self.average_length = (
            sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        )

        document_frequency: Counter[str] = Counter()
        for freq in self.freqs:
            document_frequency.update(freq.keys())
        total = len(self.freqs)
        self.idf = {
            term: math.log(1 + (total - count + 0.5) / (count + 0.5))
            for term, count in document_frequency.items()
        }

    def scores(self, query: str) -> list[float]:
        if not self.freqs:
            return []
        query_tokens = Counter(tokenize(query))
        if not query_tokens:
            return [0.0] * len(self.freqs)

        scores: list[float] = []
        for freq, length in zip(self.freqs, self.lengths, strict=True):
            normalizer = 1 - self.b + self.b * (
                length / self.average_length if self.average_length else 1.0
            )
            score = 0.0
            for term, weight in query_tokens.items():
                term_frequency = freq.get(term)
                if not term_frequency:
                    continue
                score += (
                    weight
                    * self.idf.get(term, 0.0)
                    * (term_frequency * (self.k1 + 1))
                    / (term_frequency + self.k1 * normalizer)
                )
            scores.append(score)
        return scores

    def ranking(self, query: str) -> list[int]:
        """Document indexes ordered by descending BM25 score."""
        scores = self.scores(query)
        return sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
