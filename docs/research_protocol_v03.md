# Research protocol · v0.3

## Construct and estimands

Measure contextual acceptability and direct use for a specified Chinese-speaking population,
communication setting, relationship and task. The primary observation is the distribution of
A/B/tie choices between responses to the same scenario. The secondary observation is whether
the participant would send each response unchanged, revise it, or reject/rewrite it.

Native generation, rewriting, authorship detection and diagnostics answer different questions.
Do not combine them into a universal naturalness score.

## Implemented estimator

For displayed systems a and b, log strengths θ, position coefficient β and log tie parameter λ:

~~~text
z_A   = θ_a + β/2
z_B   = θ_b - β/2
z_tie = (θ_a + θ_b)/2 + λ
P(outcome) = softmax(z)
~~~

The optimizer minimizes the sum negative log likelihood plus 0.01/2 times the squared parameter
norm. System abilities are centered after fitting. The weak fixed regularizer makes
complete separation and all-tie samples finite. It affects sparse estimates and is not a
learned population hierarchy. L-BFGS convergence and gradient diagnostics are reported.

Position is adjusted only if the design matrix can identify it separately from system
contrasts. A disconnected comparison graph is rejected. Bootstrap resamples lacking a
system, connectivity or required position identifiability are skipped and counted. Globally
centered scores from different connected components are never compared.

Uncertainty resamples connected scenario groups sharing semantic or source-template IDs.
All judgments in a selected group stay together, including transitive links. Without scenario
metadata, grouping falls back to prompt IDs with a warning. One group cannot support an interval.

Repeated action labels for the same response/rater are averaged to one fractional observation.
This avoids inflating the direct-use denominator when a response appears against multiple
opponents. Conflicts remain visible. Direct-use intervals resample the same scenario groups.

Agreement canonicalizes display order before counting votes. Entropy and raw pairwise agreement
use only pairs with at least two raters. A single vote is not agreement. Confidence never
silently weights votes. Elapsed time is a diagnostic, not measured editing burden.

Reports give neutral-position win/tie/loss probabilities, tie-adjusted preference, ability
differences, pointwise percentile intervals and exploratory Bonferroni-adjusted percentile
intervals. These are approximate, not exact familywise coverage guarantees. Use at least
1,000 resamples for a pilot and more for many contrasts. Rank intervals describe resampling
variability, not simultaneous rank confidence sets. Sparse resamples and failures remain disclosed.
The exploratory separation flag requires convergence, at least 30 groups, at least 100
attempted resamples and no more than 10% discarded fits; it is not a publication-readiness gate.

## Evidence boundaries

- The included 48-case, three-fixture report has 432 **simulated** votes. It tests software.
- There are 72 scenario candidates: 24 legacy alpha cases and 48 newly AI-authored cases.
  New cases are not native-speaker-reviewed, representative, or protected held-out data.
- There are no consented human reference answers or recruited annotators in this release.
- Bootstrap conditions on observed annotators. Shared rater effects across prompts are not
  separately modeled. Population inference needs an appropriate recruitment design and
  a validated crossed-effects model or resampling approach.
- Synthetic construction, common authoring style, leakage, provider drift, correlated outputs,
  length preference and convenience recruitment remain validity risks.
- Optional spans have no complete annotation denominator. Report counts, not error prevalence.
- Manifest hashes are integrity receipts, not signatures or external preregistration.
- Assignment pseudonyms do not authenticate participants. Local storage is not a managed
  collection backend. The development server should not be exposed as a production service.
- No automatic judge or detector substitutes for human observations.

## Stage 1: defensible pilot

Begin with 40–60 independently reviewed scenario families. Have at least two native speakers
review plausibility, ambiguity, facts, sensitivity and register. Resolve scenario defects
before generation; preserve meaningful disagreement about response preferences.

Declare the target population and recruit independently of system authors. Record relevant
language background and communication experience with consent. Keep contact information
separate from pseudonymized exports. Document recruitment and compensation.

