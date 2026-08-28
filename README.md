# 说人话 Bench (Shuorenhua Bench)

A context- and population-conditioned benchmark for perceived naturalness, direct usability,
revision burden, and semantic preservation in model-generated text.

The benchmark does **not** define a universal “human-likeness” score. It measures what people
prefer and would actually use in a specified relationship, channel, intent, and communication
context. AI-source detection is kept as a separate research task.

## What works in v0.2 alpha

- 24 native Chinese messaging scenarios with required facts and prohibited changes;
- real-model generation through any OpenAI-compatible API, including OpenRouter;
- reproducible manifests with model name, decoding configuration, hashes, and usage metadata;
- deterministic, position-balanced blind pair construction;
- a browser annotation UI for `A / tie / B` and `send / revise / reject` judgments;
- JSONL export with no server-side collection of annotator data;
- Davidson–Bradley–Terry estimation with ties and prompt-clustered bootstrap intervals;
- direct-use rates with Wilson intervals and pair-level disagreement entropy;
- leakage-resistant grouped train/dev/test splits;
- deterministic repetition, excess n-gram, semantic-preservation, and register diagnostics.

See [the benchmark card](docs/benchmark_card.md) for the claim boundary and minimum credible
pilot. This repository is SOTA-oriented; it does not claim SOTA results before human validation.

## Try the deployed annotation demo

Open the Vercel deployment in a browser. The root page presents an anonymous comparison. Enter
an annotator ID, choose a preference and action for each response, then export the judgments as
JSONL. The included responses are controlled smoke-test texts, not human/model performance data.

To run the same interface locally:

```bash
python -m pip install -e ".[dev]"
python scripts/serve_web.py
```

Open <http://127.0.0.1:8000>.

## Run a real two-model pilot

### 1. Install

```bash
git clone https://github.com/Anormalm/human-bench.git
cd human-bench
python -m pip install -e ".[dev]"
```

### 2. Select models

`configs/systems.example.yaml` uses OpenRouter as an OpenAI-compatible endpoint without locking
the benchmark to particular model families. Set two exact model IDs and your API key.

PowerShell:

```powershell
$env:OPENROUTER_API_KEY="your-key"
$env:SHUORENHUA_MODEL_A="provider/model-a"
$env:SHUORENHUA_MODEL_B="provider/model-b"
```

Bash:

```bash
export OPENROUTER_API_KEY="your-key"
export SHUORENHUA_MODEL_A="provider/model-a"
export SHUORENHUA_MODEL_B="provider/model-b"
```

### 3. Smoke-test three scenarios

```bash
python scripts/generate_responses.py \
  --scenarios data/prompts/pilot_zh_messaging_v0.2.jsonl \
  --systems configs/systems.example.yaml \
  --output data/responses/pilot_models.jsonl \
  --limit 3 --resume
```

Remove `--limit 3` for the complete 24-scenario alpha. `--resume` skips completed calls after an
API interruption.

### 4. Blind the comparisons

```bash
python scripts/build_pairs.py \
  --responses data/responses/pilot_models.jsonl \
  --output data/annotations/pilot_pairs.jsonl

python scripts/build_annotation_bundle.py \
  --scenarios data/prompts/pilot_zh_messaging_v0.2.jsonl \
  --responses data/responses/pilot_models.jsonl \
  --pairs data/annotations/pilot_pairs.jsonl \
  --output data/web/demo_bundle.json
```

Restart the local web server, or commit the new bundle and redeploy Vercel. The UI never reveals
system names and stores progress only in the annotator's browser.

### 5. Aggregate exported human judgments

Combine annotators' exported JSONL records, then run:

```bash
python scripts/evaluate.py \
  --responses data/responses/pilot_models.jsonl \
  --judgments data/annotations/judgments.jsonl \
  --output results/report.json \
  --bootstrap-samples 1000
```

The report contains system abilities, uncertainty intervals, empirical win/tie/loss counts,
direct-use distributions, sample sizes, and disagreement estimates. There is no mandatory
overall score.

## Benchmark pipeline

```text
authored scenarios → declared model outputs → blinded balanced pairs → human observations
        → validation → tie-aware statistical model → multidimensional report
```

Automated judges are optional extensions. They must predict held-out human judgment distributions,
report calibration and abstention, and never replace the human evaluation protocol silently.

## Data and research policy

Do not commit private conversations, credentials, unlicensed text, or identifiable annotator data.
Real releases must document scenario sourcing, participant recruitment, consent, exclusions,
population composition, model snapshots, decoding settings, and preregistered primary analyses.

## Development

```bash
python -m compileall -q api src scripts
pytest
```

The optional `statsmodels` backend is installed with `.[stats]`. Register diagnostics explain
distributional differences; they are not quality labels.

