"""
Weekly median-score target + high-score payout winner.
Pure functions over a {team_name: score} dict — no network/ESPN dependency,
so these are unit-testable in isolation (see tests/test_weekly_payout.py).
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode


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


def find_high_scorers(scores: Dict[str, float], fake_team_name: str) -> Tuple[List[str], float]:
    """([team_name, ...], score) — every real team at the week's top score (more than one on a tie)."""
    real = real_team_scores(scores, fake_team_name)
    top = max(real.values())
    return sorted(name for name, score in real.items() if score == top), top


def venmo_pay_link(handle: str, amount: float, note: str) -> str:
    """
    Prefilled Venmo pay link — opens the app with recipient/amount/note filled
    in, still needs a tap to confirm. https rather than venmo:// since mail
    clients don't linkify custom schemes. Venmo has no public API for personal
    payments, so this is as automatic as it gets without breaking their ToS.
    """
    query = urlencode({
        "txn": "pay",
        "audience": "private",
        "recipients": handle.strip().lstrip("@"),
        "amount": f"{amount:.2f}",
        "note": note,
    })
    return f"https://venmo.com/?{query}"


def parse_venmo_handles(raw: Optional[str]) -> Dict[str, str]:
    """
    Parse VENMO_HANDLES ("Tex:Tyler-Carwell,Medvene:@Matt-Medvene") into
    {manager_label_lowercased: handle}. Keyed by manager label (see
    espn_get_team_managers), not team name — team names get renamed week to
    week, managers don't.
    """
    handles = {}
    for entry in (raw or "").split(","):
        label, sep, handle = entry.partition(":")
        if sep and label.strip() and handle.strip():
            handles[label.strip().lower()] = handle.strip().lstrip("@")
    return handles


def payout_line(
    week: int,
    reg_season_weeks: int,
    winners: List[str],
    high_score: float,
    team_to_manager: Dict[str, str],
    handles: Dict[str, str],
    amount: float,
) -> Optional[str]:
    """
    The report's high-score payout line, with a Venmo pay link when there's
    exactly one winner with a known handle. None once the regular season is
    over — the weekly payout stops at the playoffs.
    """
    if week > reg_season_weeks:
        return None
    labels = [team_to_manager.get(name, name) for name in winners]
    if len(labels) > 1:
        return f"High score payout: TIE at {high_score:.2f} between {', '.join(labels)} — no link, decide manually."
    label = labels[0]
    handle = handles.get(label.lower())
    if not handle:
        return (
            f"High score payout: {label} with {high_score:.2f} — Venmo them "
            f"(no handle configured for {label} in VENMO_HANDLES)."
        )
    link = venmo_pay_link(handle, amount, f"Week {week} high score")
    return f"High score payout: {label} with {high_score:.2f} — pay ${amount:g} to @{handle}: {link}"
