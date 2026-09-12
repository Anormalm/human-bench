# Data provenance and release boundaries

- prompts/pilot_zh_messaging_v0.2.jsonl: 24 legacy cases labeled benchmark_authored.
  v0.3 does not add a claim that they received human review.
- prompts/challenge_zh_v0.3.jsonl: 48 new AI-authored scenario candidates. Each records
  human_review_status=pending, a challenge label and source/template grouping.
- prompts/suite_zh_v0.3.jsonl: the union, 72 candidates. No additional independent evidence
  is created by concatenating files.
- responses/challenge_fixtures.jsonl: 144 controlled software-test responses, including
  concise, padded and overpromising variations. None is a human-authored reference or a
  queried external model output. Their intended quality ordering is not ground truth.
- web/demo_bundle.json: one of 12 synthetic-demo annotation packets, with opaque IDs.
- web/demo_report.json: output of the actual estimator applied to 432 simulated judgments.
  The simulation strengths and seed are declared in scripts/run_demo.py.
- splits/suite_v03.json: public development partitions, not an access-controlled holdout.
- suite_audit_v03.json: structural/coverage audit; passing is not construct validation.

The new AI-authored candidates and controlled fixtures are offered under CC0-1.0.
The repository code remains MIT. Existing files retain their prior licensing status.
No real personal conversations were used in the new candidate scenarios.

Real responses should carry a GenerationManifest or human contributor metadata as appropriate.
For a human reference, use a pseudonymous author_id and metadata.source, metadata.consent and
metadata.license. Verify these externally: the fields themselves cannot establish permission.

Keep model keys, raw recruitment records, private study mappings and unblinded exports out
of public data folders. data/private/ and studies/ are ignored by Git. The server exposes only
the two explicitly configured JSON endpoints and the allowlisted web assets.