Collect human references from real contributors under the same context and constraints.
Store author pseudonyms and metadata fields source, consent and license. Exclude author
self-comparisons and organizer conflicts manually. Do not relabel AI drafts as unaided human text.

Use three or four declared system configurations from different families plus human references
when available. Lock prompts, decoding, model IDs, fixed rewrite sources, data selection,
primary analyses and exclusions before collection. Generate one response per system/scenario
initially; use separate versioned studies for replicates so Cartesian pairing does not
accidentally alter exposure.

Assign at least three distinct participants per pair. Avoid multiple comparisons from one
scenario per participant where the rater pool permits. The scheduler prefers this and
balances workloads, but cannot guarantee it with a small pool. A/B orientation is balanced
within each pair's assignments; odd replication differs by one presentation.

Do not ask raters to identify the model. Both responses may be rejected and preference tied.
Source identification belongs in a separate study. Supply training examples outside analysis data.

Review timing, missing fields, action conflicts and side-choice patterns without automatically
excluding fast or dissenting raters. Predeclare quality exclusions and publish sensitivity
analyses. The importer rejects structural corruption; it does not adjudicate human honesty.

## Stage 2: preregistered benchmark release

1. Expand to at least 200 independent families per track, increasing this if the target effect
   or pilot variance requires it. A raw row count is not independent sample size.
2. Broaden domains and relationships using a deliberate sampling frame. Report slice coverage
   and population weights. Do not call the public candidates representative Chinese usage.
3. Reserve newly authored access-controlled evaluation families. Keep paraphrases and templates
   together. Date and rotate holdouts; a public split is not a protected test.
4. Repeat generations to measure decoding sensitivity. Use provider snapshots where available
   and state when the provider does not expose an immutable revision.
5. Recruit enough annotators to assess population variation. Preregister a crossed-effects
   extension before claiming population-level uncertainty.
6. Include controlled perturbations for factual drift, certainty, padding and register.
   Use blinded human ratings to test their effects. Their intended direction is a hypothesis,
   not an automatic preference label.
7. Publish contrasts, uncertainty, direct-use distributions, slice coverage, disagreement,
   exclusions, missing generations and provenance permitted by consent and licenses.

The planner uses a normal approximation for binary preference against .5, Bonferroni
multiplicity, and design effect 1+(m−1)ICC. It ignores ties, unequal group sizes and nuisance
estimation. Under four systems, three raters, ICC=.25 and a ten-percentage-point effect,
its approximate target is 150 groups per contrast. A 200-group round robin produces
1,200 pairs and 3,600 judgments. This is sensitivity planning, not validated Davidson power.

## Stage 3: optional scalable evaluator

After collecting adequate independent human data, train one preference model to predict
held-out human distributions. Separate training, calibration and evaluation by scenario
and model families. Report log loss, Brier score, calibration, subgroup errors, abstention
and out-of-domain behavior. Re-audit after model/population changes. Never claim calibration
against humans using simulated fixture labels.

## Preregistration record

Complete configs/study_protocol.template.yaml and freeze it beside a trusted input manifest
before the first analysis vote. The CLI freezes its default protocol; the extended template
is an organizer record, not a claim that every field is machine-enforced. Record amendments,
dates, reasons and whether outcomes had already been inspected.

## Methodological references

- [Chatbot Arena](https://arxiv.org/abs/2403.04132) motivates blinded pairwise observations
  and statistical human-preference evaluation.
- [Measuring AI “Slop” in Text](https://arxiv.org/abs/2509.19163) motivates interpretable
  problem spans and careful treatment of subjective labels.
- [Length-Controlled AlpacaEval](https://arxiv.org/abs/2404.04475) motivates investigating
  length as an evaluation confound. v0.3 does not implement that paper's estimator or
  assume its validity transfers automatically.

These works inform design choices; they do not validate this dataset or establish SOTA.
