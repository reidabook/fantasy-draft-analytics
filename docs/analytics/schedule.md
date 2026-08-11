# Analytics: Schedule Grades

File: `src/analytics/schedule.py`

---

## Purpose

Computes a playoff schedule strength grade (A/B/C/D) for each player based on
their NFL team's opponents in weeks 15, 16, and 17. Used as a tiebreaker signal
in VBD rankings and the Sleeper Radar.

---

## Defense Tier Definitions

```python
DEFENSE_TIERS = {
    "A": {"SF", "BAL", "DAL", "BUF", "PHI"},         # Elite defenses — hard matchup
    "B": {"MIA", "CIN", "MIN", "PIT", "KC"},
    "C": {"LAR", "SEA", "DEN", "CLE", "GB"},
    "D": {"TEN", "HOU", "IND", "JAX", "ARI", "NYG", "CAR", "NE"},  # Weak defenses — easy matchup
}
```

These represent the **opponent's defense quality**. A player facing a "D" tier
defense has the **easiest** matchup (favorable for fantasy points).

**⚠️ Grade direction is counterintuitive:**

| Defense Tier | `tier_value` | Meaning for opponent |
|--------------|-------------|---------------------|
| A (elite def) | 4 | Hardest matchup for skill players |
| B | 3 | Tough |
| C | 2 | Average |
| D (weak def) | 1 | Easiest matchup — best for fantasy |

Unknown teams (e.g., new team abbreviation): default to `"C"` (neutral, tier_value=2).

---

## Grade Assignment (`grade_from_opponents`)

```python
tier_values = {"A": 4, "B": 3, "C": 2, "D": 1, "N/A": 2}

def grade_from_opponents(opponent_teams):
    values = [tier_values.get(_TEAM_TO_TIER.get(opp, "C"), 2) for opp in opponent_teams]
    avg = sum(values) / len(values)

    if avg >= 3.5:  return "D"   # all tough opponents → bad for player
    if avg >= 2.5:  return "C"
    if avg >= 1.5:  return "B"
    return "A"                   # all weak opponents → best for player
```

**Output grade "A" = BEST schedule** (weakest opponents, easiest for fantasy scoring).
**Output grade "D" = WORST schedule** (toughest opponents).

This is the inverse of what "A" means in `DEFENSE_TIERS`. Read carefully:
- `DEFENSE_TIERS["A"]` = elite defenses (hard for the player to score against)
- `schedule_grade = "A"` = player faces weak defenses (easy to score)

---

## Main Function

### `compute_schedule_grades(players, schedules_df, season, playoff_weeks=[15, 16, 17]) → List[dict]`

| Argument | Type | Notes |
|----------|------|-------|
| `players` | DataFrame | All players with `team` column |
| `schedules_df` | DataFrame\|None | From `nfldata_import_schedules()` |
| `season` | int | e.g., 2025 |
| `playoff_weeks` | list | Defaults to [15, 16, 17] |

### Algorithm

```python
# 1. Build team → week → opponent lookup from schedules_df
#    Each row in schedules_df: home_team, away_team, week, season
team_schedule = {team: {week: opponent} for ...}

# 2. For each player's NFL team, look up weeks 15/16/17 opponents
opponents = [team_schedule[player.team][w] for w in playoff_weeks]

# 3. Compute grade
grade = grade_from_opponents(opponents)

# 4. Build row for DB
{
    "player_id": player.id,
    "season": season,
    "playoff_week_15_opp": opponents[0],
    "playoff_week_16_opp": opponents[1],
    "playoff_week_17_opp": opponents[2],
    "schedule_grade": grade,
}
```

### Fallback Behavior

If `schedules_df` is None or empty:
```python
# All players assigned "C" (neutral/unknown)
grade = "C"
opponents = ["N/A", "N/A", "N/A"]
```

This ensures `schedule_grade` is always populated in `vbd_scores`, preventing
NULL errors in the display layer even when `--full` has not been run.

---

## Output

`compute_schedule_grades()` returns `List[dict]` → passed to `upsert_schedule_grades()`.

Stored in `schedule_grades` table:

| Column | Example |
|--------|---------|
| `player_id` | "4046" |
| `season` | 2025 |
| `playoff_week_15_opp` | "DAL" |
| `playoff_week_16_opp` | "NYG" |
| `playoff_week_17_opp` | "PHI" |
| `schedule_grade` | "B" |

---

## Usage in Pages

### VBD Rankings (`2_VBD_Rankings.py`)
Column: `Grade` — shows A/B/C/D; A = green (best), D = red (worst).

### Sleeper Radar (`5_Sleeper_Radar.py`)
- Sleeper candidates: `schedule_grade in {"A", "B"}` → adds bullet "Playoff schedule grade: {X} (favorable matchups in Wks 15–17)"
- Bust Watch: `schedule_grade in {"C", "D"}` → adds bullet "Playoff schedule grade: {X} (tough matchups in Wks 15–17)"

### Player Research (`3_Player_Research.py`)
`schedule_grade` normalized 0–1 for radar chart (A=1.0, B=0.75, C=0.5, D=0.0).

---

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| All players show grade "C" | Schedules not fetched (only `--quick` run) | Run `prefetch.py --full` |
| Player team not in schedule | Team abbreviation mismatch between sources | Check `_TEAM_TO_TIER` dict; add mapping if needed |
| Grade seems wrong | `DEFENSE_TIERS` stale (teams improve/decline) | Update `DEFENSE_TIERS` dict at start of season |
| Week 17 opponent shows "N/A" | NFL schedule not yet released for that week | Expected pre-season; refresh after schedule release |
