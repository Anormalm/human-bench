from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from .annotation_bundle import build_annotation_bundle
from .audit import audit_dataset
from .dataset import read_jsonl, write_jsonl
from .pairing import build_pairs
from .schemas import Pair, PairwiseJudgment, Response, Scenario
from .validation import require_valid


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def prepare_study(scenarios, responses, output, *, raters=9, judgments_per_pair=3,
                  seed=20260913, study_name="Chinese communication study", demo=False):
    if judgments_per_pair < 2 or raters < judgments_per_pair:
        raise ValueError("require at least two judgments per pair and enough distinct raters")
    require_valid(scenarios, responses)
    input_audit = audit_dataset(scenarios, responses)
    pairs = build_pairs(responses, seed)
    if not pairs:
        raise ValueError("no compatible cross-system pairs")
    compared_ids = {identifier for p in pairs for identifier in (p.response_a, p.response_b)}
    tracks = {r.track for r in responses if r.response_id in compared_ids}
    if len(tracks) != 1:
        raise ValueError("prepare separate studies for separate tracks")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("study directory must be empty; frozen studies cannot be overwritten")
    output.mkdir(parents=True, exist_ok=True)
    ids = {}
    bundle = build_annotation_bundle(scenarios, responses, pairs, id_map=ids)
    study_id = bundle["study_id"]
    bundle["title"] = study_name
    bundle["demo"] = demo
    private = output / "private"
    public = output / "public"
    write_jsonl(private / "scenarios.jsonl", scenarios)
    write_jsonl(private / "responses.jsonl", responses)
    write_jsonl(private / "pairs.jsonl", pairs)
    write_json(private / "response_map.json", ids)
    rng = random.Random(seed)
    queues = [[] for _ in range(raters)]
    counts = [0] * raters
    # Give each pair distinct raters, balancing workloads and avoiding repeated scenarios when possible.
    seen_scenarios = [Counter() for _ in range(raters)]
    shuffled = list(bundle["items"])
    rng.shuffle(shuffled)
    for item in shuffled:
        candidates = list(range(raters))
        rng.shuffle(candidates)
        candidates.sort(key=lambda i: (seen_scenarios[i][item["scenario_id"]], counts[i]))
        selected = candidates[:judgments_per_pair]
        flip_start = rng.randrange(2)
        for vote, rater in enumerate(selected):
            displayed = dict(item)
            if (vote + flip_start) % 2:
                displayed["response_a"], displayed["response_b"] = item["response_b"], item["response_a"]
                displayed["response_a_text"], displayed["response_b_text"] = item["response_b_text"], item["response_a_text"]
            queues[rater].append(displayed)
            counts[rater] += 1
            seen_scenarios[rater][item["scenario_id"]] += 1
    assignments = {}
    for rater, items in enumerate(queues, 1):
        rng.shuffle(items)
        assignment_id = f"rater-{rater:03d}"
        packet = {**bundle, "items": items, "n_pairs": len(items), "assignment_id": assignment_id}
        packet["bundle_id"] = hashlib.sha256(json.dumps(packet, sort_keys=True).encode()).hexdigest()
        relative = f"public/{assignment_id}.json"
        write_json(output / relative, packet)
        assignments[assignment_id] = relative
    hashes = {str(p.relative_to(output)).replace("\\", "/"): sha256_file(p)
              for folder in (private, public) for p in sorted(folder.glob("*"))}
    manifest = {
        "schema_version": "0.3", "study_id": study_id, "title": study_name,
        "track": next(iter(tracks)), "seed": seed,
        "n_scenarios": len(scenarios), "n_responses": len(responses), "n_pairs": len(pairs),
        "n_assignments": raters, "judgments_per_pair": judgments_per_pair,
        "n_planned_judgments": len(pairs) * judgments_per_pair,
        "assignment_loads": counts, "assignments": assignments, "sha256": hashes,
        "input_coverage": {
            "missing_system_scenario_cells": input_audit["missing_system_scenario_cells"],
            "scenario_sources": input_audit["scenario_sources"],
            "human_reference_count": input_audit["human_reference_count"],
        },
        "evidence_status": "synthetic_demo" if demo else "awaiting_human_annotation",
        "protocol": {
            "primary_outcome": "contextual preference, A/B/tie",
            "secondary_outcome": "send/revise/reject per response",
            "model": "regularized Davidson with identifiable display-position effect",
            "uncertainty": "semantic/template connected-cluster bootstrap, conditional on raters",
            "min_raters_per_pair": judgments_per_pair,
            "exclusions": "invalid records rejected; no automatic speed/confidence exclusions",
            "source_detection": "separate study only",
            "claim_boundary": "engineering pilot until recruitment, human review and validity audit",
        },
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def verify_study(path):
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    required = {"private/scenarios.jsonl", "private/responses.jsonl", "private/pairs.jsonl",
                "private/response_map.json", *manifest["assignments"].values()}
    if not required.issubset(manifest["sha256"]):
        raise ValueError("manifest omits required study files")
    for relative, expected in manifest["sha256"].items():
        target = (path / relative).resolve()
        if not target.is_relative_to(path.resolve()):
            raise ValueError("manifest path escapes study directory")
        if not target.is_file() or sha256_file(target) != expected:
            raise ValueError(f"study integrity failure: {relative}")
    return manifest


def import_judgments(study, files):
    study = Path(study)
    manifest = verify_study(study)
    mapping = json.loads((study / "private/response_map.json").read_text(encoding="utf-8"))
    assignments = {}
    for assignment, relative in manifest["assignments"].items():
        packet = json.loads((study / relative).read_text(encoding="utf-8"))
        assignments[assignment] = {x["pair_id"]: x for x in packet["items"]}
    records, duplicates = {}, 0
    for file in files:
        for j in read_jsonl(file, PairwiseJudgment):
            if j.study_id != manifest["study_id"]:
                raise ValueError("judgment belongs to a different study")
            if manifest["evidence_status"] == "synthetic_demo" and j.evidence_kind != "synthetic":
                raise ValueError("demo exports must be labeled synthetic")
            if j.assignment_id not in assignments:
                raise ValueError("unknown annotation assignment")
            if j.annotator_id != j.assignment_id:
                raise ValueError("annotator must use the assigned pseudonym")
            item = assignments[j.assignment_id].get(j.pair_id)
            if item is None or (j.response_a, j.response_b, j.scenario_id) != (
                    item["response_a"], item["response_b"], item["scenario_id"]):
                raise ValueError("judgment does not match assigned display")
            spans = []
            for span in j.spans:
                if span.response_id not in (j.response_a, j.response_b):
                    raise ValueError("span references a response outside this assignment")
                spans.append(span.model_copy(update={"response_id": mapping[span.response_id]}))
            resolved = j.model_copy(update={"response_a": mapping[j.response_a],
                                          "response_b": mapping[j.response_b], "spans": spans})
            key = (j.pair_id, j.annotator_id)
            if key in records:
                if records[key] != resolved:
                    raise ValueError(f"conflicting duplicate export: {key}")
                duplicates += 1
            else:
                records[key] = resolved
    rows = list(records.values())
    require_valid(read_jsonl(study / "private/scenarios.jsonl", Scenario),
                  read_jsonl(study / "private/responses.jsonl", Response),
                  read_jsonl(study / "private/pairs.jsonl", Pair), rows)
    return rows, duplicates
