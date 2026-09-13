# Combine completed model batches

`combine-runs` makes an offline report from disjoint, completed batches. Use the same candidate configuration, system prompt, judge rubric and decoding throughout. This command does not send API requests.

```powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli combine-runs `
  --runs studies/batch-01 studies/batch-02 `
  --output studies/combined `
  --bootstrap-samples 1000 --raters 12
```

The command verifies raw judge observations, candidate request fingerprints and output hashes, exact system/scenario coverage, matching protocols, and non-overlapping scenario IDs before writing. Reusing a batch or an output directory is rejected. Semantic and template families are clustered across the pooled inputs, including family links across batches. Shared families do not become independent observations because they were generated in separate runs.

Outputs:

- `combined-manifest.json`: source paths and hashes, configuration identity, pooled artifact hashes, and human study identity.
- `report.json`: unchanged primary rule (both orders agree on preference and both actions), pooled bootstrap intervals and per-genre summaries.
- `judge-audit.json`: all forward/reverse decisions, with each comparison's source batch.
- `sensitivity.json`: primary and stable-preference-only point fits, extra diagnostic comparisons, and worst-case score bounds for excluded pairs.
- `human-study/public/`: blinded assignments with three distinct raters assigned per pair; twelve packets by default. For 32 scenarios and three models, each packet has about 24 comparisons (workloads can vary to reduce repeated scenarios per rater), totalling 288 planned judgments.

All batches count as one fixed judge configuration. Original response texts and display orientations are preserved in the pooled records; the human packets receive a separately balanced blind display. Source artifacts are never overwritten. Control fixtures, synthetic evidence and rewritten responses are excluded from this workflow. `combined-manifest.json` identifies a derived analysis rather than pretending it is a new generation run.

## Interpreting sensitivity

The primary result still excludes action disagreements. The diagnostic separately keeps a preference only when it is stable across both orders, even when action labels disagree. It creates no action labels and no human evidence. These point estimates have no additional significance claim. An ordering change is evidence of sensitivity to the acceptance policy, not permission to select the policy with the preferred result.

The bounds use all planned comparisons as the denominator. For example, with 3 left wins, 5 ties, 1 right win and 1 excluded pair, the left score is bounded by 55% and 65%. This assigns the excluded pair to either side; it does not impute a vote into the report. The bounds are not confidence intervals.

Pooling more scenarios does not establish representativeness or human alignment. Mixed train/dev selections remain exploratory, and matching model aliases do not guarantee an immutable backend snapshot. Keep the selection record for each batch and inspect source-resolved model metadata. Do not treat the same fixed model judge as independent raters across batches.

## Open the combined result

```powershell
.\.venv\Scripts\python.exe scripts/serve_web.py --port 8043 `
  --report studies/combined/report.json `
  --judge-audit studies/combined/judge-audit.json `
  --bundle studies/combined/human-study/public/rater-001.json
```

Results includes the primary estimates and exclusion sensitivity. Judge audit shows raw rationales. If an old annotation packet is remembered in your browser, export any work first, then use **Load packet** to open your new assigned packet. Send only the public packet directory to raters; keep the private mapping and model report out of their blind annotation session.
