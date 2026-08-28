# Shuorenhua Bench v0.2 alpha — benchmark card

## Claim boundary

Shuorenhua Bench measures population- and context-conditioned preferences, direct-use
decisions, revision behavior, semantic preservation, and interpretable text diagnostics.
It does not define a universal human-likeness score and does not treat AI-source detection
as a proxy for writing quality.

## Current alpha asset

- 24 benchmark-authored, native Chinese messaging scenarios.
- Seven genres, four relationship types, and six communication intents.
- Explicit required facts and prohibited changes for every scenario.
- OpenAI-compatible generation runner with model/configuration provenance.
- Deterministic, position-balanced pair construction.
- Browser-based blinded A/B/tie and send/revise/reject annotation.
- Tie-aware Davidson–Bradley–Terry estimation with prompt-clustered bootstrap intervals.
- Wilson intervals for direct-use rates and entropy-based disagreement reporting.
- Leakage-resistant grouped splitting by semantic cluster and source template.

The alpha scenarios are suitable for protocol testing, not final population claims. No
system result is publishable until outputs are generated from declared model snapshots and
each comparison receives independent human judgments from a documented sample.

## Evidence inherited from prior work

- [Measuring AI “Slop” in Text](https://arxiv.org/abs/2509.19163) motivates explicit
  construct work and span-level problem localization rather than relying on a binary slop label.
- [HumanEval-MGT](https://aclanthology.org/2026.acl-long.639/) shows that source
  detectability and human preference are distinct constructs, so this benchmark separates them.
- [Register-Aware Linguistic Evaluation](https://arxiv.org/abs/2605.23651) motivates
  comparing linguistic distributions within matched registers; register distance remains a
  diagnostic and is never interpreted as quality by itself.
- Pairwise reward-model research motivates blinded comparisons, but automated evaluators
  are optional and must be calibrated on held-out human observations before use.

## Minimum credible pilot

1. Freeze 50–100 scenarios after cognitive interviews with target users.
2. Compare at least four declared systems, including a raw-model baseline and rewrite baseline.
3. Collect at least three independent judgments per pair, increasing coverage for high-disagreement pairs.
4. Pre-register primary slices and exclusions before inspecting system rankings.
5. Report prompt-clustered uncertainty, rater disagreement, and population slices.
6. Keep hidden scenarios, model-family holdouts, and adversarial formulaicity cases.

## SOTA gate

The repository may call itself a state-of-the-art *measurement framework* only after it
demonstrates, on held-out data, higher human-distribution agreement or stronger reliability
than declared baselines. Engineering completeness or use of frontier models is not evidence
of SOTA performance.

