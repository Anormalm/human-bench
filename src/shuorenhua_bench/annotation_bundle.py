from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone

from .schemas import Pair, Response, Scenario
from .validation import require_valid


def build_annotation_bundle(scenarios: list[Scenario], responses: list[Response],
                            pairs: list[Pair], *, id_map: dict | None = None,
                            study_id: str | None = None, salt: str | None = None) -> dict:
    require_valid(scenarios, responses, pairs)
    salt = salt or secrets.token_hex(32)
    scenario_by_id = {s.scenario_id: s for s in scenarios}
    response_by_id = {r.response_id: r for r in responses}
    aliases = {}
    for r in responses:
        alias = "r-" + hashlib.sha256((salt + "\0" + r.response_id).encode()).hexdigest()[:24]
        aliases[r.response_id] = alias
        if id_map is not None:
            id_map[alias] = r.response_id
    items = []
    for pair in pairs:
        s = scenario_by_id[pair.scenario_id]
        item = {key: getattr(s, key) for key in (
            "scenario_id", "language", "genre", "relationship", "intent", "channel",
            "context", "instruction", "required_facts", "prohibited_changes")}
        item.update(pair_id=pair.pair_id, response_a=aliases[pair.response_a],
                    response_b=aliases[pair.response_b],
                    response_a_text=response_by_id[pair.response_a].text,
                    response_b_text=response_by_id[pair.response_b].text)
        items.append(item)
    identity = hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"schema_version": "0.3", "study_id": study_id or "study-" + identity[:16],
            "bundle_id": identity, "created_at": datetime.now(timezone.utc).isoformat(),
            "n_pairs": len(items), "items": items}
