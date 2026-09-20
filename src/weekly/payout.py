"""
Weekly median-score target + high-score payout winner.
Pure functions over a {team_name: score} dict — no network/ESPN dependency,
so these are unit-testable in isolation (see tests/test_weekly_payout.py).
"""
from __future__ import annotations

import statistics
from typing import Dict, Tuple


def real_team_scores(scores: Dict[str, float], fake_team_name: str) -> Dict[str, float]:
    """All scores except the fake team's. Raises if the fake team isn't present."""
    if fake_team_name not in scores:
        raise ValueError(
            f"Fake team {fake_team_name!r} not found among this week's teams: "
            f"{sorted(scores)} — check FAKE_TEAM_NAME against the league's actual team name."
        )
    return {name: score for name, score in scores.items() if name != fake_team_name}


def compute_median(scores: Dict[str, float], fake_team_name: str) -> float:
    """Median score across all real teams (fake team excluded)."""
    real = real_team_scores(scores, fake_team_name)
    if len(real) % 2 == 0:
        raise ValueError(
            f"Expected an odd number of real teams (one plays the fake team each week), "
            f"got {len(real)}: {sorted(real)} — median target assumption may be wrong."
        )
    return statistics.median(real.values())


def find_high_scorer(scores: Dict[str, float], fake_team_name: str) -> Tuple[str, float]:
    """(team_name, score) of the week's highest-scoring real team — the payout winner."""
    real = real_team_scores(scores, fake_team_name)
    winner = max(real, key=real.get)
    return winner, real[winner]
