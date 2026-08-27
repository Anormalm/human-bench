# Annotation guidelines — V0.1

Judge the response **inside the supplied communication context**. Do not guess whether it was written by AI, and do not reward or punish surface markers merely because they are associated with AI systems.

## Core tasks

1. **Pairwise preference:** Which response would work better for this speaker, recipient, channel, relationship, and intent? Choose `A`, `B`, or `tie`.
2. **Behavioral action:** For each response, choose `send` if you would use it unchanged, `revise` if a local edit could make it usable, or `reject` if substantial rewriting is needed.
3. **Confidence:** Report confidence from 1 (very uncertain) to 5 (very certain). Uncertainty and legitimate disagreement are data, not annotation failure.
4. **Problem spans:** When requested, select only the smallest exact span causing a problem and assign a taxonomy type.

## Required checks

- Does it preserve every required fact, number, entity, date, risk, and promise?
- Does it actually perform the requested communication act?
- Is its register plausible for the relationship and channel?
- Is every sentence locally useful?

Do not see system names, provenance, or other annotators' judgments. Source-detection questions belong to a separate task and must never appear on the same annotation screen.

