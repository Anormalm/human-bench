# Track returned human assignments

The Collection page is a coordinator view of a saved snapshot. It shows returned judgments, remaining work, complete assignments, fully rated comparisons, genre coverage and comparison-graph connectivity. It does not score models or change the primary evaluation rules.

## Create the first snapshot

A study can be inspected before any participant returns a file:

```powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli collection `
  --study studies/gpt56-combined-32/human-study `
  --output studies/gpt56-combined-32/collection-initial.json
```

This retains all planned assignments and models, including models with zero observations. Missing work remains missing; it is not filled in as ties or assumed rejections.

## Update after receiving files

Keep participants' JSONL returns in a dedicated local folder. Read all `.jsonl` files directly inside it, or pass explicit paths with `--exports`:

```powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli collection `
  --study studies/gpt56-combined-32/human-study `
  --exports-dir exports/combined-32 `
  --output studies/gpt56-combined-32/collection-round-01.json
```

The folder must exist. Snapshots use a new output path so earlier reports are preserved. No API calls are made and no votes are excluded by time, confidence or disagreement.

The command reuses the strict study importer. It checks study and assignment identities, frozen display orientation, evidence kind, response mappings and problem spans. Identical repeated rows are ignored, including overlapping partial and complete exports from one rater. Distinct assigned pseudonyms determine the rater count; exporting again does not add a rater. Conflicting duplicates or malformed files abort snapshot creation. Resolve the source files explicitly and retain your audit trail; there is no automatic last-file-wins policy.

Input filenames, SHA-256 hashes, raw row counts, assignments and duplicate counts are recorded. Empty input files are listed. Files that change during validation are rejected. Keep the original study intact.

## Read the coordinator page

Import the snapshot into **Collection**, or configure the local workbench:

```powershell
.\.venv\Scripts\python.exe scripts/serve_web.py --port 8043 `
  --report studies/gpt56-combined-32/report.json `
  --judge-audit studies/gpt56-combined-32/judge-audit.json `
  --bundle studies/gpt56-combined-32/human-study/public/rater-001.json `
  --collection studies/gpt56-combined-32/collection-round-01.json
```

This is a saved snapshot, not a live inbox. Browser-local judgments do not appear until the participant exports them, you receive the file, and you generate a new snapshot. Import the new snapshot to refresh the page. The rater-only server does not expose `/api/collection`, even if a workbench collection path is configured in its environment.

Three separate conditions matter:

- **All assigned judgments returned:** the original assignment workload is complete.
- **All models connected by returns:** returned comparisons connect every model in the study track. One completed assignment may already connect the graph, but the other raters can still be missing. Fully rated comparisons are checked separately.
- **Ready for planned analysis:** all assigned judgments are present, the returned graph connects every model, and there are no missing generation cells.

Readiness is structural. It does not establish eligibility, independent recruitment, reliable uncertainty, statistical separation or a winner. Assigned pseudonyms are not proof of different people. Fewer than 30 scenario-family groups with returns remains an exploratory sample. Synthetic practice snapshots remain labeled synthetic and contribute zero human judgments.

When the planned data is available, use the existing `evaluate` command with the original study and all returned exports to fit the human report. Keep that report separate from the automatic model-judge screening report. See [human validation](human_validation.md) for the participant workflow.
