from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

from shuorenhua_bench.dataset import read_jsonl, write_jsonl
from shuorenhua_bench.generation import stable_hash
from shuorenhua_bench.providers import OpenAICompatibleProvider, ProviderConfig
from shuorenhua_bench.schemas import GenerationManifest, Provenance, Response, Scenario


def render_prompt(scenario: Scenario) -> str:
    return json.dumps(
        {
            "language": scenario.language,
            "genre": scenario.genre,
            "channel": scenario.channel,
            "relationship": scenario.relationship,
            "intent": scenario.intent,
            "context": scenario.context,
            "instruction": scenario.instruction,
            "required_facts": scenario.required_facts,
            "prohibited_changes": scenario.prohibited_changes,
        },
        ensure_ascii=False,
        indent=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate benchmark responses from real models")
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--systems", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    scenarios = read_jsonl(args.scenarios, Scenario)
    if args.limit is not None:
        scenarios = scenarios[: args.limit]
    config = yaml.safe_load(args.systems.read_text(encoding="utf-8"))
    system_prompt = config["system_prompt"]
    responses: list[Response] = (
        read_jsonl(args.output, Response) if args.resume and args.output.exists() else []
    )
    completed = {item.response_id for item in responses}

    for system in config["systems"]:
        model = system.get("model") or os.environ.get(system.get("model_env", ""))
        if not model:
            raise RuntimeError(
                f"set {system.get('model_env')} or add model: to {args.systems}"
            )
        provider = OpenAICompatibleProvider(
            ProviderConfig(
                system_id=system["system_id"],
                model=model,
                base_url=system["base_url"],
                api_key_env=system["api_key_env"],
                temperature=float(system.get("temperature", 0.2)),
                top_p=float(system.get("top_p", 1.0)),
                max_tokens=int(system.get("max_tokens", 512)),
            )
        )
        for scenario in scenarios:
            response_id = f"{scenario.scenario_id}:{system['system_id']}"
            if response_id in completed:
                print(f"skipped {response_id} (already generated)")
                continue
            user_prompt = render_prompt(scenario)
            text, provider_metadata = provider.generate(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            responses.append(
                Response(
                    response_id=response_id,
                    scenario_id=scenario.scenario_id,
                    system_id=system["system_id"],
                    text=text,
                    provenance=Provenance.RAW_MODEL,
                    manifest=GenerationManifest(
                        provider=system.get("provider", "openai_compatible"),
                        model=model,
                        system_prompt=system_prompt,
                        temperature=provider.config.temperature,
                        top_p=provider.config.top_p,
                        max_tokens=provider.config.max_tokens,
                        input_hash=stable_hash(user_prompt),
                        output_hash=stable_hash(text),
                    ),
                    metadata=provider_metadata,
                )
            )
            completed.add(response_id)
            write_jsonl(args.output, responses)
            print(f"generated {scenario.scenario_id} with {system['system_id']}")


if __name__ == "__main__":
    main()
