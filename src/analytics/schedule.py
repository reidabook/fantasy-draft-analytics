"""
Playoff schedule strength of schedule (SOS) grades.
Evaluates weeks 15-17 opponents for each player's team.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

# Rough defensive strength ratings (lower = easier matchup)
# Updated preseason — adjust as season progresses
DEFENSE_TIERS = {
    "A": {"SF", "BAL", "DAL", "BUF", "PHI"},   # elite defenses
    "B": {"MIA", "CIN", "MIN", "PIT", "KC"},
    "C": {"LAR", "SEA", "DEN", "CLE", "GB"},
    "D": {"TEN", "HOU", "IND", "JAX", "ARI", "NYG", "CAR", "NE"},  # weak defenses (good matchups)
}

_TEAM_TO_TIER: Dict[str, str] = {}
for tier, teams in DEFENSE_TIERS.items():
    for t in teams:
        _TEAM_TO_TIER[t] = tier


def grade_from_opponents(opponents: List[Optional[str]]) -> str:
    """
    Given a list of playoff week opponents (teams), return an overall schedule grade.
    Grade is based on average defensive strength of opponents.
    A = best schedule (weakest defenses), D = hardest.
    """
    if not opponents or all(o is None for o in opponents):
        return "N/A"

    tier_values = {"A": 4, "B": 3, "C": 2, "D": 1, "N/A": 2}
    # Easier opponent (D tier defense) → better for the player
    opp_tiers = [_TEAM_TO_TIER.get(opp, "C") if opp else "C" for opp in opponents if opp]
    if not opp_tiers:
        return "C"

    avg = sum(tier_values.get(t, 2) for t in opp_tiers) / len(opp_tiers)

    if avg >= 3.5:
        return "D"   # hardest schedule
    elif avg >= 2.5:
        return "C"
    elif avg >= 1.5:
        return "B"
    return "A"      # easiest schedule


def compute_schedule_grades(
    players: List[dict],
    schedules_df: Optional["pd.DataFrame"],
    season: int,
    playoff_weeks: List[int] = [15, 16, 17],
) -> List[dict]:
    """
    Compute playoff schedule grade for each player.

    Args:
        players: list of player dicts (need 'id', 'team')
        schedules_df: nfl_data_py schedules DataFrame
        season: NFL season year
        playoff_weeks: which weeks to grade

    Returns:
        List of schedule_grade dicts for cache.upsert_schedule_grades()
    """
    if schedules_df is None or schedules_df.empty:
        # Return neutral grades
        return [
            {
                "player_id": p["id"],
                "season": season,
                "playoff_week_15_opp": None,
                "playoff_week_16_opp": None,
                "playoff_week_17_opp": None,
                "schedule_grade": "C",
            }
            for p in players
        ]

    # Build team → weekly opponent map
    team_opponents: Dict[str, Dict[int, str]] = {}

    for _, row in schedules_df.iterrows():
        if row.get("season") != season:
            continue
        week = int(row.get("week", 0))
        if week not in playoff_weeks:
            continue

        home_team = row.get("home_team", "")
        away_team = row.get("away_team", "")

        if home_team not in team_opponents:
            team_opponents[home_team] = {}
        team_opponents[home_team][week] = away_team

        if away_team not in team_opponents:
            team_opponents[away_team] = {}
        team_opponents[away_team][week] = home_team

    rows = []
    for p in players:
        team = p.get("team", "")
        opps = team_opponents.get(team, {})
        w15 = opps.get(15)
        w16 = opps.get(16)
        w17 = opps.get(17)
        grade = grade_from_opponents([w15, w16, w17])
        rows.append({
            "player_id": p["id"],
            "season": season,
            "playoff_week_15_opp": w15,
            "playoff_week_16_opp": w16,
            "playoff_week_17_opp": w17,
            "schedule_grade": grade,
        })
    return rows
