# 说人话 Bench (Shuorenhua Bench)

A context- and population-conditioned benchmark for measuring perceived naturalness, direct usability, revision burden, and semantic preservation in model-generated text.

The benchmark does **not** define a universal “human-likeness” score. Its core path is deliberately simple and auditable:

1. matched scenarios and responses;
2. blinded, position-balanced pairwise comparisons;
3. human `A / tie / B` and `send / revise / reject` observations;
4. Davidson–Bradley–Terry and behavioral aggregation;
5. deterministic diagnostics as explanations, not ground truth.

Automated judges are optional extensions and must be calibrated against held-out human judgments. Native generation and humanization/rewrite results are reported separately.

## V0.1 scope

`v0.1 — Chinese Messaging Pilot` targets workplace and everyday Chinese messaging across four relationships (friend, colleague, manager, stranger) and four intents (explain, refuse, request, respond). The configuration targets 200 scenarios, one human response and three system responses per scenario, with at least three judgments per pair.

## Quick start

```bash
python -m pip install -e '.[dev]'
python scripts/build_pairs.py \
  --responses data/responses/example.jsonl \
  --output data/annotations/pairs.jsonl
python scripts/import_annotations.py \
  --input label_studio_export.json \
  --output data/annotations/judgments.jsonl
python scripts/evaluate.py \
  --responses data/responses/example.jsonl \
  --judgments data/annotations/judgments.jsonl \
  --output results/report.json
pytest
```

JSONL records are validated against the Pydantic models in `schemas.py`. See `configs/benchmark_v0.1.yaml` and `annotation/guidelines.md` before collecting data.

## Main outputs

- population-conditioned pairwise preference and uncertainty;
- direct-use probability (`send`, `revise`, `reject`);
- revision burden;
- semantic-preservation and hard-constraint pass rates;
- formulaicity, repetition, and register-distance diagnostics;
- rater disagreement and subgroup slices.

There is no mandatory overall score. Any composite score must declare its weights and is secondary to the multidimensional report.

## Data policy

The repository contains schemas and small examples only. Do not commit personally identifying content, proprietary conversations, credentials, or unlicensed text. Public releases should use grouped splits so semantic clusters, source templates, and response authors cannot cross train/test boundaries.

## Development status

This is an experimental V0.1 implementation. The Davidson model, bootstrap confidence intervals, validation, pairing, and deterministic diagnostics are usable; mixed-effects estimation is exposed as an optional `statsmodels` backend. A learned preference evaluator is intentionally deferred until sufficient human comparison data exists.

