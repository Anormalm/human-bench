from __future__ import annotations

import re
from collections import Counter


def character_ngram_repetition(text: str, n: int = 4) -> float:
    units = [char for char in re.sub(r"\s+", "", text)]
    grams = [tuple(units[i : i + n]) for i in range(max(0, len(units) - n + 1))]
    if not grams:
        return 0.0
    counts = Counter(grams)
    repeated = sum(count - 1 for count in counts.values())
    return repeated / len(grams)


def line_repetition(text: str) -> float:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return 0.0 if not lines else 1.0 - len(set(lines)) / len(lines)

