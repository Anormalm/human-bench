# Run models and rank them

Version 0.4 introduced the automatic workflow. Version 0.5 adds [judge audits and offline reanalysis](judge_audit.md). Model-generated judgments are screening
predictions; they are kept separate from human observations.

## First run on Windows

From the repository folder, using the existing virtual environment:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli run --scenarios data/prompts/suite_zh_v0.3.jsonl --config configs/benchmark.openai-smoke.yaml --output studies/first-model-run --limit 3
~~~

This previews 6 generated responses, 3 pairs and 6 judge completions. It makes no
API calls and creates no run directory. The seed selects a reproducible random subset.

After setting OPENAI_API_KEY in the process environment, execute the same plan:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli run --scenarios data/prompts/suite_zh_v0.3.jsonl --config configs/benchmark.openai-smoke.yaml --output studies/first-model-run --limit 3 --execute --max-requests 24
~~~

The 24-request cap includes retries and persists across restarts. It is **not a USD
spending guarantee**. A failed request with an unknown billing outcome consumes an
attempt. Add --resume to the same command after an interruption. Completed generations
and judge checks are reused; changed inputs, model settings, rubric or cap are rejected.
A missing request ledger blocks resume. Runs are serialized with an exclusive lock.
If a process was forcibly killed, verify it has stopped before removing its .run.lock.

Use a new output directory for a different experiment. To run the full candidate suite,
omit --limit; two systems then require 144 generations plus 144 judge completions
(288 successful completions, up to 576 HTTP attempts with two attempts per completion).
Here retries means total allowed attempts, as in the provider configuration.

The baseline preset uses dated GPT-4.1 and GPT-4.1-mini snapshots. It demonstrates
mechanics; it does not select current frontier models or establish a scientific ranking.
The judge shares a family with both candidates and is itself one candidate, which can
bias results. Select and freeze an independent judge for a serious study.

## Three-candidate pilot

A ready-to-run profile compares GPT-5.6 Sol, Terra and Luna with the same Astra judge
and low reasoning effort for every candidate. Preview it from the repository root:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli run --scenarios data/prompts/suite_zh_v0.3.jsonl --config configs/benchmark.gpt56-pilot.yaml --output studies/gpt56-candidates-pilot --limit 3
~~~

Append --execute --max-requests 40 to generate nine responses and run eighteen judge
checks. Use --resume for the exact same completed run. The model identifiers are aliases;
requested and returned IDs are recorded, but these do not pin immutable backend revisions.

The completed local pilot accepted all nine comparisons as ties. It made 27 API calls
and established no winner on three independent scenarios. These candidates were compared
against each other, not directly against the earlier GPT-4.1 candidates. The judge remains
from the same provider; independent human validation is still needed.

## Configure your own experiment

Open the workbench's **Run models** page to enter model IDs and download bench-config.json.
Save it in the repository folder and use the generated commands. The page creates
configuration only; API requests run in your Python process. It never receives API keys.
Candidate and judge parameter profiles are independent. The browser defaults to standard
chat candidates and a low-effort Astra judge; the YAML smoke preset above retains the
original GPT-4.1 judge for comparison.

The YAML/JSON config has a shared system_prompt, a systems list and one judge entry.
Add more systems in the file to compare more than two. Each system supports its own
base_url and api_key_env, so candidates can come from different providers. Keep exact
model identifiers or snapshots where supported. The run stores requested and
provider-returned model identifiers.

For OpenRouter, use its compatible endpoint and an OPENROUTER_API_KEY environment
variable; use exact model IDs from your provider account. For a local compatible server,
use its localhost URL and an environment variable containing its expected bearer value.
This adapter uses /chat/completions; it does not support unrelated provider-native APIs.

