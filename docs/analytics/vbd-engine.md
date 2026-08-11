# Analytics: VBD Engine

File: `src/analytics/vbd.py`

---

## Purpose

Computes Value-Based Drafting scores for every player given a specific league's
scoring settings and roster configuration. Produces the sorted board that all other
features consume.

---

## Core Function

### `compute_vbd(players, projections, adp, config, notes) → DataFrame`

| Argument | Type | Source |
|----------|------|--------|
| `players` | DataFrame | `get_all_players()` |
| `projections` | DataFrame | `get_projections(season, week=0)` |
| `adp` | DataFrame | `get_adp(season)` |
| `config` | `LeagueConfig` | `load_config()` |
| `notes` | dict | `get_all_player_notes(league_id)` |

Returns a DataFrame with one row per player, sorted by `vbd_surplus` descending.

---

## Step-by-Step Algorithm

### 1. Select scoring column

```python
pts_col = {
    "ppr":      "pts_ppr",
    "half_ppr": "pts_half_ppr",
    "standard": "pts_std",
}.get(config.scoring.type, "pts_ppr")  # defaults to PPR if unknown
```

### 2. Resolve multiple projection sources

When both Sleeper and FantasyPros projections exist for the same player, take the
maximum (most optimistic projection wins):

```python
proj_best = projections.groupby("player_id")[pts_col].max().reset_index()
proj_best.columns = ["player_id", "projected_pts"]
```

### 3. Resolve multiple ADP sources

When both FantasyPros and Sleeper proxy ADP exist, take the minimum (best available
draft position):

```python
adp_best = adp.groupby("player_id")["adp_overall"].min().reset_index()
```

Unranked players are assigned `adp_overall = 999.0` (effectively undrafted).

### 4. Filter to fantasy-relevant positions

Only `QB`, `RB`, `WR`, `TE` are scored. `K` and `DST` excluded from VBD calculation.

### 5. Compute position rank

```python
df["position_rank"] = (
    df.groupby("position")["projected_pts"]
    .rank(ascending=False, method="min")
    .astype(int)
)
```

### 6. Compute replacement points

```python
def _get_replacement_pts(pos_df, threshold):
    pos_df_sorted = pos_df.sort_values("projected_pts", ascending=False)
    if len(pos_df_sorted) >= threshold:
        return pos_df_sorted.iloc[threshold - 1]["projected_pts"]
    else:
        return pos_df_sorted.iloc[-1]["projected_pts"]  # last player if pool is small
```

**Replacement thresholds** are derived from `config`:

```python
# Example: 12-team league, roster: QB=1, RB=2, WR=2, TE=1, FLEX=1
# FLEX assumed 50% RB, 50% WR
replacement_rank = {
    "QB": teams * QB_slots,                   # 12 * 1 = 12
    "RB": teams * (RB_slots + FLEX * 0.5),   # 12 * 2.5 = 30
    "WR": teams * (WR_slots + FLEX * 0.5),   # 12 * 2.5 = 30
    "TE": teams * TE_slots,                   # 12 * 1 = 12
}
```

### 7. Compute VBD surplus

```python
df["vbd_surplus"] = (df["projected_pts"] - df["replacement_pts"]).clip(lower=0)
```

Surplus is always non-negative. Players below replacement level are clamped to 0
(they are still included in the board, just ranked last among their position).

### 8. Compute overall rank

```python
df["overall_rank"] = (
    df["vbd_surplus"].rank(ascending=False, method="min").astype(int)
)
```

### 9. Compute ADP gap

```python
df["adp_gap"] = df["adp_overall"] - df["overall_rank"]
# positive = undervalued (VBD ranks higher than consensus)
# negative = overvalued (VBD ranks lower than consensus)
```

### 10. Assign tiers

```python
def _assign_tiers(df, max_tiers=8):
    sorted_surplus = df["vbd_surplus"].sort_values(ascending=False)
    threshold = sorted_surplus.std() * 0.5
    # Walk the sorted list; start new tier when gap between consecutive rows > threshold
    # Caps at max_tiers=8 total tiers
    # Tier 1 = best players
```

### 11. Apply custom ranks (from notes)

```python
df["custom_rank"] = df["player_id"].map(lambda pid: notes.get(pid, {}).get("custom_rank"))
df["sort_key"] = df.apply(
    lambda r: r["custom_rank"] if pd.notna(r["custom_rank"]) else r["overall_rank"] + 1000,
    axis=1
)
df = df.sort_values("sort_key")
```

Custom ranks float to the top. Un-overridden players sort by `overall_rank + 1000`
which places them after all custom-ranked entries.

---

## Output Columns

| Column | Type | Notes |
|--------|------|-------|
| `player_id` | str | Sleeper player ID |
| `name` | str | Display name |
| `position` | str | QB/RB/WR/TE |
| `team` | str | NFL team |
| `projected_pts` | float | Best projection across sources |
| `replacement_pts` | float | Threshold player's pts |
| `vbd_surplus` | float | ≥ 0, core sort key |
| `position_rank` | int | Rank within position |
| `overall_rank` | int | Rank across all positions |
| `adp_overall` | float | 999.0 if undrafted |
| `adp_gap` | float | Positive = value |
| `tier` | int | 1–8 |
| `custom_rank` | int\|None | From player_notes |
| `sort_key` | float | custom_rank or overall_rank+1000 |
| `notes` | str | From player_notes |
| `schedule_grade` | str | A/B/C/D (joined from schedule_grades) |

**Flag columns are NOT present** in `compute_vbd()` output. They are added separately
by `flags.py` when nfl_data_py metrics are available.

---

## `vbd_to_db_rows(df, league_id, season, scoring_type) → List[dict]`

Converts the VBD DataFrame to a list of dicts suitable for `upsert_vbd_scores()`.

Columns written to DB:
```
player_id, league_id, season, scoring_type,
projected_pts, replacement_pts, vbd_surplus,
position_rank, overall_rank, adp_gap, tier
```

Flag columns (`flag_summary`, `sleeper_reasons`, `bust_reasons`) are **not included**
here — they are computed at display time by calling `flag_players()` on the returned
DataFrame.

---

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| QBs at top of board | VBD working as intended — QB scarcity in small leagues | Verify `replacement_rank["QB"]` matches your league's team count |
| All players show VBD = 0 | Projections not fetched | Run `prefetch.py --quick` |
| ADP gap all zero | ADP not fetched | Run `prefetch.py --quick` |
| Custom rank not sticking | Notes not passed to `compute_vbd` | Verify `get_all_player_notes(league_id)` returns data |
| Board reshuffles on league switch | Expected — VBD is per-league (different scoring/teams) | Check `league_id` in sidebar |
