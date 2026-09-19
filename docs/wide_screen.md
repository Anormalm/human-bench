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

## Add depth without repeating paid calls

An existing study can be extended with more scenario families in a new directory:

~~~powershell
.\.venv\Scripts\python.exe scripts/run_wide_screen.py --extend studies/wide-150-rerouted --output studies/wide-18 --additional-scenarios 12 --budget-usd 6
.\.venv\Scripts\python.exe scripts/run_wide_screen.py --output studies/wide-18 --resume --execute --workers 16 --request-interval 0.25 --bootstrap-samples 300
~~~

Preparation validates the earlier evidence without rewriting its report, retains
its complete-generation model cohort, and freezes all new pairings before new
responses arrive. Existing compatible generation and judge records are reused;
their original charges remain included in the local allowance. Added scenarios
come from unused semantic/template families in the supplied full suite, balancing
genre counts with a fixed seed. The full suite hash and selected family map are
saved. This broadens public scenario coverage; it does not create a private test set
or replace native-speaker review.

The cohort stays fixed on subsequent extensions. New missing or truncated responses
skip only affected pairs, and do not become preference losses. Models with partial
generation coverage can retain a point estimate from their available connected
comparisons; the table marks that status and shows the missing coverage. Compare
models cautiously when missingness differs. Rank changes relative to the earlier
snapshot are descriptive, not evidence that a model improved or that ranks differ
significantly. Bootstrap intervals still follow the connectivity and degeneracy rules.

Serve both snapshots with:

~~~powershell
.\.venv\Scripts\python.exe scripts/serve_web.py --port 8043 --wide-report studies/wide-18/wide-report.json --wide-baseline studies/wide-150-rerouted/wide-report.json
~~~

The Study selector switches between the current study and earlier snapshot. The
earlier report remains available while the expansion is running. Rater-only servers
also block the baseline endpoint.

## Add models to an existing ranking

Enroll exact catalog IDs in a new study while retaining every previous response,
comparison, charge and uncertain reservation:

~~~powershell
.\.venv\Scripts\python.exe scripts/run_wide_screen.py --add-models-from studies/wide-18 --catalog model-catalog.json --model-ids anthropic/claude-sonnet-5 openai/gpt-5.6-sol --output studies/wide-enrolled --additional-budget-usd 2
.\.venv\Scripts\python.exe scripts/run_wide_screen.py --output studies/wide-enrolled --resume --execute --workers 12 --request-interval 0.25 --bootstrap-samples 300
~~~

`configs/wide_models.expansion.json` records the 28-ID selection checked on
2026-09-19. In PowerShell, load it with
`$additionalModelIds = Get-Content configs/wide_models.expansion.json -Raw | ConvertFrom-Json`
and pass `--model-ids $additionalModelIds`. Recheck a fresh catalog and the source
cohort before preparing; duplicates and models outside the price limits fail.
The leaderboard's **Newly added models** filter selects the enrolled IDs while
preserving their positions in the full-study ranking.

Availability and prices must pass validation against the saved current catalog;
these example IDs are not a promise of future availability. New candidates must
advertise text output, token-limit support, no per-request charge, input pricing
at most $3/M and output pricing at most $15/M. Judge IDs, canonical duplicates,
routing aliases and known specialist categories are excluded. Each new model's
provider limits allow at most 10% above its catalog token prices, bounded by those
ceilings. Prior candidate and judge requests retain their original limits.

`--additional-budget-usd` caps **new scheduling allowance**, unlike the total
`--budget-usd` used by other preparation modes. The plan adds imported accounted
costs to that allowance; final provider billing remains external. Expensive token
allowances reserve more before dispatch, even when the visible answer is short.
No automatic retries or allowance increases occur.

The frozen schedule retains all old pairs. For every existing scenario, each new
model receives two seeded opponents from the prior models with complete responses.
Selection uses availability, not rank or judge outcomes. Old models consequently
receive unequal additional comparisons. All accepted evidence is refitted jointly;
new models without an accepted connection have no global rank. New generation
failures skip affected pairs and remain visible without removing the whole model.

The source must have finished dispatching its scheduled work. New scenarios,
prompts, judge versions and decoding changes are outside this enrollment mode.
The 2,048-token cap and economical reasoning configuration are preserved; this
does not measure every model's maximum reasoning capability. Changing the cohort
can move existing ranks without any model having improved. Model aliases and
provider revisions also limit comparisons across collection dates.

Preparation and offline reanalysis verify the saved evidence and source chain.
Resume checks the frozen inherited and bridge schedule before dispatch. Keep all
source directories intact. Further model enrollment is supported; adding scenario
families after enrollment currently requires a separate protocol.

## Recover a provider and rebuild offline

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

Open the [model leaderboard](http://127.0.0.1:8043/wide). Search or filter by model
organization and response coverage, and sort table columns by point rank, name,
rank movement, usable scenarios, accepted comparisons, or reported generation cost.
Reset filters also restores rank order. The default Charts view shows four plots:

- Stacked win/tie/loss bars show raw accepted-comparison counts for the top 10,
  20, or 50 matching ranked models. All bars share a zero-based count scale and
  stay in point-rank order. Bar length measures accepted evidence volume, not
  model quality; opponents and coverage differ, and the ranking adjusts for
  opponents. Missing and rejected comparisons do not become losses.
- Response coverage shows usable versus missing, failed, or pending responses
  across **all models matching the filters**, including unranked models. Its
  denominator is their scheduled model–scenario responses.
- The judge-agreement donut shows outcomes for **all scheduled pairs in the
  selected study**, unchanged by model filters. It separates counted comparisons,
  changed judgments, invalid/missing judge output, missing candidate responses,
  and other/pending outcomes. Agreement is not evidence of judge correctness.
- Rank uncertainty shows the same selected models' point estimates and available
  95% scenario-bootstrap intervals. Endpoints round outward to whole ranks;
  missing intervals remain explicitly unavailable.

Selecting a model in either comparison plot finds it in the Rankings table.
Chart legends include counts and denominators, and the model bars expose their
values to keyboard and screen-reader users. Search, organization, coverage,
study selection, and chart limits update the relevant plots together.

Summary cards describe the selected study, including reused records. Per-model
generation costs exclude judge calls and unknown charges; they are not catalog
prices or comparable per-task cost estimates. Run & cost and Study limits &
exclusions disclose the complete accounting and exclusion details. The layout takes
visual inspiration from [Artificial Analysis](https://artificialanalysis.ai/leaderboards/models)
while using this benchmark's own measurements and identity.

It refreshes automatically during a run. The new report option can be combined with
the existing `--report`, `--bundle`, `--judge-audit` and `--collection` options.
Rater-only servers do not expose the leaderboard, its script or stylesheet, or its
report endpoint.

Offline reanalysis reconstructs requests from the frozen plan, verifies saved raw
records against ledger hashes, checks the exact seeded schedule, and reproduces
the ranking. It refuses changed, missing completed, or unexpected evidence. Hashes
provide local integrity checks, not independent signatures or proof of an immutable
remote model version. Preserve an external copy of the frozen plan and ledger for
an auditable study.