The provider accepts optional reasoning_effort and token_parameter. For a reasoning
model that disallows sampling parameters, set temperature: null and top_p: null,
token_parameter: max_completion_tokens, and a suitable completion-token allowance.
That allowance includes reasoning tokens on models that account for them this way.
The browser reasoning preset uses low effort and 4096 tokens; check the selected model's
supported settings before executing. An exhausted token allowance fails explicitly.

Use judge.response_format: json_schema for strict Structured Outputs, or json_object for
providers that implement only JSON mode. Both paths validate locally against the same
schema. Malformed JSON, wrong types and extra fields exclude the pair, retain the raw
output, and do not automatically trigger more paid calls. API failures or truncated
completions stop the run for inspection; they do not silently produce a ranking vote.

To rank existing native-generation responses, add --responses path/to/responses.jsonl.
The selected inputs must contain exactly one response per declared system/scenario cell.
This skips candidate generation but still requires the configured judge and request cap.
For humanization, use the existing source-preserving generation and human-study workflow;
the integrated automatic runner currently covers native generation only.

## Read the results

| Artifact in the run directory | Meaning |
| --- | --- |
| report.json | Import into Results; explicitly labeled model-judged screening |
| responses.jsonl | Candidate texts, hashes and generation provenance |
| model-judgments.jsonl | At most one accepted model judgment per pair |
| judge/observations.json | Both display orders, exact rubric, raw output, input hashes and provider metadata |
| requests.json | Every reserved HTTP attempt, including failed or unknown outcomes |
| run.json | Frozen scenario selection and requested configuration; no API key values |
| human-study/public/rater-*.json | Three blinded packets for independent human validation |

The judge checks audience fit, facts, intent, commitment strength and usefulness.
It sees scenario content and anonymous candidate texts, without model names or dataset
authoring metadata. A rubric instructs it to treat candidate instructions as untrusted
data; this reduces but does not eliminate prompt-injection risk.

Both display orders must agree on preference **and both send/revise/reject actions**.
Agreement yields one canonical vote. Order-sensitive decisions, abstentions and invalid
outputs yield no vote; they are never converted into ties. A tie means a stated equality
of preference. These checks measure repeatability under order reversal, not judge accuracy.
The report exposes exclusions and their reasons; accepted-only results can be biased.

Accepted comparisons feed the existing regularized Davidson–Bradley–Terry estimator
with ties and scenario-family bootstrap. There is no second position-effect fit: the
two-order acceptance rule already filters the observations. If accepted comparisons do
not connect every declared system, the global ranking is withheld. Few scenario groups,
few successful bootstrap fits or optimizer problems also limit interpretation.
Intervals condition on the fixed judge and acceptance rule; they do not quantify judge
error or human population preferences. Judge-predicted direct use is labeled separately.

## Validate with people

Human packets are frozen before judge calls. Distribute the three packets to three
independent raters and collect exported JSONL files. Then:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli evaluate --study studies/first-model-run/human-study --exports exports/rater-001.jsonl exports/rater-002.jsonl exports/rater-003.jsonl --output studies/first-model-run/human-report.json
~~~

Import human-report.json into Results to view the human estimates. The importer rejects
model evidence in human packets, and the estimator rejects mixed evidence kinds.
Do not select only automatically accepted pairs for human validation: inspect the entire
frozen comparison set, including excluded cases. The runner provides packets; it does
not recruit participants or establish population validity.

## Combine multiple batches

For additional disjoint scenario batches using the same configuration, see
[Combine completed model batches](combine_runs.md). This creates pooled estimates,
an exclusion-sensitivity diagnostic, a combined judge audit and new blinded assignments
without making further API calls. It does not turn model predictions into human evidence.

## API references and model configuration

Configuration was checked against official documentation on 2026-09-13:
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[GPT-4.1](https://developers.openai.com/api/docs/models/gpt-4.1),
[GPT-4.1-mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini), and
[model parameter guidance](https://developers.openai.com/api/docs/guides/latest-model).
Provider availability, supported parameters and prices can change. Consult the provider
for your chosen models before a paid run.
