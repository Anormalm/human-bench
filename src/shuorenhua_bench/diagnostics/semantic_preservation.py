from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PreservationResult:
    required_fact_recall: float
    number_consistency: float
    missing_facts: tuple[str, ...]
    introduced_numbers: tuple[str, ...]


def check_preservation(source: str, rewritten: str, required_facts: list[str]) -> PreservationResult:
    missing = tuple(fact for fact in required_facts if fact not in rewritten)
    source_numbers = set(re.findall(r"\d+(?:[.,]\d+)?%?", source))
    rewritten_numbers = set(re.findall(r"\d+(?:[.,]\d+)?%?", rewritten))
    introduced = tuple(sorted(rewritten_numbers - source_numbers))
    fact_recall = 1.0 if not required_facts else 1.0 - len(missing) / len(required_facts)
    union = source_numbers | rewritten_numbers
    number_consistency = 1.0 if not union else len(source_numbers & rewritten_numbers) / len(union)
    return PreservationResult(fact_recall, number_consistency, missing, introduced)

