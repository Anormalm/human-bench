from __future__ import annotations

from datetime import datetime, timezone

from .schemas import Pair, Response, Scenario


def build_annotation_bundle(
    scenarios: list[Scenario], responses: list[Response], pairs: list[Pair]
) -> dict:
    scenario_by_id = {item.scenario_id: item for item in scenarios}
    response_by_id = {item.response_id: item for item in responses}
    items = []
    for pair in pairs:
        scenario = scenario_by_id[pair.scenario_id]
        response_a = response_by_id[pair.response_a]
        response_b = response_by_id[pair.response_b]
        if response_a.scenario_id != scenario.scenario_id or response_b.scenario_id != scenario.scenario_id:
            raise ValueError(f"pair {pair.pair_id} crosses scenarios")
        items.append(
            {
                "pair_id": pair.pair_id,
                "scenario_id": scenario.scenario_id,
                "language": scenario.language,
                "genre": scenario.genre,
                "relationship": scenario.relationship,
                "intent": scenario.intent,
                "channel": scenario.channel,
                "context": scenario.context,
                "instruction": scenario.instruction,
                "required_facts": scenario.required_facts,
                "prohibited_changes": scenario.prohibited_changes,
                "response_a": response_a.response_id,
                "response_b": response_b.response_id,
                "response_a_text": response_a.text,
                "response_b_text": response_b.text,
            }
        )
    return {
        "schema_version": "0.2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_pairs": len(items),
        "items": items,
    }

