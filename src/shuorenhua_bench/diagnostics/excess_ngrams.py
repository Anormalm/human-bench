from __future__ import annotations

import math
import re
from collections import Counter


def ngrams(text: str, n: int) -> list[str]:
    normalized = re.sub(r"\s+", "", text)
    return [normalized[i : i + n] for i in range(max(0, len(normalized) - n + 1))]


def excess_ngram_log_odds(
    candidate_texts: list[str], reference_texts: list[str], n: int = 4, alpha: float = 0.5
) -> dict[str, float]:
    """Smoothed log-odds relative to a matched human/register corpus."""
    candidate = Counter(g for text in candidate_texts for g in ngrams(text, n))
    reference = Counter(g for text in reference_texts for g in ngrams(text, n))
    vocabulary = set(candidate) | set(reference)
    c_total = sum(candidate.values()) + alpha * len(vocabulary)
    r_total = sum(reference.values()) + alpha * len(vocabulary)
    return {
        gram: math.log((candidate[gram] + alpha) / c_total)
        - math.log((reference[gram] + alpha) / r_total)
        for gram in vocabulary
    }

