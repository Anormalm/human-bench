# Budgeted screening across many models

The model sweep compares many inexpensive OpenRouter model IDs on shared scenarios.
It is a shortlist tool: six public, AI-authored scenarios and one automatic judge do
not establish a population ranking or a SOTA claim. Results stay separate from the
workbench's human studies and smaller full-pair comparisons.

## Prepare and run

Save a current public [OpenRouter model catalog](https://openrouter.ai/api/v1/models),
then prepare the frozen plan. Preparation makes no paid inference calls:

~~~powershell
Invoke-WebRequest https://openrouter.ai/api/v1/models -OutFile model-catalog.json
.\.venv\Scripts\python.exe scripts/run_wide_screen.py --catalog model-catalog.json --output studies/wide-150 --models 150 --scenario-count 6 --budget-usd 12
~~~

The default selection uses text-output models with advertised positive prices at or
below $1 per million input tokens and $3 per million output tokens. It excludes the
judge, routing aliases, colon variants and known specialist categories, deduplicates
canonical slugs, and rotates across organizations, newest versions first. Different
IDs may still share weights, training data or model families. Fewer eligible IDs
than requested is an error; the runner does not raise the price ceiling.

Review `plan.json` and `catalog-selected.json`. Keep the API key in the process
environment; on Windows, an already configured User environment key can be loaded:

~~~powershell
$env:OPENROUTER_API_KEY = [Environment]::GetEnvironmentVariable('OPENROUTER_API_KEY', 'User')
.\.venv\Scripts\python.exe scripts/run_wide_screen.py --output studies/wide-150 --resume --execute --workers 12 --bootstrap-samples 100
~~~

The saved plan controls resumed runs. Changing model count, prompts, decoding or
budget requires a new output directory. Existing successful and failed HTTP attempts
are reused; there are no automatic retries. Requests interrupted without a saved
response retain an uncertain billing reservation and are not automatically repeated.
A process lock prevents concurrent execution or reanalysis of the same study.
By default, new requests start at least one second apart; a rate-limit response
pauses new dispatches for 30 seconds without retrying the failed call. Use
`--workers 4 --request-interval 2` to reduce pressure further. Execution timing can
change on resume without changing the frozen prompts, models or comparisons.

## What the ranking means

- Scenarios are selected before generation with a fixed seed, one per genre and
  distinct semantic/template family. Every model receives the same six contexts.
- Candidate generation has a 2,048-token cap. Optional reasoning is disabled;
  mandatory reasoning uses an economical supported effort. These settings do not
  equalize computation. Truncated or empty output is unusable.
- Only models with usable responses to every selected scenario enter the comparison
  cohort. Failed generations remain visible and are not counted as preference losses.
- A seeded cycle assigns two opponents per model per scenario. Six scenarios give
  twelve planned comparisons per complete model. This costs O(models × scenarios),
  unlike a quadratic all-pairs tournament. Opponents are selected without reading
  preference outcomes. Availability still affects the evaluated population.
- The fixed judge, `openai/gpt-5.6-luna`, sees anonymized candidates in both orders.
  Both preferences and both send/revise/reject actions must agree after orientation
  normalization. Each accepted pair contributes one vote, including ties.
- Point estimates use the existing Davidson–Bradley–Terry fitter, with a fixed 0.01
  Gaussian regularization coefficient on the summed likelihood. Ranks cover only
  the largest connected accepted-comparison component. Unconnected models are not
  assigned a global rank. Point estimates can be strongly affected by sparse evidence
  and regularization; the top row is not a demonstrated winner.
- Exploratory 95% intervals resample whole scenario families. Intervals are withheld
  when over 10% of resamples lose connectivity or fail to converge, fewer than 20
  fits survive, or the interval collapses. Six families cannot provide reliable
  population inference. The report records all rejected fits. These intervals do
  not include model-judge error, selection bias, or variation across judges.

A/B reversal checks positional consistency, not correctness. The judge may favor
related model families or particular styles. Human validation on fresh, reviewed
scenarios is needed before promoting a shortlist into a substantive benchmark.

## Cost controls and records

Each request uses OpenRouter's [provider price limits](https://openrouter.ai/docs/guides/routing/provider-selection),
requires parameter support, chooses by price and disables provider fallbacks. The
local ledger reserves cost before dispatch under a thread lock, then settles against
`usage.cost` when available. Unknown costs keep their reservation across restarts.
Reservations allow at least 8,192 input tokens, or UTF-8 payload bytes plus overhead,
and twice the requested output allowance at the configured price ceilings.

This is a conservative local scheduling allowance, not an unconditional billing cap.
Provider token accounting and final billing may differ; credit purchase fees and
taxes are outside the inference report. A $12 plan leaves room within a $20 balance;
it does not imply that the run will spend $12. The runner stops scheduling when the
reservation or request limit would be exceeded.

Study files include the frozen plan, selected catalog, comparison schedule, request
ledger, raw request/response records, and `wide-report.json`. Raw error bodies can
contain provider/account metadata: keep the study directory private. It is ignored
by Git. Public report failure categories omit raw provider error messages.

## Rebuild offline and view

If a provider remains unavailable, preserve that pass and prepare a **separate**
judging study. This copies verified generation records and their cost reservations;
it does not copy any judge votes. The original plan stays frozen:

~~~powershell
.\.venv\Scripts\python.exe scripts/run_wide_screen.py --reuse-generations studies/wide-150 --judge-provider openai --output studies/wide-150-rerouted --budget-usd 4
.\.venv\Scripts\python.exe scripts/run_wide_screen.py --output studies/wide-150-rerouted --resume --execute --workers 4
~~~

The provider slug must be available for the same judge and still fit the frozen
price ceilings. Confirm this through the current model endpoint catalog before
execution. The new allowance includes reused generation costs and reservations.
Keep enough account funds for both passes; their allowances are independent.
The report separately totals unique request records across linked studies,
including the earlier pass, without double-counting reused generations. Keep
source studies unchanged and preserve their relative paths when moving files;
their frozen ledger hashes are verified during reanalysis.

No key or network connection is needed for offline reanalysis:

~~~powershell
.\.venv\Scripts\python.exe scripts/run_wide_screen.py --output studies/wide-150 --analyze-only --bootstrap-samples 100
.\.venv\Scripts\python.exe scripts/serve_web.py --port 8043 --wide-report studies/wide-150/wide-report.json
~~~

Open [Model sweep](http://127.0.0.1:8043/wide). The page shows searchable, paginated
ranks, incomplete models, comparison coverage, consistency exclusions and billing.
It refreshes automatically during a run. The new report option can be combined with
the existing `--report`, `--bundle`, `--judge-audit` and `--collection` options.
Rater-only servers do not expose the sweep page, its script, or its report endpoint.

Offline reanalysis reconstructs requests from the frozen plan, verifies saved raw
records against ledger hashes, checks the exact seeded schedule, and reproduces
the ranking. It refuses changed, missing completed, or unexpected evidence. Hashes
provide local integrity checks, not independent signatures or proof of an immutable
remote model version. Preserve an external copy of the frozen plan and ledger for
an auditable study.
