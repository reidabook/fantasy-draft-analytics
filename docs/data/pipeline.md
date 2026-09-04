# Data: Pipeline Orchestration

File: `src/data/pipeline.py`

---

## Purpose

Coordinates all fetch → transform → cache flows. Called by `prefetch.py` CLI and
referenced directly by page-level recalc buttons. Single definition point for `SEASON`.

---

## Constants

```python
SEASON = 2025   # Change here to update all downstream fetches
```

---

## Two Run Modes

### `run_quick(log_cb=None)`

Minimum viable daily refresh. Fetches only what changes frequently.

| Step | Function | TTL |
|------|----------|-----|
| Projections | `fetch_projections()` | 24h |
| ADP | `fetch_adp()` | 24h |

Skips player directory and nfl_data_py metrics. Safe to run daily.

### `run_full(log_cb=None)`

Complete weekly refresh. Fetches everything including heavyweight nfl_data_py metrics.

| Step | Function | TTL |
|------|----------|-----|
| Players | `fetch_players()` | 24h |
| Projections | `fetch_projections()` | 24h |
| ADP | `fetch_adp()` | 24h |
| NFL metrics | `fetch_nfl_metrics()` | 168h (weekly) |

Required before `flags.py` can produce sleeper/bust signals. Without this, pages fall back
to ADP-gap-only logic.

---

## Individual Fetch Functions

### `fetch_players(log=None)`

```
sleeper_get_all_players()
  → normalize_sleeper_players()
  → upsert_players()
  → mark_fetched("sleeper_players")
```

Checks `is_stale("sleeper_players", 24)` before fetching. Logs player count on success.
Deliberately 24h rather than the 168h "weekly" cadence of the other `--full` sources —
this carries team/roster-status/injury designation, which moves daily in-season
(especially around roster cutdowns).

### `fetch_projections(log=None)`

```
sleeper_get_projections(season=SEASON, week=0)
  → normalize_sleeper_projections()
  → upsert_projections()
  → mark_fetched("sleeper_projections")
```

`week=0` = full-season projections. Checks `is_stale("sleeper_projections", 24)`.

### `fetch_adp(log=None)`

```
try: fantasypros_get_adp()
except/empty: normalize_sleeper_adp_from_projections()  # fallback

→ upsert_adp()
→ mark_fetched("adp")
```

Checks `is_stale("adp", 24)`. FantasyPros scraping is fragile — fallback silently
uses Sleeper projection ordering as proxy ADP when FantasyPros fails. When it's
blocked, `import_fantasypros_local()` (below) is the manual alternative.

### `fetch_nfl_metrics(log=None)`

```
nfldata_import_ids()
  → build_id_map()  # maps Sleeper player_id → gsis_id

for season in [2023, 2024]:
    nfldata_import_seasonal([season])
      → normalize_seasonal_metrics(df, id_map, season)
      → upsert_advanced_metrics(rows)

mark_fetched("nfl_metrics")
```

Checks `is_stale("nfl_metrics", 168)`. Fetches 2 seasons to enable YoY delta calculations
in `flags.py` (prior-year = 2023, current-year = 2024).

**DO NOT use** `import_pbp_data` — that's 500MB. `import_seasonal_data` is ~10MB total.

---

### `import_fantasypros_local(stats_csv_path, bye_csv_path=None, log_cb=None)`

Ingests a manually-downloaded FantasyPros "Draft ALL Rankings" CSV export — the
same one `fetch_adp()` would scrape live, for when that scrape is blocked. Called
by `prefetch.py --local-csv PATH [--local-bye-csv PATH]`.

```
fantasypros_parse_local_csv(stats_csv_path)       # stat-line variant: RK, TIERS,
                                                     PLAYER NAME, TEAM, FANTASYPTS, ...
  → normalize_fantasypros_local(raw, name_to_id, season)
  → (proj_rows, adp_rows)
  → upsert_projections(proj_rows) / upsert_adp(adp_rows)   # source="fantasypros_local"

if bye_csv_path:
  fantasypros_parse_local_bye_weeks_csv(bye_csv_path)   # cheat-sheet variant: RK, TIERS,
                                                           PLAYER NAME, TEAM, POS, BYE WEEK, ...
    → normalize_fantasypros_bye_weeks(raw, name_to_id)
    → upsert_bye_weeks(bye_weeks)
```

Requires the player directory already cached (`fetch_players()` / `--full` first) —
matching is by lowercased name (+ suffix-stripping + fuzzy fallback) against
`cache.get_all_players()`. Team-defense/kicker rows in the CSV don't match a
named player and are logged as unmatched/skipped — expected, not an error.

---

## League Import Functions

### `import_sleeper_league(username, log_cb=None)`

Called by `pages/1_League_Import.py` on form submit.

```
sleeper_get_user(username)           → user_id
sleeper_get_leagues(user_id, SEASON) → list of league dicts

for each league:
    sleeper_get_league_drafts(league_id) → drafts[0].draft_order, draft_id
      # draft_order: {user_id: pick_slot}, or null if Sleeper hasn't
      # randomized the draft yet — falls back to the previously-saved
      # my_pick_position/draft_id (default 6/"" if none saved)

    build_league_config_from_sleeper(league_dict, user_settings={my_pick_position, draft_id})
      → LeagueConfig
      → save_config(config, path="config/sleeper_{league_id}.json")

returns List[LeagueConfig]
```

No credentials required — Sleeper username only.

### `import_espn_league(log_cb=None)`

Called by `pages/1_League_Import.py` on form submit.

```
reads os.getenv("ESPN_LEAGUE_ID")
reads os.getenv("ESPN_S2")
reads os.getenv("ESPN_SWID")

espn_get_league(league_id, year=SEASON, espn_s2, swid)
  → build_league_config_from_espn(espn_league)
  → save_config(config, path="config/espn_{league_id}.json")
```

ESPN cookies expire. Re-extract from browser DevTools → Application → Cookies → espn.com.
Credentials are never written to disk from this function — only passed via env vars.

---

## Logging Pattern

```python
def log(msg, callback=None):
    if callback:
        callback(msg)
    else:
        print(msg)
```

All fetch functions accept a `log_cb` callable. Pages pass `logs.append` to capture
messages for display in the Streamlit UI. CLI (`prefetch.py`) passes `None` → stdout.

---

## Error Handling

Each step in `run_quick` and `run_full` is wrapped in `try/except Exception`:
- Failure in one step does not abort subsequent steps
- Error message logged via `log()`
- Stale TTL check is bypassed on explicit `--force` flag from CLI (not yet implemented)

---

## Dependencies

| Import | Source |
|--------|--------|
| `fetcher.py` | All `sleeper_*`, `espn_*`, `fantasypros_*`, `nfldata_*` functions |
| `transformer.py` | `normalize_*`, `build_id_map` |
| `cache.py` | `upsert_*`, `is_stale`, `mark_fetched` |
| `settings.py` | `build_league_config_from_sleeper`, `build_league_config_from_espn`, `save_config` |
