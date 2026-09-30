"""
Pull everything the league site needs out of ESPN into one plain,
JSON-serializable dict. This is the only module in src/site that touches the
network — awards.py / render.py work off the dict it returns, so they're
testable (and re-renderable) without ESPN.

Teams are keyed by ESPN team_id (as a string, for JSON) rather than name,
since team names get renamed week to week.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from src.data.fetcher import espn_get_team_managers

_NON_STARTER_SLOTS = {"BE", "IR"}
_HEALTHY = {None, "", "ACTIVE", "NORMAL"}


def _player(p) -> dict:
    status = getattr(p, "injuryStatus", None)
    return {
        "name": p.name, "pos": p.position, "slot": p.slot_position,
        "pts": round(p.points or 0.0, 2), "proj": round(p.projected_points or 0.0, 2),
        "injury": None if status in _HEALTHY else status,
    }


def _side(team, score: float, projected: Optional[float], lineup: list) -> dict:
    starters = [_player(p) for p in lineup if p.slot_position not in _NON_STARTER_SLOTS]
    bench = [_player(p) for p in lineup if p.slot_position == "BE"]
    ir = [_player(p) for p in lineup if p.slot_position == "IR"]
    starters.sort(key=lambda p: p["pts"], reverse=True)
    bench.sort(key=lambda p: p["pts"], reverse=True)
    return {
        "team_id": str(team.team_id),
        "score": round(score or 0.0, 2),
        "projected": round(projected or 0.0, 2),
        "top_starter": starters[0] if starters else None,
        "starters": starters,
        "bench": bench,
        "ir": ir,
        "bench_pts": round(sum(p["pts"] for p in bench), 2),
    }


def _matchups(league, week: int) -> List[dict]:
    out = []
    for box in league.box_scores(week=week):
        if box.home_team is None or box.away_team is None:
            continue  # bye
        out.append({
            "home": _side(box.home_team, box.home_score, box.home_projected, box.home_lineup),
            "away": _side(box.away_team, box.away_score, box.away_projected, box.away_lineup),
        })
    return out


def collect_league_data(league, week: int, fake_team_name: str) -> dict:
    """
    `week` is the most recently completed week — the one the site recaps.
    Weeks 1..week are pulled as completed results; week+1 (if still in the
    regular season) as upcoming matchups with projections.
    """
    managers = espn_get_team_managers(league)
    fake_team_id = next(
        (str(t.team_id) for t in league.teams if t.team_name == fake_team_name), None
    )

    teams: Dict[str, dict] = {}
    for t in league.teams:
        teams[str(t.team_id)] = {
            "id": str(t.team_id),
            "name": t.team_name,
            "abbrev": t.team_abbrev,
            "manager": managers.get(t.team_name, t.team_name),
            "logo": t.logo_url or None,
            "wins": t.wins,
            "losses": t.losses,
            "ties": t.ties,
            "pf": round(t.points_for, 2),
            "pa": round(t.points_against, 2),
            "standing": t.standing,
            "streak": f"{t.streak_type[:1]}{t.streak_length}" if t.streak_type else "",
            "playoff_pct": getattr(t, "playoff_pct", None),
            "is_fake": str(t.team_id) == fake_team_id,
        }

    weeks = {str(w): _matchups(league, w) for w in range(1, week + 1)}

    next_week = week + 1
    upcoming = _matchups(league, next_week) if next_week <= league.settings.reg_season_count else []

    return {
        "league_name": league.settings.name,
        "season": league.year,
        "week": week,
        "next_week": next_week if upcoming else None,
        "reg_season_weeks": league.settings.reg_season_count,
        "playoff_teams": league.settings.playoff_team_count,
        "fake_team_id": fake_team_id,
        "generated_at": datetime.now().isoformat(timespec="minutes"),
        "teams": teams,
        "weeks": weeks,
        "upcoming": upcoming,
    }
