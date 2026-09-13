# Collect independent human judgments

Use a separate rater-only site for recruited participants. The research workbench exposes candidate identities and judge decisions on its other pages, which can influence human judgments.

## Build and run locally

From the repository root, after preparing a frozen study:

```powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli rater-site `
  --study studies/gpt56-combined-32/human-study `
  --output studies/rater-site

.\.venv\Scripts\python.exe scripts/serve_web.py `
  --port 8044 --rater-site studies/rater-site
```

Open `studies/rater-site/README.md` for the assigned links. This coordinator file lists one random URL per assignment and its workload. For the current 32-scenario study, twelve raters receive 23-25 comparisons each: three assigned raters per comparison and 288 planned judgments. Give each rater only their own link.

The server binds to `127.0.0.1` by default. These URLs work on this computer; sending a localhost URL to another person will not give them access. This command does not deploy anything or recruit participants. Remote use needs a separately configured host and origin. If hosting static files later, publish only the `site/` subdirectory, disable directory listings, and keep the coordinator files private. `--base-url` sets the origin used in the coordinator links; it does not configure networking or TLS.

## Participant workflow

1. Read the bilingual instructions and begin the assigned packet.
2. Read each situation and its facts. Choose A, B or a tie, then independently assess both responses as send, revise or reject. A tie is allowed even when both responses need work.
3. Save each judgment. Resume using the same browser and origin; progress is keyed to study, packet and assigned pseudonym.
4. Export saved judgments, then return the JSONL file to the coordinator. A copyable JSONL preview is available when the browser does not provide a download. Save the preview as UTF-8 with the displayed filename.

Answers remain in browser storage until the participant returns the file. The server is read-only and does not collect answers. There are no speed or confidence exclusions in the page. Raters should work independently and avoid consulting the model leaderboard or other judges. Recruit and document an appropriate native-speaker population; the software does not establish population representativeness.

## Coordinator import

Keep all human judgments separate from model screening reports. For example, once actual participants return exports:

```powershell
.\.venv\Scripts\python.exe -m shuorenhua_bench.cli evaluate `
  --study studies/gpt56-combined-32/human-study `
  --exports exports/rater-001.jsonl exports/rater-002.jsonl exports/rater-003.jsonl `
  --output studies/gpt56-combined-32/human-report.json
```

Include all returned files, including the remaining nine raters for a twelve-rater study. Three files alone generally do not cover every comparison. The importer verifies study, assigned pseudonym, displayed response order, evidence kind and duplicates. Incomplete coverage remains visible in the report; do not interpret it as a complete ranking. Keep the original frozen study and its private mapping for import.

The rater site preserves the original opaque response aliases, display order and packet identity. Extra metadata and titles are projected out of the public JSON. It never serves the model report, judge audit, raw model files, private mapping or coordinator index, even when workbench report environment variables are configured. Responses themselves are unchanged and could contain clues to their origin.

`site-manifest.json` freezes public file hashes. The server verifies the declared files and serves their in-memory snapshot through a fixed route allowlist. Changes require a new site directory. An update from the same frozen study retains packet identities and therefore browser progress on the same origin, even though newly generated links differ. Keep each participant on their assignment. Random links are not authentication and do not prove who supplied the answers.

## Validation performed

Server tests cover blocked private/workbench routes, manifest path restrictions, frozen file integrity, packet identity and orientation, synthetic/human labels, and strict import compatibility. A separate synthetic browser fixture exercised incomplete-save rejection, save, reload/resume, JSONL export preview and import, plus isolation between two assignments. No test judgments were added to the real model study.
