# Data layout

- `prompts/`: validated Scenario JSONL files
- `responses/`: immutable Response JSONL files and generation manifests
- `annotations/`: blinded pair assignments and normalized human observations
- `splits/`: grouped split manifests, never raw copies of sensitive data

Only consented, licensed, de-identified data may be committed.

`prompts/pilot_zh_messaging_v0.2.jsonl` contains benchmark-authored, realistic scenarios;
it is not a dump of private conversations. `responses/example.jsonl` contains controlled
smoke-test responses and must not be reported as human or model performance.

Real benchmark releases must preserve response provenance, collect consented human
observations, and publish a dataset card describing recruitment and sampling.
