# Benchmark card · v0.3

| Property | Current release |
|---|---|
| Construct | Contextual preference and direct use |
| Language | Simplified Chinese, zh-CN |
| Candidate scenarios | 72: 24 legacy alpha + 48 new AI-authored |
| Human-reviewed new scenarios | 0 |
| Consented human reference responses | 0 |
| Measured real-model results | None in the bundled report |
| Demonstration | 48 scenarios, 3 controlled fixtures, 144 pairs, 432 synthetic votes |
| Tracks | Native generation; shared-source humanization; analyzed separately |
| Primary model | Regularized Davidson–Bradley–Terry, optional identifiable position effect |
| Intervals | Connected semantic/template group bootstrap, conditional on observed raters |
| Annotation | Blind per-rater packets, local browser storage, JSONL export |
| Population validity | Not yet established |
| Protected holdout | Not included |
| Automatic judge | Not included |
| SOTA claim | None; this is study infrastructure |

Read the [research protocol](research_protocol_v03.md) for the estimator, limitations,
sampling plan and milestones required for a credible public result. Read the
[data documentation](../data/README.md) for provenance and the distinction between
controlled fixtures, AI-authored candidates and human references.
