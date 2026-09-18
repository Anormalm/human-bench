# Judge audit and human-reference comparison · v0.5

Automatic preference is a measurement procedure that needs validation. This release
adds an offline audit of that procedure while preserving the original acceptance rule:
a ranking vote requires agreement on preference and both action labels across the
two display orders. No rule was relaxed after seeing the first pilot.

## Inspect judge repeatability

Run each judge on identical saved candidate responses, with separate output directories.
The Astra example reuses the completed first pilot:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli run --scenarios studies/first-model-run/scenarios.jsonl --responses studies/first-model-run/responses.jsonl --config configs/benchmark.astra-judge.yaml --output studies/astra-judge-pilot --execute --max-requests 12
~~~

This requests six judge completions for three pairs and caps total HTTP attempts at 12.
For the completed local example, add --resume to inspect/reuse the same run. No candidate
generation is required. The config uses low reasoning effort and omits unsupported sampling
parameters, consistent with [OpenAI's model guidance](https://developers.openai.com/api/docs/guides/latest-model).
The requested [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) identifier
is an alias; the returned identifier is recorded, but it does not pin an immutable backend revision.

Compare the saved judges without any API calls:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli compare-judges --runs studies/first-model-run studies/astra-judge-pilot --output studies/judge-comparison-v05.json
~~~

Import the JSON file under **Judge audit**, or serve it:

~~~powershell
.\.venv\Scripts\python.exe scripts/serve_web.py --port 8043 --judge-audit studies/judge-comparison-v05.json
~~~

The audit verifies frozen scenarios, response/output hashes, pair registry, judge
configuration, protocol hashes, each raw observation hash, displayed response identities
and reconstructed input-prompt hashes. It computes diagnostics from raw responses instead
of trusting a previously exported report's derived votes. Runs using different candidate
texts, scenario contents or pair sets are rejected. Missing checks are reported explicitly.
The report records rubric and observation hashes; different rubrics produce a confounding warning.

The table separates preference consistency, action consistency and accepted comparisons.
Counts of comparable pairs exclude invalid and abstaining checks. The detail panels show
both original texts and every judge explanation. Display order is stated, and normalized
choices/actions use the fixed candidate labels on the audit page. A/B within an explanation
still refer to that check's original display positions.

Filters show all comparisons, inconsistent checks, or pairs with human observations.
The browser renders 20 comparisons per page. The audit is for coordinators: collect
human judgments independently before showing raters the model explanations.

## Compare with human judgments

Use a frozen human study with exactly the same comparison inputs. Export the independent
raters' JSONL files, then:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli compare-judges --runs studies/first-model-run studies/astra-judge-pilot --study studies/first-model-run/human-study --exports exports/rater-001.jsonl exports/rater-002.jsonl exports/rater-003.jsonl --output studies/judge-human-comparison.json
~~~

The existing importer verifies assigned identities and displayed orientations. Identical
duplicate exports are ignored; conflicting duplicates and synthetic/model evidence in
human packets are rejected. Reference exports and study-manifest hashes are recorded.

A reference needs at least three distinct raters per pair by default and a strict majority
for A, B or tie. The minimum can be declared with --min-human-raters. One A vote, one B vote
and one tie vote is unresolved disagreement, not a tie. Under-annotated pairs are reported
without a majority. All individual vote counts remain visible.

For each judge, the report shows:

- the number of pairs with an eligible human majority;
- the number also having a stable model preference;
- conditional agreement, a three-class confusion matrix and Cohen's kappa where defined;
- scenario-family bootstrap intervals where the sample supports a non-collapsed interval;
- descriptive agreement by ordinal confidence level.

Each pair contributes once. The two order checks are dependent observations, not two raters.
Cross-judge agreement uses the intersection of stable preferences and displays its coverage.
A preference that agrees across orders can enter this diagnostic even when action labels
disagree; the primary ranking still excludes that pair. This distinction is intentional.

These are agreement statistics against the recruited study's majority, not ground-truth
accuracy or population validity. Intervals condition on the comparable subset. Missing and
inconsistent cases can bias that subset. Confidence values 1–5 are ordinal, so the audit
does not interpret them as probabilities or report probability-calibration errors.

Without human exports, status is awaiting_human_judgments and human-alignment metrics stay
unavailable. Model-model consistency cannot substitute for human calibration.

## Reanalyze saved model observations

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli reanalyze --run studies/astra-judge-pilot --output studies/astra-judge-pilot/report-v05.json
~~~

This is fully offline. The CLI requires a new output path so previous analyses stay intact.
It reconstructs the original accepted votes and retains the original display orientations.
The report records its analysis version and source protocol hash.

Zero-width percentile intervals are withheld for ability, rank, direct use and pairwise
contrasts. Repeated identical bootstrap samples do not demonstrate zero uncertainty outside
the observed sample. If every observed preference is a tie, ranking_status is no_separation;
the dashboard states that no winner is established. A tied pilot also does not establish
population equivalence between the models.

## Live pilot findings

On the same three scenarios and six candidate responses, the first judge (GPT-4.1)
had stable preference on 1/3 pairs, stable actions on 2/3, and accepted 0/3 under the
full rule. GPT-6 Astra completed six additional judge calls and accepted 3/3, calling
all three pairs ties with both responses usable.

This is a tiny exploratory judge comparison. The result supports repeatability on those
specific cases; it does not establish that Astra is a calibrated judge, that the candidates
are equivalent, or that the benchmark is SOTA. Human judgments remain to be collected.

## Check sensitivity to clear differences

Use the separate [constructed controls](judge_controls.md) to test a judge on fixed
violations and equivalent text. These checks have author-declared expectations; they
are not human calibration and their results are not pooled into model rankings.
