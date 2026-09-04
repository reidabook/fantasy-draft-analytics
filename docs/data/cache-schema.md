# Data: Cache Schema (SQLite)

File: `src/data/cache.py`

---

## Overview

All persistent data lives in a single SQLite database. The module auto-initializes
all tables on import — no manual schema migration needed.

```python
DB_PATH       = .../data/cache/fantasy.db
MANIFEST_PATH = .../data/cache/.cache_manifest.json
```

`init_db()` is called at module-level so any `import cache` creates the schema.

---

## Connection Pattern

```python
with get_conn() as conn:
    conn.row_factory = sqlite3.Row   # dict-like row access
    # auto-commit on success, auto-rollback on exception
```

---

## Tables

### `players`

Primary source of truth for all NFL player metadata.

| Column | Type | Notes |
|--------|------|-------|
| id | TEXT PK | Sleeper player_id |
| name | TEXT | Display name |
| position | TEXT | QB / RB / WR / TE / K / DEF |
| team | TEXT | NFL team abbreviation |
| age | INTEGER | |
| depth_chart_pos | TEXT | "starter" / "backup" / NULL |
| injury_status | TEXT | Sleeper injury field |
| gsis_id | TEXT | For nfl_data_py join |
| sleeper_id | TEXT | Same as id; kept for clarity |
| espn_id | TEXT | For ESPN join |
| updated_at | TEXT | ISO timestamp |

**PK:** `id`

### `projections`

Full-season and weekly projected fantasy points per player per source.

| Column | Type | Notes |
|--------|------|-------|
| player_id | TEXT | FK → players.id |
| season | INTEGER | e.g., 2025 |
| week | INTEGER | 0 = full-season |
| source | TEXT | "sleeper" / "fantasypros" |
| pts_ppr | REAL | |
| pts_half_ppr | REAL | |
| pts_std | REAL | |
| rush_yd | REAL | |
| rec_yd | REAL | |
| pass_yd | REAL | |
| rush_td | REAL | |
| rec_td | REAL | |
| pass_td | REAL | |
| targets | REAL | |
| receptions | REAL | |
| carries | REAL | |
| updated_at | TEXT | |

**PK:** `(player_id, season, week, source)`

### `advanced_metrics`

nfl_data_py seasonal metrics. Populated only by `prefetch.py --full`.

| Column | Type | Notes |
|--------|------|-------|
| player_id | TEXT | FK → players.id (via gsis_id → Sleeper ID mapping) |
| season | INTEGER | |
| snap_pct | REAL | 0.0–1.0 |
| target_share | REAL | 0.0–1.0 |
| air_yards_share | REAL | |
| wopr | REAL | Weighted opportunity rating |
| carry_share | REAL | 0.0–1.0 |
| rz_target_share | REAL | Red zone target share |
| epa_per_play | REAL | |
| td_luck | REAL | Computed by flags.py; stored here |
| updated_at | TEXT | |

**PK:** `(player_id, season)`

Empty until `fetch_nfl_metrics()` runs. Absence of rows = `--quick` only mode.

### `adp`

Consensus ADP from FantasyPros (primary) or Sleeper projection ordering (fallback).

| Column | Type | Notes |
|--------|------|-------|
| player_id | TEXT | |
| season | INTEGER | |
| source | TEXT | "fantasypros" / "sleeper_proxy" |
| adp_overall | REAL | Overall pick position |
| adp_ppr | REAL | |
| adp_half_ppr | REAL | |
| adp_std | REAL | |
| updated_at | TEXT | |

**PK:** `(player_id, season, source)`

`vbd.py` takes `min(adp_overall)` across sources for each player (best ADP).
Unranked players get `adp_overall = 999.0`.

### `vbd_scores`

Per-player, per-league VBD computation results.

| Column | Type | Notes |
|--------|------|-------|
| player_id | TEXT | |
| league_id | TEXT | Partitions data per league |
| season | INTEGER | |
| scoring_type | TEXT | "ppr" / "half_ppr" / "standard" |
| projected_pts | REAL | Best projection across sources |
| replacement_pts | REAL | Threshold player's pts |
| vbd_surplus | REAL | clip(projected - replacement, 0) |
| position_rank | INTEGER | Rank within position |
| overall_rank | INTEGER | Rank across all positions |
| adp_gap | REAL | adp_overall - overall_rank |
| tier | INTEGER | 1–8, auto-detected |
| updated_at | TEXT | |

**PK:** `(player_id, league_id, season, scoring_type)`

**Flag columns are NOT stored here.** `flag_summary`, `sleeper_reasons`, `bust_reasons`
are computed at runtime by `flags.py` and never written to the database.

### `draft_picks`

