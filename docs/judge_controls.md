# Constructed judge controls

The `judge-controls` command checks a fixed judge on a small, explicit set of
constructed comparisons. It is a diagnostic beside the candidate benchmark.
It does not create a leaderboard, human-study packet or human labels.

The bundled six checks include four deliberate violations and two equivalence
checks: a changed time, an unsupported recovery guarantee, a password request,
a reversed workload commitment, identical text, and two expressions of 10:20.
The source scenarios and expected outcomes are fixed before the calls.

These are author-declared expectations, not measured human preferences.
Passing them shows sensitivity on these particular checks; it does not establish
accuracy on subtle quality differences, natural writing or human preference.
Several controls share a source scenario, so the six checks are not six independent
population samples.

Preview without any API calls:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli judge-controls --controls data/controls/judge_sensitivity_v05.json --config configs/benchmark.gpt56-pilot.yaml --output studies/astra-judge-controls-v05
~~~

Execute twelve judge completions with a cap of sixteen HTTP attempts:

~~~powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli judge-controls --controls data/controls/judge_sensitivity_v05.json --config configs/benchmark.gpt56-pilot.yaml --output studies/astra-judge-controls-v05 --execute --max-requests 16
~~~

Add `--resume` to continue the same run or reuse completed observations.
A changed fixture, expected answer, judge setting, seed or request cap is rejected.
The cap includes retries and unknown outcomes. It is a request count, not a dollar budget.

Each pair is shown in both orders. The judge receives only the scenario fields
and candidate texts; control IDs, expectations and explanations are omitted.
All inputs and raw judge outputs are preserved with hashes.

A control passes only if both orders match the declared preference and acceptable
action labels, and also satisfy the unchanged full acceptance rule: preference and
both individual action labels must agree across display orders. For a flawed
response, revise and reject are both acceptable actions, but a judge that alternates
between them still fails the full consistency requirement. The report shows preference
matches, action matches and full passes separately.

The result is `control-results.json`, explicitly labeled
`model_judged_constructed_controls`, with zero human judgments. Every individual
observation and expected outcome is available there. Do not pool these controls into
the candidate ranking or a human-calibration report.
