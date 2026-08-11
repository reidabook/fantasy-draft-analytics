# Analytics: Flag Engine

File: `src/analytics/flags.py`

---

## Purpose

Identifies sleeper candidates, bust risks, and handcuff targets by analyzing
nfl_data_py metrics against ADP. Runs after VBD computation when `--full` metrics
are available. Adds flag columns to the player DataFrame.

---

## Main Function

### `flag_players(vbd_df, metrics_df, prior_metrics_df=None, adp_cutoff_rank=100) → DataFrame`

| Argument | Type | Notes |
|----------|------|-------|
| `vbd_df` | DataFrame | Output of `compute_vbd()` |
| `metrics_df` | DataFrame | Current-year rows from `advanced_metrics` (season=2024) |
| `prior_metrics_df` | DataFrame\|None | Prior-year rows from `advanced_metrics` (season=2023) |
| `adp_cutoff_rank` | int | Default 100 — separates "early ADP" from "late ADP" |

Returns `vbd_df` with flag columns added. If `metrics_df` is None or empty, returns
`vbd_df` unchanged (page falls back to ADP-gap logic).

---

## Join Logic

```python
# Merge current metrics onto VBD by player ID
merged = vbd_df.merge(
    metrics_df,
    left_on="id",           # vbd_df uses "id" column
    right_on="player_id",   # metrics_df uses "player_id" column
    how="left"
)

# If prior year exists, join and rename to prev_* columns
merged = merged.merge(
    prior_metrics_df,
    on="player_id",
    suffixes=("", "_prior"),
    how="left"
)
# Rename _prior columns → prev_target_share, prev_carry_share, prev_snap_pct
```

Players without advanced metrics (did not appear in nfl_data_py) still appear
in output — all flag columns will be False / empty strings for them.

---

## Sleeper Signals

A player is flagged `is_sleeper = True` if **any** of these conditions are met:

| Signal | Condition | Reason string |
|--------|-----------|---------------|
| Target share growth | `target_share - prev_target_share > 0.03` | "Target share +{delta:.1%} YoY" |
| Elite air yards combo | `wopr > 0.4` AND `position in (WR, TE)` | "WOPR {wopr:.3f} — elite opportunity" |
| Hidden starter | `snap_pct > 0.75` AND `adp_overall > adp_cutoff_rank` | "Snap {snap:.0%} but ADP #{adp} — undervalued" |
| Carry share growth | `carry_share - prev_carry_share > 0.05` AND `position == RB` | "Carry share +{delta:.1%} YoY (RB breakout)" |

`sleeper_reasons` is a semicolon-separated string of all triggered reasons.
`is_sleeper = len(sleeper_reasons) >= 1`

---

## Bust Signals

A player is flagged `is_bust = True` if **any** of these conditions are met:

| Signal | Condition | Reason string |
|--------|-----------|---------------|
| TD regression | `td_luck > 0.05` | "TD over-performer (luck: +{td_luck:.3f}) — regression risk" |
| Declining usage | `target_share - prev_target_share < -0.03` AND `adp_overall < adp_cutoff_rank` | "Target share -{delta:.1%} despite high ADP" |
| Part-time role | `snap_pct < 0.60` AND `adp_overall < adp_cutoff_rank` | "Snap {snap:.0%} — not a full-time starter" |
| Depth chart concern | `"backup" in depth_chart_pos` AND `adp_overall < adp_cutoff_rank` | "Listed as backup but ADP #{adp} implies starter" |

`bust_reasons` is a semicolon-separated string of all triggered reasons.
`is_bust = len(bust_reasons) >= 1`

---

## Handcuff Signal

```python
is_handcuff = (
    position == "RB"
    AND "backup" in str(depth_chart_pos).lower()
)
```

No ADP condition — all backup RBs are potential handcuffs regardless of draft
position. `adp_cutoff_rank` does not apply here.

---

## TD Luck Formula

```python
def compute_td_luck(metrics_current, metrics_prior=None):
    tds = metrics_current.get("rush_td", 0) + metrics_current.get("rec_td", 0)
    targets = metrics_current.get("targets", 1)       # avoid /0; 1 = no targets
    rz_target_share = metrics_current.get("rz_target_share", 0)

    actual_td_rate = tds / targets
    expected_td_rate = rz_target_share * 0.25
    return round(actual_td_rate - expected_td_rate, 3)
```

Positive TD luck → player over-performed on touchdowns relative to red zone opportunity.
A value > 0.05 is the bust threshold (regression likely next season).

The result is stored in `advanced_metrics.td_luck` via `upsert_advanced_metrics()`.

---

## Flag Summary Column

```python
flags = []
if row["is_sleeper"]:   flags.append("SLEEPER")
if row["is_bust"]:      flags.append("BUST?")
if row["is_handcuff"]:  flags.append("HC")

row["flag_summary"] = ", ".join(flags)
# Examples: "SLEEPER", "BUST?", "HC", "SLEEPER, HC", ""
```

---

## Output Columns Added

| Column | Type | Example |
|--------|------|---------|
| `is_sleeper` | bool | True |
| `is_bust` | bool | False |
| `is_handcuff` | bool | True |
| `sleeper_reasons` | str | "WOPR 0.412 — elite opportunity; Snap 82% but ADP #134" |
| `bust_reasons` | str | "" |
| `flag_summary` | str | "SLEEPER, HC" |

---

## Integration with VBD Pipeline

Flags are NOT computed at page load time. The pipeline is:

1. `prefetch.py --full` → `fetch_nfl_metrics()` → `advanced_metrics` table populated
2. User clicks ↺ Recalc on VBD Rankings → `compute_vbd()` runs
3. `flag_players(vbd_df, metrics_df, prior_metrics_df)` called in the recalc flow
4. Flagged DataFrame → `vbd_to_db_rows()` (note: flag columns excluded from DB rows)
5. Pages call `get_vbd_scores()` then call `flag_players()` again at display time
   to add flag columns for filtering

If `advanced_metrics` table is empty (only `--quick` was run), `metrics_df` will be
empty and `flag_players()` returns the VBD DataFrame with no flag columns added.
Pages detect the absence of `flag_summary` and fall back to ADP-gap logic.

---

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| No flags shown | `advanced_metrics` empty | Run `prefetch.py --full` |
| `flag_summary` absent from `get_vbd_scores()` output | Flags not in DB schema | Expected — computed at display time |
| All players flagged as handcuff | `depth_chart_pos` stale/incorrect | Run `prefetch.py --full` to refresh player directory |
| Bust reasons empty despite high ADP | Prior-year metrics missing | `prior_metrics_df=None`; only current-year signals fire |
| Player flagged as both SLEEPER and HC | RB with breakout carry trend who is backup | Correct behavior — handcuff with upside |
