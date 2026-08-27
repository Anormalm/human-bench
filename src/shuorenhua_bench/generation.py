from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable

from .schemas import GenerationManifest, Provenance, Response, Scenario


def stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_generator(
    scenarios: Iterable[Scenario],
    generator: Callable[[Scenario], str],
    *,
    system_id: str,
    provider: str | None = None,
    model: str | None = None,
) -> list[Response]:
    """Run an injected generator while recording reproducibility metadata."""
    responses = []
    for scenario in scenarios:
        text = generator(scenario).strip()
        prompt_text = f"{scenario.context}\n{scenario.instruction}"
        responses.append(
            Response(
                response_id=f"{scenario.scenario_id}:{system_id}",
                scenario_id=scenario.scenario_id,
                system_id=system_id,
                text=text,
                provenance=Provenance.RAW_MODEL,
                manifest=GenerationManifest(
                    provider=provider,
                    model=model,
                    input_hash=stable_hash(prompt_text),
                    output_hash=stable_hash(text),
                ),
            )
        )
    return responses

