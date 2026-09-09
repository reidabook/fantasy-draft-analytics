# Feature: Update Rankings (Page 6)

File: `pages/6_Update_Rankings.py`

---

## Purpose

Upload FantasyPros "Draft ALL Rankings" CSV exports without touching the CLI.
Three independent slots, one per scoring format (PPR / Half-PPR / Standard), plus
a shared bye-week upload. This is the app-native alternative to
`prefetch.py --local-csv PATH --scoring-type ... --local-bye-csv PATH` — same
underlying function (`pipeline.import_fantasypros_local()`), just fed from
`st.file_uploader` instead of a filesystem path.

## Why three separate uploads

FantasyPros ranks players differently per scoring format — a pass-catching RB
moves up in PPR vs standard — in a way that can't be derived from the raw stat
line the same CSV carries. Each format's CSV is stored as its own source
(`fantasypros_local_ppr` / `_half_ppr` / `_standard`), so uploading Half-PPR
rankings never overwrites PPR ones. Projected points, by contrast, don't need
three uploads: they're fully derivable from any one file's raw stat line for all
three formats at once (reception count doesn't change by format, only its point
value does).

`compute_vbd()` and `get_vbd_scores()` then pick whichever format-scoped source
matches the *active league's own* `scoring.type` first, falling back to the
other formats (then live-scrape/proxy sources) if that specific format hasn't
been uploaded yet — see `CLAUDE.md`'s "Scoring-format-scoped rankings" section.

## Layout

- **Rankings by format**: three columns (PPR, Half-PPR, Standard), each showing
  that format's current status (row count + last-updated, or "never uploaded")
  above its own `st.file_uploader`.
- **Bye weeks**: one shared uploader below — format-agnostic, can be used alone
  with no rankings file.
- **Import uploaded files** button: runs whichever slots have a file, in one pass.
  Uses whichever bye-week file was uploaded across all format imports in the same
  click (uploading it three times would be redundant — one `players.bye_week`
  update per player_id is all that's needed).

## Mechanics

`st.file_uploader` returns an in-memory `UploadedFile`, not a filesystem path —
`_save_upload()` writes its bytes to a `tempfile.NamedTemporaryFile` first, since
`fetcher.fantasypros_parse_local_csv()` expects a path (`open(path, ...)`). Temp
files are deleted in a `finally` block after each import, whether it succeeded or
raised.

## After uploading

VBD isn't recomputed automatically (same as the sidebar refresh buttons in
`app.py`) — go to **VBD Rankings** and click **↺ Recalc** for each league, or run
`python prefetch.py --vbd`.

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `src/data/pipeline.py` | `import_fantasypros_local()`, `SCORING_TYPES` |
| `src/data/cache.py` | `get_adp()`, `get_projections()` (status display) |

## Common Issues

| Symptom | Fix |
|---------|-----|
| "No players cached" error on import | Run `prefetch.py --full` first to populate the player directory |
| A format still shows "never uploaded" after import | Check the CSV is the stat-line variant (RK, TIERS, PLAYER NAME, TEAM, FANTASYPTS, ...), not the bye-week cheat-sheet variant |
| Rankings don't seem to change a league's board | Recalc VBD for that league (this page doesn't do it automatically) |
