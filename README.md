# 说人话 Bench · v0.5

**Measure which messages people prefer and would actually use in a specific situation.**

A human-grounded research workbench for Chinese communication. Native generation and
humanization are separate tracks. Source detection, diagnostics and preference are separate constructs.

**Status:** functioning study infrastructure with 72 scenario candidates. The bundled
leaderboard contains **synthetic software-test votes**, not measured model performance.
The 48 new challenge candidates are AI-authored and await native-speaker review.
This release does not establish SOTA or a validated population benchmark.

## Run locally

From this repository directory, without activating a virtual environment:

~~~powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe scripts/serve_web.py --port 8043
~~~

Open <http://127.0.0.1:8043>. The workbench includes Overview, Run models, Annotate, Results and Judge audit.
A ready-made demonstration is included; no API key is needed.

On macOS/Linux, use .venv/bin/python. For the exact tested dependency set, install
requirements-dev.lock before installing the project with --no-deps.

## Run models and get an automatic ranking

Open **Run models** in the browser to configure two candidates and a judge. Or use
the baseline profile from the repository root:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli run --scenarios data/prompts/suite_zh_v0.3.jsonl --config configs/benchmark.openai-smoke.yaml --output studies/first-model-run --limit 3
~~~

This previews 6 candidate responses and 6 judge completions without API calls.
Set OPENAI_API_KEY and append **--execute --max-requests 24** to run it. Add --resume
after an interruption. Import the resulting report.json into Results.

The runner checks every pair in both orders, keeps one vote only when decisions agree,
records exclusions, preserves raw judge output, and creates three human-validation packets.
A persistent cap counts all HTTP attempts, including retries. It is not a USD budget.
Automatic predictions, human judgments and synthetic test evidence stay separate.

See [running and interpreting models](docs/run_models.md) for custom providers, reasoning
models, existing responses, resume rules and human validation. This smoke profile tests
mechanics with dated baseline snapshots; it is not a frontier-model recommendation.

## Audit and calibrate judges

The **Judge audit** page compares judges on identical saved candidate responses and
shows preference consistency separately from action consistency. Expand a pair to read
both display orders and explanations. Optional human exports provide a separate majority
reference with explicit coverage, disagreement and provenance.

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli compare-judges --runs studies/first-model-run studies/astra-judge-pilot --output studies/judge-comparison-v05.json
~~~

The [judge audit guide](docs/judge_audit.md) includes the Astra comparison configuration,
human-reference commands and offline reanalysis. The original acceptance rule is retained.
All-tie reports state that no winner is established; collapsed bootstrap intervals are withheld.
The separate [constructed judge controls](docs/judge_controls.md) check sensitivity to
clear violations and equivalent text. They never enter the candidate ranking.

## Study infrastructure from v0.3

- **Study packages:** frozen input copies, SHA-256 checks, private identity maps, opaque public
  response IDs, distinct-rater assignments, and A/B counterbalancing.
- **Annotation desk:** packet import, persistent progress scoped to packet and annotator,
  preference, send/revise/reject actions, confidence, timing, optional problem spans and export.
- **Strict import:** validate assignment and displayed orientation, resolve blind IDs, ignore
  identical duplicate exports, and reject conflicts or cross-study records.
- **Statistics:** regularized Davidson–Bradley–Terry estimation, identifiable position adjustment,
  graph connectivity checks, semantic/template group bootstrap, pairwise contrasts, exploratory
  rank intervals, direct-use intervals and explicit missing-evidence warnings.
- **Evidence inspection:** agreement normalized across reversed displays, per-rater diagnostics,
  span counts, coverage and context slices. Repeated response/rater actions count as one observation.
- **Collection:** the 24-case alpha plus 48 challenge candidates covering commitment strength,
  privacy, uncertainty, audience adaptation, factual scope and social relationships.
- **Generation:** dry-run preflight, bounded completions/retries, configuration-checked resume,
  atomic output replacement, provider-returned model metadata, truncation rejection and rewriting.
- **Research operations:** dataset/split audits, approximate sample-size planning,
  preregistration template, regression tests and CI.

## Full software demonstration

Use a fresh output directory; prepared studies are not overwritten.

~~~powershell
.\.venv\Scripts\python.exe scripts/run_demo.py --output studies/my-demo --bootstrap-samples 1000
~~~

This constructs 144 pairs from 48 scenarios and three controlled fixture systems,
creates 12 rater packets, simulates 432 explicitly labeled votes, imports them through
the study verifier, and fits the report. It does not call a model API or recruit people.
Add --update-web-demo to replace the bundled demo. Refresh after changing files.
Previously imported packets remain selected; import the desired packet to change studies.

## Run a real study

### 1. Review scenarios and declare the experiment

Start with data/prompts/suite_zh_v0.3.jsonl and the
[research protocol](docs/research_protocol_v03.md). Have native speakers review candidate
contexts, facts, constraints and suitability. Author fresh human references with documented
source, consent and licensing. Keep recruitment identities outside this repository.

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli plan --systems 4 --scenarios 200 --effect 0.1
~~~

