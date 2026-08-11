# Feature: Player Research (Page 3)

File: `pages/3_Player_Research.py`

---

## Purpose

Deep-dive player analysis. Searchable metrics table, side-by-side player comparison,
and radar chart vs positional average.

---

## Metrics Table

All players matching the current filters in one sortable table.

**Filters:**
- Name search (text input, substring, case-insensitive)
- Position multiselect (QB / RB / WR / TE)
- Team multiselect (all NFL teams)

**Columns shown:**
- Name, Position, Team, Age
- `projected_pts` (full season)
- `vbd_surplus`, `adp_overall`, `adp_gap`
- `target_share`, `snap_pct`, `wopr`, `air_yards_share` (WR/TE)
- `carry_share`, `rz_target_share` (RB)
- `epa_per_play`
- `schedule_grade`
- `flag_summary`

Cells are color-coded for at-a-glance reading:
- Green = strong signal (e.g., snap_pct ≥ 0.80)
- Yellow = moderate
- Red = weak / concerning

Data loaded via `get_vbd_scores(league_id, season, scoring_type)` (VBD enriched view)
joined to `advanced_metrics` for nfl_data_py columns.

---

## Side-by-Side Comparison

Two searchable dropdowns at the top of the page to select any two players.

Split layout shows:
- Basic info: position, team, age
- Projection: pts, VBD surplus
- ADP vs VBD rank
- All available advanced metrics
- Flag summary with reasons

Useful for close draft-day decisions (e.g., "RB12 vs WR8 — which has more upside?").

---

## Radar Chart

Select one player → radar chart showing that player's normalized metrics vs the
positional average for all players at that position.

**Axes (all normalized 0–1 within position):**
- `target_share`
- `snap_pct`
- `wopr`
- `vbd_surplus`
- `adp_gap` (positive = better)
- `schedule_grade` (A=1.0, D=0.0)

Built with `plotly.graph_objects.Scatterpolar`. Shaded fill shows where player
exceeds or trails positional average.

**Note:** If nfl_data_py metrics are missing, chart only shows VBD + ADP axes.
Run `prefetch.py --full` for complete radar.

---

## Data Sources

All data loaded from SQLite via:
- `get_vbd_scores(league_id, season, scoring_type)` — VBD + ADP + position + team
- `get_all_players(positions=[...])` — age, depth_chart_pos
- Advanced metrics joined in via `vbd_scores` table (which includes nfl_data_py columns
  when `prefetch.py --full` has been run)

`@st.cache_data(ttl=120)` used to avoid re-querying SQLite on every widget interaction.

---

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `src/data/cache.py` | `get_vbd_scores`, `get_all_players` |
| `src/data/pipeline.py` | `SEASON` constant |
| `plotly` | Radar chart rendering |

---

## Common Issues

| Symptom | Fix |
|---------|-----|
| Radar only shows 2 axes | Run `prefetch.py --full` to populate advanced_metrics |
| Player not in search | VBD not computed for this player; run ↺ Recalc on VBD Rankings page |
| "No data" after switching leagues | Different league_id; run VBD Recalc for this league |
