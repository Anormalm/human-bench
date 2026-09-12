# Changelog

## 0.3.0 · 2026-09-13

Turns the alpha into an end-to-end study workbench: freeze inputs, build blinded assignments,
collect local browser judgments, verify and unblind exports, then inspect estimates and gaps.

Adds 48 AI-authored challenge candidates (72 total), declared controlled fixtures, sample-size
planning, dataset audits, research protocol, regression tests and CI. Replaces the original
optimizer with a stable regularized Davidson fit and scenario-family bootstrap reporting.

Fixes identity leakage from raw response IDs, cross-study browser progress, duplicate votes,
invalid joins, cross-track comparisons, reversed-display agreement, repeated action counting,
unsafe resume across changed model configurations and silent truncated completions.

### Compatibility

The report schema is 0.3. Old Wilson and prompt-only interval fields are replaced with
group-bootstrap fields. Standalone bundles now require a private identity-map output.
Raw-ID v0.2 evaluation remains available with stricter validation. v0.2 generation files
cannot be resumed without request fingerprints; preserve them and start a new output.

### Evidence status

No SOTA result is claimed. New scenarios await human review, and the bundled report contains
only simulated votes. Population recruitment, human reference writing, protected holdouts,
crossed-rater inference and real model evaluation remain research work.