All picks during a draft session. Persists across page refreshes.

| Column | Type | Notes |
|--------|------|-------|
| id | INTEGER AUTOINCREMENT PK | |
| league_id | TEXT | |
| season | INTEGER | |
| pick_number | INTEGER | 1-based overall pick |
| round | INTEGER | |
| pick_in_round | INTEGER | |
| player_id | TEXT | |
| team_number | INTEGER | Which team drafted (snake math) |
| is_my_pick | INTEGER | 0 or 1 (DEFAULT 0) |
| drafted_at | TEXT | ISO timestamp |

**UNIQUE:** `(league_id, season, pick_number)` — prevents duplicate picks.

`undo_last_pick()` deletes the row with max `pick_number` for the league/season.

### `historical_stats`

Per-player per-season actuals (prior years).

| Column | Type | Notes |
|--------|------|-------|
| player_id | TEXT | |
| season | INTEGER | |
| games | INTEGER | |
| pts_ppr_per_game | REAL | |
| targets | INTEGER | |
| carries | INTEGER | |
| updated_at | TEXT | |

**PK:** `(player_id, season)`

### `player_notes`

User-written per-player notes and custom ranks. **Per-league** — notes don't
bleed across leagues.

| Column | Type | Notes |
|--------|------|-------|
| player_id | TEXT | |
| league_id | TEXT | |
| notes | TEXT | Free text |
| custom_rank | INTEGER | NULL = use VBD rank |
| updated_at | TEXT | |

**PK:** `(player_id, league_id)`

`get_all_player_notes(league_id)` returns `{player_id: {"notes": ..., "custom_rank": ...}}`
for O(1) lookup during VBD computation.

### `schedule_grades`

Playoff schedule strength grades (weeks 15–17). Computed by `schedule.py`.

| Column | Type | Notes |
|--------|------|-------|
| player_id | TEXT | |
| season | INTEGER | |
| playoff_week_15_opp | TEXT | Opponent team abbreviation |
| playoff_week_16_opp | TEXT | |
| playoff_week_17_opp | TEXT | |
| schedule_grade | TEXT | A / B / C / D |
| updated_at | TEXT | |

**PK:** `(player_id, season)`

---

## Cache Manifest

`data/cache/.cache_manifest.json` — JSON dict of `{source_key: iso_timestamp}`.

| Source key | TTL | Updated by |
|------------|-----|-----------|
| `sleeper_players` | 24h | `fetch_players()` |
| `sleeper_projections` | 24h | `fetch_projections()` |
| `adp` | 24h | `fetch_adp()` |
| `nfl_metrics` | 168h | `fetch_nfl_metrics()` |

### Freshness API

```python
is_stale(source_key, max_age_hours) → bool
    # True if never fetched OR (now - last_fetched) > max_age_hours

freshness_label(source_key) → str
    # "fresh"  — fetched < 24h ago
    # "stale"  — fetched 1–7 days ago
    # "old"    — fetched >= 7 days ago
    # "never"  — never fetched

mark_fetched(source_key)
    # writes UTC ISO timestamp to manifest
```

Shown in the sidebar as colored indicator: green (fresh) / yellow (stale) / red (old/never).

---

## Key Read Helpers

### `get_vbd_scores(league_id, season, scoring_type)`

```sql
SELECT vs.*, p.name, p.position, p.team, p.age, p.injury_status, p.depth_chart_pos
FROM vbd_scores vs
JOIN players p ON vs.player_id = p.id
WHERE vs.league_id = ? AND vs.season = ? AND vs.scoring_type = ?
ORDER BY vs.vbd_surplus DESC
```

Returns enriched rows with all player metadata. Flag columns are absent unless
added downstream by `flags.py`.

### `get_drafted_player_ids(league_id, season)`

Returns `set[str]` of player_ids already drafted. Used by draft board to filter
available pool.

### `get_all_player_notes(league_id)`

Returns `{player_id: {"notes": str, "custom_rank": int|None}}`. Called at VBD
compute time to merge custom ranks into the sort key.

---

## Write Helpers (all use INSERT OR REPLACE)

| Function | Table |
|----------|-------|
| `upsert_players(rows)` | players |
| `upsert_projections(rows)` | projections |
| `upsert_advanced_metrics(rows)` | advanced_metrics |
| `upsert_adp(rows)` | adp |
| `upsert_vbd_scores(rows)` | vbd_scores |
| `upsert_draft_pick(pick_dict)` | draft_picks |
| `upsert_player_notes(player_id, league_id, notes, custom_rank)` | player_notes |
| `upsert_schedule_grades(rows)` | schedule_grades |
| `undo_last_pick(league_id, season)` | draft_picks (DELETE) |
