# Feature: VBD Rankings (Page 2)

File: `pages/2_VBD_Rankings.py`

---

## Purpose

Primary pre-draft research view. Shows every player ranked by VBD surplus with auto-detected
tier dividers, inline notes, custom rank overrides, and CSV export.

---

## Board Layout

### Columns (left → right)

| Column | Source field | Notes |
|--------|-------------|-------|
| Tier | `tier` | Auto-detected (1 = best); tier break shown as colored divider |
| Rank | `overall_rank` or `custom_rank` | User-overridable |
| Name | `name` | Color-coded by position |
| Pos | `position` | QB=red, RB=teal, WR=blue, TE=green |
| Team | `team` | NFL team abbreviation |
| Proj Pts | `projected_pts` | Full-season projection |
| VBD Surplus | `vbd_surplus` | Core sort key; replacement = 0.0 |
| ADP | `adp_overall` | Consensus ADP; "—" if undrafted (≥999) |
| ADP Gap | `adp_gap` | Green if +5 or more (undervalued), red if −5 or less |
| Target% | `target_share` | nfl_data_py metric; blank if not fetched |
| Snap% | `snap_pct` | nfl_data_py metric |
| Carry% | `carry_share` | nfl_data_py metric |
| Grade | `schedule_grade` | A/B/C/D for playoff weeks 15-17 |
| Flag | `flag_summary` | 🟢 SLEEPER / 🔴 BUST? / 🤝 HC |
| Notes | `player_notes.notes` | Per-league; click to edit inline |

### Tier Dividers

A horizontal colored bar appears between rows where `tier` changes. Tier numbers
auto-detected by `_assign_tiers()` — gaps in VBD surplus greater than `std × 0.5`
become tier breaks. Up to 8 tiers. Tier 1 = best players.

Manual adjustment: type a new rank number in the Rank field to drag a player up/down.
Custom ranks sort before auto ranks (sort key = `custom_rank if set, else overall_rank + 1000`).

---

## Filters and Controls

- **Position filter** (multiselect): QB / RB / WR / TE — default all selected
- **Sort column** (selectbox): any column; default VBD Surplus descending
- **Name search** (text input): substring match, case-insensitive
- **Recalc VBD button (↺)**: re-runs `compute_vbd` from current cached data + config without re-fetching

---

## Notes

Notes are stored per-player per-league in `player_notes` SQLite table.

- Click the notes cell (or edit icon) to open inline text area
- Save writes immediately via `upsert_player_notes(player_id, league_id, notes, custom_rank)`
- Notes **do not transfer** between leagues (league_id partitioned)
- `custom_rank` from the same table; None means "use VBD rank"

---

## CSV Export

"Export CSV" button → downloads current filtered/sorted board as:
`data/exports/rankings_{league_id}_{date}.csv`

Contains all columns including notes and flags — usable as cheat sheet during draft.

---

## VBD Recalculation Flow

Clicking ↺ Recalc:
1. `get_all_players(positions=["QB","RB","WR","TE"])` from SQLite
2. `get_projections(season, week=0)` from SQLite
3. `get_adp(season)` from SQLite
4. `get_all_player_notes(league_id)` from SQLite
5. `compute_vbd(players, projs, adp, config, notes)` → DataFrame
6. `vbd_to_db_rows(df, league_id, season, scoring_type)` → List[dict]
7. `upsert_vbd_scores(rows)` → writes to SQLite
8. `st.cache_data.clear()` + `st.rerun()`

---

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `src/data/cache.py` | `get_vbd_scores`, `get_all_players`, `get_projections`, `get_adp`, `get_all_player_notes`, `upsert_vbd_scores`, `upsert_player_notes` |
| `src/analytics/vbd.py` | `compute_vbd`, `vbd_to_db_rows` |
| `src/data/pipeline.py` | `SEASON` constant |

---

## Common Issues

| Symptom | Fix |
|---------|-----|
| Empty board | Run `prefetch.py --full` then click ↺ Recalc |
| QBs at top | VBD working correctly; QBs shouldn't lead unless half PPR with low QB count — check league settings |
| ADP Gap all zero | ADP not fetched; run `prefetch.py --quick` |
| Target%/Snap% empty | nfl_data_py metrics require `prefetch.py --full` (not `--quick`) |
| Notes not saving | Check that `data/cache/fantasy.db` is writable |
