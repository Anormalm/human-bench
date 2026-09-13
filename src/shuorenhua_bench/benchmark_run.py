from __future__ import annotations

import json
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .dataset import read_jsonl, write_jsonl
from .model_judge import atomic_json, automatic_report, digest, judge_config, judge_pairs
from .pairing import build_pairs
from .response_runner import run as generate
from .schemas import Response
from .study import prepare_study, verify_study
from .validation import require_valid


class RequestLedger:
    """A persistent cap on HTTP attempts, not a currency spending guarantee."""

    def __init__(self, path, maximum):
        if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
            raise ValueError("--max-requests must be a positive integer for --execute")
        self.path = Path(path)
        self.maximum = maximum
        self.data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "attempts": [], "max_requests": maximum}
        if self.data["max_requests"] != maximum:
            raise ValueError("resume must retain the original --max-requests cap")
        if len(self.data["attempts"]) > maximum:
            raise ValueError("request ledger already exceeds the cap")
        atomic_json(self.path, self.data)

    def reserve(self, config, payload):
        if len(self.data["attempts"]) >= self.maximum:
            raise RuntimeError("HTTP request cap reached; completed calls are saved. No request sent.")
        self.data["attempts"].append({
            "number": len(self.data["attempts"]) + 1, "model": config.model,
            "system_id": config.system_id, "provider": config.base_url,
            "request_hash": digest(payload), "max_output_tokens": config.max_tokens,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
        })
        atomic_json(self.path, self.data)


@contextmanager
def run_lock(output):
    lock = Path(output) / ".run.lock"
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        raise ValueError("run is locked; after verifying no process is active, remove .run.lock") from None
    try:
        yield
    finally:
        lock.unlink()


def _resolved_config(config):
    config = deepcopy(config)
    if not config.get("systems") or len(config["systems"]) < 2:
        raise ValueError("automatic comparison requires at least two systems")
    for system in config["systems"]:
        system["model"] = system.get("model") or os.environ.get(system.get("model_env", ""))
    provider, _ = judge_config(config["judge"])
    config["judge"]["model"] = provider.model
    return config


def run_benchmark(scenarios, config, output, *, execute=False, max_requests=None, resume=False,
                  bootstrap_samples=1000, seed=20260913, existing_responses=None):
    if bootstrap_samples < 0:
        raise ValueError("bootstrap samples must be nonnegative")
    config = _resolved_config(config)
    output = Path(output)
    if output.exists() and any(output.iterdir()) and not resume:
        raise ValueError("output directory is not empty; choose a new run or use --resume")
    require_valid(scenarios, existing_responses or [])
    if not scenarios or len({s.scenario_id for s in scenarios}) != len(scenarios):
        raise ValueError("nonempty, unique scenarios are required")
    ids = [s["system_id"] for s in config["systems"]]
    if len(set(ids)) != len(ids):
        raise ValueError("system IDs must be unique")
    if existing_responses is not None:
        cells = [(r.scenario_id, r.system_id) for r in existing_responses]
        expected = {(s.scenario_id, system) for s in scenarios for system in ids}
        if len(cells) != len(set(cells)) or set(cells) != expected:
            raise ValueError("imported responses must contain exactly one response per declared cell")
        if any(r.track != "native_generation" for r in existing_responses):
            raise ValueError("automatic runner currently requires native_generation responses")
    protocol = {"schema_version": "0.4", "config": config, "seed": seed,
                "scenarios": [s.model_dump(mode="json") for s in scenarios],
                "imported_responses": [r.model_dump(mode="json") for r in existing_responses]
                if existing_responses is not None else None}
    manifest_path = output / "run.json"
    if resume and manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != protocol:
            raise ValueError("resume input or configuration changed")
        if not (output / "requests.json").exists():
            raise ValueError("resume request ledger is missing; cannot preserve the request cap")
    elif output.exists() and any(output.iterdir()):
        raise ValueError("existing directory has no compatible run manifest")
    generation_plan = generate(scenarios, config, output / "responses.jsonl", dry_run=True,
                               resume=resume) if existing_responses is None else {
                                   "planned_completions": 0, "maximum_http_attempts": 0}
    provider, _ = judge_config(config["judge"])
    n_pairs = len(scenarios) * len(ids) * (len(ids) - 1) // 2
    plan = {
        "status": "preview", "scenarios": len(scenarios), "systems": ids,
        "models": {s["system_id"]: s["model"] for s in config["systems"]},
        "judge": provider.model, "new_generation_completions": generation_plan["planned_completions"],
        "comparison_pairs": n_pairs, "judge_completions_before_resume": 2 * n_pairs,
        "maximum_http_attempts_before_judge_resume": generation_plan["maximum_http_attempts"]
        + 2 * n_pairs * provider.retries,
        "max_requests": max_requests,
        "cap_scope": "HTTP attempts across this run, including retries and unknown outcomes; not USD.",
        "output": str(output), "execution": "Add --execute --max-requests N to make API calls.",
    }
    if not execute:
        return plan
    if not isinstance(max_requests, int) or isinstance(max_requests, bool) or max_requests < 1:
        raise ValueError("--execute requires a positive --max-requests")
    # Resolve all credentials before generating anything, including the judge credential.
    env_names = {provider.api_key_env}
    if generation_plan["planned_completions"]:
        env_names.update(s["api_key_env"] for s in config["systems"])
    missing = sorted(name for name in env_names if not os.environ.get(name))
    if missing:
        raise ValueError("missing API key environment variables: " + ", ".join(missing))
    if not resume and max_requests < generation_plan["planned_completions"] + 2 * n_pairs:
        raise ValueError("--max-requests is below the minimum complete run size; preview the plan")
    output.mkdir(parents=True, exist_ok=True)
    with run_lock(output):
        atomic_json(manifest_path, protocol)
        ledger = RequestLedger(output / "requests.json", max_requests)
        write_jsonl(output / "scenarios.jsonl", scenarios)
        if existing_responses is None:
            generate(scenarios, config, output / "responses.jsonl", resume=resume,
                     before_request=ledger.reserve)
        else:
            write_jsonl(output / "responses.jsonl", existing_responses)
        responses = read_jsonl(output / "responses.jsonl", Response)
        pairs = build_pairs(responses, seed=seed)
        write_jsonl(output / "pairs.jsonl", pairs)
        # The human validation packet is frozen before automatic judgments are collected.
        human_path = output / "human-study"
        if (human_path / "manifest.json").exists():
            verify_study(human_path)
        else:
            prepare_study(scenarios, responses, human_path, raters=3, judgments_per_pair=3,
                          seed=seed, study_name="Human validation of model screening")
        judgments, summary = judge_pairs(
            scenarios, responses, pairs, config["judge"], output / "judge", resume=resume,
            before_request=ledger.reserve)
        write_jsonl(output / "model-judgments.jsonl", judgments)
        report = automatic_report(scenarios, responses, pairs, judgments, summary,
                                  bootstrap_samples=bootstrap_samples, seed=seed)
        report["run"] = {"protocol_hash": digest(protocol), "http_attempts_reserved": len(ledger.data["attempts"]),
                         "max_requests": max_requests, "human_study": "human-study"}
        atomic_json(output / "report.json", report)
    return {"status": "complete", "ranking_status": report["ranking_status"],
            "accepted_pairs": len(judgments), "excluded_pairs": summary["n_excluded_pairs"],
            "report": str(output / "report.json"), "human_study": str(human_path),
            "http_attempts_reserved": len(ledger.data["attempts"]), "max_requests": max_requests}
