# Feature: Sleeper Radar (Page 5)

File: `pages/5_Sleeper_Radar.py`

---

## Purpose

Surface actionable intelligence about non-obvious players: under-the-radar sleepers,
overvalued bust risks, and handcuff targets worth rostering. Driven by the flag engine
in `src/analytics/flags.py`.

---

## Tab Layout

Three tabs: 🟢 Sleeper Candidates | 🔴 Bust Watch | 🤝 Handcuff Targets

### Data Source

Loaded via `get_vbd_scores(league_id, season, scoring_type)` — the enriched view
includes `flag_summary`, `sleeper_reasons`, `bust_reasons`, and all nfl_data_py
metric columns when a full fetch has been run.

---

## Tab 1: Sleeper Candidates

Players with positive usage trends and/or an ADP undervaluation.

**Filter logic:**
- Primary (with flags): `flag_summary` contains "SLEEPER"
- Fallback (no flags): `adp_gap > 10` (VBD ranks the player higher than consensus by 10+ picks)

Sorted: `adp_gap` descending (biggest value first).

**Evidence row per player:**
1. `sleeper_reasons` column (semicolon-separated strings from `flags.py`)
2. `target_share > 0` → "Target share: {X}%"
3. `wopr > 0.35` → "WOPR: {X:.3f} (strong air yards + target share combo)"
4. `snap_pct > 0.75` → "Snap %: {X}% (full starter workload)"
5. `adp_gap > 5` → "ADP gap: +{N} picks (VBD ranks higher than consensus)"
6. `schedule_grade` in {A, B} → "Playoff schedule grade: {X} (favorable matchups in Wks 15-17)"

If no evidence: "Identified by flag engine — run --full for detailed metrics"

---

## Tab 2: Bust Watch

Players showing regression risk: over-performed on TDs, declining usage, or overhyped ADP.

**Filter logic:**
- Primary (with flags): `flag_summary` contains "BUST"
- Fallback (no flags): `adp_gap < -10` (consensus overvalues them by 10+ picks)

Sorted: `adp_gap` ascending (biggest overvaluation first).

**Evidence row per player:**
1. `bust_reasons` column (from `flags.py`)
2. `target_share < 0.12` → "Low target share: {X}% (below viable WR/TE threshold)"
3. `snap_pct < 0.60` → "Snap %: {X}% (part-time role)"
4. `adp_gap < -5` → "ADP gap: {N} picks (VBD ranks significantly lower than consensus)"
5. `schedule_grade` in {C, D} → "Playoff schedule grade: {X} (tough matchups in Wks 15-17)"

---

## Tab 3: Handcuff Targets

Backup RBs worth rostering based on starter injury risk and workload opportunity.

**Filter logic:**
- Primary (with flags): `flag_summary` contains "HANDCUFF"
- Fallback (no flags): RBs with `adp_overall > config.teams × 7` (rounds 7+)

Sorted: `adp_overall` ascending (earliest-available handcuffs first).

**Evidence row per player:**
1. `carry_share > 0.10` → "Carry share: {X}% (meaningful committee role)"
2. `snap_pct > 0.30` → "Snap %: {X}% (on-field presence, ready to step up)"
3. `adp_overall > config.teams × 10` → "ADP #{N} — late-round value, low cost to roster"
4. `vbd_surplus > 0` → "VBD surplus {X} — standalone value if starter goes down"
5. Otherwise: "Roster for insurance — minimal standalone value but crucial if starter injured"

---

## Player Header Format

Each player renders a header row with:
- Name (color-coded by position: QB=#FF6B6B, RB=#4ECDC4, WR=#45B7D1, TE=#96CEB4)
- "POS · TEAM" in gray
- "VBD {X} · ADP #{N}" or "ADP undrafted"

Below the header: unordered list of evidence bullets in gray.
Horizontal rule between players.

---

## Position Filter

Multiselect at top (default: all 4 positions). Filters `df` before tab rendering.

---

## Fallback Behavior

When `flag_summary` column is absent (nfl_data_py metrics not fetched), the page
falls back to pure ADP-gap logic:
- Sleepers: adp_gap > 10
- Busts: adp_gap < -10
- Handcuffs: RBs with late ADP

This means the page is **usable after just `prefetch.py --quick`**, but evidence
quality is much lower. The footer note explains this and prompts `--full`.

---

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `src/data/cache.py` | `get_vbd_scores` |
| `src/data/pipeline.py` | `SEASON` constant |
| `src/analytics/flags.py` | Source of `flag_summary`, `sleeper_reasons`, `bust_reasons` columns (computed during VBD recalc, stored in `vbd_scores`) |

---

## How Flags Get Into vbd_scores

Flags are **not** computed at page load time. They are computed during VBD recalculation:
1. `prefetch.py --full` fetches nfl_data_py metrics → stored in `advanced_metrics` table
2. `compute_vbd()` or inline recalc calls `flag_players(vbd_df, metrics_df, prior_metrics_df)`
3. `flags.py` adds `is_sleeper`, `is_bust`, `is_handcuff`, `sleeper_reasons`, `bust_reasons`, `flag_summary` columns to the DataFrame
4. `vbd_to_db_rows()` includes these columns in the rows written to `vbd_scores`
5. `get_vbd_scores()` returns them → Sleeper Radar reads them

If `prefetch.py --quick` (not `--full`) was used: `advanced_metrics` table is empty →
flags are absent → page falls back to ADP gap logic.

---

## Common Issues

| Symptom | Fix |
|---------|-----|
| All three tabs empty | Run `prefetch.py --full` then ↺ Recalc on VBD Rankings |
| No sleepers/busts found (only fallback message) | Flags missing — `flag_summary` not in data. Run `--full` |
| Handcuffs list includes starters | `depth_chart_pos` stale or not populated; run `--full` |
| Evidence rows all show generic message | Flags computed but reasons empty — may be a prior-year metrics gap |
