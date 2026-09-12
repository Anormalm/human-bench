from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

import yaml

from shuorenhua_bench.dataset import read_jsonl, write_jsonl
from shuorenhua_bench.generation import stable_hash
from shuorenhua_bench.providers import OpenAICompatibleProvider, ProviderConfig
from shuorenhua_bench.schemas import GenerationManifest, Provenance, Response, Scenario


def render_prompt(scenario: Scenario, source: str | None = None) -> str:
    fields = ("language", "genre", "channel", "relationship", "intent", "context", "instruction",
              "required_facts", "prohibited_changes")
    payload = {key: getattr(scenario, key) for key in fields}
    if source is not None:
        payload["source_text_to_rewrite"] = source
        payload["rewrite_requirement"] = "Preserve facts, intent and commitment strength."
    return json.dumps(payload, ensure_ascii=False, indent=2)


def run(scenarios, config, output, *, resume=False, dry_run=False, max_calls=None, sources=None):
    if not scenarios or len({s.scenario_id for s in scenarios}) != len(scenarios):
        raise ValueError("scenarios must be nonempty with unique IDs")
    system_ids = [s["system_id"] for s in config["systems"]]
    if not system_ids or len(set(system_ids)) != len(system_ids):
        raise ValueError("system IDs must be nonempty and unique")
    source_map = {}
    for source in sources or []:
        if source.scenario_id in source_map:
            raise ValueError("one fixed source response per scenario required")
        source_map[source.scenario_id] = source
    if sources is not None and any(s.scenario_id not in source_map for s in scenarios):
        raise ValueError("missing rewrite source")
    output = Path(output)
    if output.exists() and not resume and not dry_run:
        raise ValueError("output exists; use --resume or a new output path")
    existing = read_jsonl(output, Response) if output.exists() and resume else []
    if len({r.response_id for r in existing}) != len(existing):
        raise ValueError("duplicate response IDs in resume file")
    completed = {r.response_id: r for r in existing}
    if existing and sources is not None:
        for source in sources:
            if completed.get(source.response_id) != source:
                raise ValueError("resume source lineage changed or is missing")
    tasks = []
    for system in config["systems"]:
        model = system.get("model") or os.environ.get(system.get("model_env", ""))
        if not model:
            raise ValueError(f"set {system.get('model_env')} or configure an exact model")
        provider_config = ProviderConfig(
            system_id=system["system_id"], model=model, base_url=system["base_url"],
            api_key_env=system["api_key_env"], temperature=float(system.get("temperature", .2)),
            top_p=float(system.get("top_p", 1)), max_tokens=int(system.get("max_tokens", 512)),
            retries=int(system.get("retries", 3)),
            timeout_seconds=float(system.get("timeout_seconds", 90)))
        prompt = system.get("system_prompt", config["system_prompt"])
        for scenario in scenarios:
            source = source_map.get(scenario.scenario_id)
            user_prompt = render_prompt(scenario, source.text if source else None)
            identifier = f"{scenario.scenario_id}:{system['system_id']}"
            fingerprint = stable_hash(json.dumps(
                {"config": asdict(provider_config), "system_prompt": prompt,
                 "user_prompt": user_prompt, "source_response_id": source.response_id if source else None},
                ensure_ascii=False, sort_keys=True))
            if identifier in completed:
                prior = completed[identifier]
                if prior.metadata.get("request_fingerprint") != fingerprint:
                    raise ValueError(f"resume configuration or input changed: {identifier}")
                if not prior.manifest or stable_hash(prior.text) != prior.manifest.output_hash:
                    raise ValueError(f"resume output hash mismatch: {identifier}")
                continue
            tasks.append((scenario, source, identifier, fingerprint, provider_config, prompt, user_prompt))
    expected_ids = {f"{s.scenario_id}:{system}" for s in scenarios for system in system_ids}
    source_ids = {s.response_id for s in sources or []}
    if set(completed) - expected_ids - source_ids:
        raise ValueError("resume file contains outputs outside this run")
    if max_calls is not None and (max_calls < 0 or len(tasks) > max_calls):
        raise ValueError(f"planned {len(tasks)} completions exceeds --max-calls={max_calls}")
    plan = {"planned_completions": len(tasks), "completed": len(existing),
            "maximum_http_attempts": sum(t[4].retries for t in tasks),
            "maximum_new_output_tokens": sum(t[4].max_tokens for t in tasks),
            "dry_run": dry_run}
    if dry_run:
        return plan
    # Check all credentials before the first paid call.
    for task in tasks:
        if not os.environ.get(task[4].api_key_env):
            raise ValueError(f"missing API key environment variable: {task[4].api_key_env}")
    responses = existing or list(sources or [])
    for scenario, source, identifier, fingerprint, provider_config, prompt, user_prompt in tasks:
        text, metadata = OpenAICompatibleProvider(provider_config).generate(
            system_prompt=prompt, user_prompt=user_prompt)
        metadata["request_fingerprint"] = fingerprint
        responses.append(Response(
            response_id=identifier, scenario_id=scenario.scenario_id,
            system_id=provider_config.system_id, text=text,
            provenance=Provenance.HUMANIZER if source else Provenance.RAW_MODEL,
            track="humanization" if source else "native_generation",
            source_response_id=source.response_id if source else None,
            manifest=GenerationManifest(
                provider=provider_config.base_url, model=provider_config.model,
                model_revision=metadata.get("resolved_model"), system_prompt=prompt,
                temperature=provider_config.temperature, top_p=provider_config.top_p,
                max_tokens=provider_config.max_tokens,
                input_hash=stable_hash(prompt + "\0" + user_prompt), output_hash=stable_hash(text)),
            metadata=metadata))
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        write_jsonl(temporary, responses)
        os.replace(temporary, output)
        print(f"generated {identifier}")
    return plan


def main():
    parser = argparse.ArgumentParser(description="Generate reproducible model responses")
    parser.add_argument("--scenarios", type=Path, required=True)
    parser.add_argument("--systems", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sources", type=Path, help="Fixed source responses for rewrite track")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-calls", type=int, help="Fail before generation if the plan exceeds this bound")
    args = parser.parse_args()
    scenarios = read_jsonl(args.scenarios, Scenario)
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        scenarios = scenarios[:args.limit]
    result = run(
        scenarios, yaml.safe_load(args.systems.read_text(encoding="utf-8")), args.output,
        resume=args.resume, dry_run=args.dry_run, max_calls=args.max_calls,
        sources=read_jsonl(args.sources, Response) if args.sources else None)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