The planner is a binary normal approximation with explicit ICC and multiplicity assumptions,
not validated power for the full tie-aware model. This design has 1,200 pairs and 3,600 judgments.
The repository currently supplies 72 candidates, not 200 validated cases.

### 2. Generate model responses

Choose exact model identifiers using configs/systems.example.yaml (OpenRouter) or
configs/systems.openai.example.yaml (OpenAI). Keep credentials in environment variables.

~~~powershell
$env:OPENROUTER_API_KEY="your-key"
$env:SHUORENHUA_MODEL_A="provider/exact-model-a"
$env:SHUORENHUA_MODEL_B="provider/exact-model-b"
.\.venv\Scripts\python.exe scripts/generate_responses.py --scenarios data/prompts/suite_zh_v0.3.jsonl --systems configs/systems.example.yaml --output data/private/model_responses.jsonl --limit 3 --dry-run --max-calls 6
~~~

Review the plan, then remove --dry-run to perform six completions.
--max-calls bounds logical completions; retries may create extra HTTP requests and charges.
It is **not a dollar budget**. Provider billing and model availability are external.

Use --resume after interruption. Changed prompts, models or decoding settings require a new
output path. v0.2 outputs lack request fingerprints and cannot be silently resumed.
Use dated snapshots where available; a provider-returned alias does not prove an immutable model.

For rewriting, add --sources with a source-response JSONL file. Use one fixed source per
scenario shared by every rewrite system. The output retains source records for lineage
validation; only compatible rewrite responses are compared.

### 3. Prepare blinded assignments

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli prepare --scenarios data/prompts/suite_zh_v0.3.jsonl --responses data/private/model_responses.jsonl --output studies/live-pilot --raters 12 --judgments-per-pair 3
~~~

Use matching scenario/response files. A generation run with --limit 3 covers only that subset;
the audit shows missing responses for the remaining scenarios.

~~~text
manifest.json                    Declared design, assignments, input hashes
private/scenarios.jsonl           Frozen scenarios
private/responses.jsonl           Frozen outputs and provenance
private/pairs.jsonl               Canonical comparisons
private/response_map.json         Identity key; never give to annotators
public/rater-001.json ...         Individually assigned blind packets
~~~

Preserve a separate trusted manifest before collection. Hash checks detect changes relative
to it; they are not a signature against someone rewriting both inputs and manifest.

Give each participant their own packet to load in Annotate. An assignment ID is a pseudonym,
not authentication or proof of an independent human. Manage recruitment, consent and one
participant per ID outside the app. Progress stays in browser storage; export regularly.
Private browsing, storage eviction or clearing site data can remove progress.

### 4. Import and inspect

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli evaluate --study studies/live-pilot --exports exports/rater-001.jsonl exports/rater-002.jsonl exports/rater-003.jsonl --output results/live-pilot.json --bootstrap-samples 1000
~~~

List all exported files. Load the resulting JSON in Results. Under-annotated planned pairs
remain visible. The CLI also writes a normalized judgments JSONL next to the report;
keep it private during collection.

Set SHUORENHUA_BUNDLE and SHUORENHUA_REPORT to absolute paths before starting the local server
to serve a selected packet/report. Only those configured files and allowlisted web assets
are exposed. There is no server-side collection or study-directory browsing.
The local server is a development server.

## Audit and grouped splits

~~~powershell
.\.venv\Scripts\python.exe scripts/build_splits.py --scenarios data/prompts/suite_zh_v0.3.jsonl --output data/splits/suite_v03.json
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli audit --scenarios data/prompts/suite_zh_v0.3.jsonl --splits data/splits/suite_v03.json --output results/audit.json
~~~

Grouping uses the transitive closure of semantic and template IDs. Review those IDs:
automatic grouping cannot discover all paraphrases. Public splits are reproducible
development partitions, not protected held-out evaluation data.

## Interpretation and development

Intervals capture scenario-group resampling conditional on recruited raters, not uncertainty
over a new rater population. The model is regularized, not a hierarchical mixed-effects model.
Sparse or disconnected comparisons do not justify a complete ranking. Diagnostics and
optional problem flags do not measure quality by themselves.

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m compileall -q api src scripts
~~~

Raw-ID v0.2 judgments still work with scripts/evaluate.py, with stricter validation.
Standalone v0.3 bundle construction now requires --private-map outside the public directory;
pass the map as --response-map to scripts/evaluate.py. Prefer the study prepare/evaluate
workflow because it also validates assignments.

Report schema 0.3 replaces IID Wilson and prompt-only interval fields with group-bootstrap
fields. Consumers should check schema_version.

See [CHANGELOG](CHANGELOG.md), [benchmark card](docs/benchmark_card.md),
[research protocol](docs/research_protocol_v03.md) and [data documentation](data/README.md).
