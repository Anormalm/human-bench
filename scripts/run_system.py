from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from shuorenhua_bench.dataset import read_jsonl, write_jsonl
from shuorenhua_bench.generation import run_generator
from shuorenhua_bench.schemas import Scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an importable generator over scenarios")
    parser.add_argument("--scenarios", required=True, type=Path)
    parser.add_argument("--callable", required=True, help="module:function accepting a Scenario")
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    module_name, function_name = args.callable.split(":", 1)
    generator = getattr(importlib.import_module(module_name), function_name)
    responses = run_generator(read_jsonl(args.scenarios, Scenario), generator, system_id=args.system_id)
    write_jsonl(args.output, responses)


if __name__ == "__main__":
    main()

