from __future__ import annotations

import re

import numpy as np


def register_features(text: str) -> np.ndarray:
    length = max(len(text), 1)
    sentences = max(len(re.findall(r"[。！？!?]", text)), 1)
    return np.array(
        [
            len(text) / sentences,
            text.count("您") / length,
            text.count("请") / length,
            text.count("哈哈") / length,
            len(re.findall(r"[!！]{2,}", text)) / length,
            len(re.findall(r"(?:首先|其次|最后|总之)", text)) / length,
        ],
        dtype=float,
    )


def standardized_register_distance(text: str, reference_texts: list[str]) -> float:
    if not reference_texts:
        raise ValueError("reference_texts must not be empty")
    reference = np.vstack([register_features(item) for item in reference_texts])
    scale = np.where(reference.std(axis=0) > 1e-9, reference.std(axis=0), 1.0)
    return float(np.linalg.norm((register_features(text) - reference.mean(axis=0)) / scale))

