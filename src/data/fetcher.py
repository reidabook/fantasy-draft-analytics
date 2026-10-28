"""
Data fetchers: Sleeper API, ESPN API, FantasyPros ADP, nfl_data_py.
All functions return raw dicts/lists; transformer.py normalizes them.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

SLEEPER_BASE = "https://api.sleeper.app/v1"
FANTASYPROS_ADP_URL = "https://api.fantasypros.com/v2/json/nfl/2025/consensus-rankings"


def _get(url: str, params: Optional[dict] = None, retries: int = 3) -> Any:
    """GET request with simple retry logic."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


# ---------------------------------------------------------------------------
# Sleeper API
# ---------------------------------------------------------------------------

def sleeper_get_user(username: str) -> dict:
    """Resolve username → user object (includes user_id)."""
    return _get(f"{SLEEPER_BASE}/user/{username}")


def sleeper_get_leagues(user_id: str, season: int = 2025) -> List[dict]:
    """Get all NFL leagues for a user in a given season."""
    return _get(f"{SLEEPER_BASE}/user/{user_id}/leagues/nfl/{season}") or []


def sleeper_get_league(league_id: str) -> dict:
    """Get full league details including settings and scoring."""
    return _get(f"{SLEEPER_BASE}/league/{league_id}")


def sleeper_get_all_players() -> Dict[str, dict]:
    """
    Download full player directory from Sleeper.
    Returns dict keyed by sleeper player_id.
    NOTE: ~5MB JSON — refresh weekly, not daily.
    """
    return _get(f"{SLEEPER_BASE}/players/nfl") or {}


def sleeper_get_projections(season: int = 2025, week: int = 0, season_type: str = "regular") -> Dict[str, dict]:
    """
    Get full-season (week=0) or weekly projections from Sleeper.
    Returns dict keyed by sleeper player_id.
    Sleeper's API requires the season_type path segment — omitting it (older
    URL form) still returns 200 but with every player's projection empty.
    """
    return _get(f"{SLEEPER_BASE}/projections/nfl/{season_type}/{season}/{week}") or {}


def sleeper_get_weekly_projections_batch(
    season: int, weeks: range = range(1, 19), season_type: str = "regular"
) -> Dict[int, Dict[str, dict]]:
    """
    Fetch per-week projections for every week in `weeks`.
    Used as a fallback to build a full-season total when Sleeper hasn't yet
    computed the week=0 season aggregate (common pre-kickoff) — weekly
    projections are populated well before that.
    Returns {week: {player_id: stats}}.
    """
    return {wk: sleeper_get_projections(season, wk, season_type) for wk in weeks}


def sleeper_get_player_stats(player_id: str, season: int) -> dict:
    """Get historical actuals for a single player."""
    return _get(f"{SLEEPER_BASE}/stats/nfl/player/{player_id}?season_type=regular&season={season}") or {}


def sleeper_get_trending(trend_type: str = "add", sport: str = "nfl", lookback: int = 24, limit: int = 25) -> List[dict]:
    """Get trending adds/drops for news ticker."""
    return _get(
        f"{SLEEPER_BASE}/players/nfl/trending/{trend_type}",
        params={"lookback_hours": lookback, "limit": limit}
    ) or []


def sleeper_get_league_drafts(league_id: str) -> List[dict]:
    """Get all drafts associated with a league."""
    return _get(f"{SLEEPER_BASE}/league/{league_id}/drafts") or []


def sleeper_get_draft_picks(draft_id: str) -> List[dict]:
    """Get all picks made in a draft."""
    return _get(f"{SLEEPER_BASE}/draft/{draft_id}/picks") or []


# ---------------------------------------------------------------------------
# ESPN API
# ---------------------------------------------------------------------------

def espn_get_league(league_id: int, year: int = 2025, espn_s2: str = "", swid: str = ""):
    """
    Return espn_api.football.League instance.
    Requires espn-api package and valid credentials.
    """
    try:
        from espn_api.football import League
        return League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
    except ImportError:
        raise ImportError("espn-api package not installed. Run: pip install espn-api")
    except Exception as e:
        raise RuntimeError(f"ESPN API error: {e}")


def espn_get_full_player_pool(espn_league, size: int = 3000) -> List[dict]:
    """
    Pull every rostered + free-agent player from an ESPN league, with
    projected_total_points already scored under the league's actual settings.
    Pre-draft, all players are free agents, so this covers the whole player pool.
    """
    players = list(espn_league.free_agents(size=size))
    for team in espn_league.teams:
        players.extend(team.roster)

    result = []
    seen = set()
    for p in players:
        if p.playerId in seen:
            continue
        seen.add(p.playerId)
        result.append({
            "espn_id": p.playerId,
            "name": p.name,
            "position": p.position,
            "team": p.proTeam,
            "injury_status": getattr(p, "injuryStatus", None),
            "projected_total_points": getattr(p, "projected_total_points", 0.0) or 0.0,
        })
    return result


def espn_get_weekly_scores(espn_league, week: Optional[int] = None) -> Dict[str, float]:
    """
    Pull every team's total score for a given week (defaults to the league's
    current week). Returns {team_name: score}, including the "Fake team" —
    callers that need to exclude it do so themselves (see src/weekly/payout.py).
    Uses box_scores() rather than scoreboard() since it resolves both sides of
    a matchup to Team objects even for a mid-week/live period.
    """
    scores: Dict[str, float] = {}
    for box in espn_league.box_scores(week=week):
        if box.home_team is not None:
            scores[box.home_team.team_name] = box.home_score
        if box.away_team is not None:
            scores[box.away_team.team_name] = box.away_score
    return scores


# Owners whose group-text label isn't just their first name (nicknames the
# league actually uses). Keyed by (firstName, lastName) lowercased so it
# survives however ESPN capitalizes a given owner's profile.
_MANAGER_LABEL_OVERRIDES = {
    ("alex", "costa"): "Costa",
    ("matt", "medvene"): "Medvene",
    ("tyler", "carwell"): "Tex",
}


def espn_get_team_managers(espn_league) -> Dict[str, str]:
    """
    Map {team_name: manager_label} from the league's current owners — see
    https://fantasy.espn.com/football/tools/leaguemembers?leagueId=<id> for
    the source of truth this mirrors. Resolved fresh from team.owners (not
    the team name) each call, since team names get renamed week to week but
    ESPN's owner records don't.
    Label is the owner's first name, except the overrides in
    _MANAGER_LABEL_OVERRIDES (nicknames the league actually uses).
    Falls back to the team name if a team has no listed owner.
    """
    managers = {}
    for team in espn_league.teams:
        owners = getattr(team, "owners", None)
        if not owners:
            managers[team.team_name] = team.team_name
            continue
        owner = owners[0]
        first = (owner.get("firstName") or "").strip()
        last = (owner.get("lastName") or "").strip()
        override = _MANAGER_LABEL_OVERRIDES.get((first.lower(), last.lower()))
        managers[team.team_name] = override or (first.capitalize() if first else team.team_name)
    return managers


def espn_get_fake_team_opponent(
    espn_league, week: Optional[int], fake_team_name: str
) -> Optional[Tuple[str, float]]:
    """
    Find whichever real team played the "Fake team" this week — that's the
    team on the hook to beat the league median. Returns (opponent_name,
    opponent_score), or None if the Fake team has no matchup that week.
    """
    for box in espn_league.box_scores(week=week):
        home_name = box.home_team.team_name if box.home_team else None
        away_name = box.away_team.team_name if box.away_team else None
        if home_name == fake_team_name and away_name is not None:
            return away_name, box.away_score
        if away_name == fake_team_name and home_name is not None:
            return home_name, box.home_score
    return None


def espn_get_draft_picks(espn_league) -> List[dict]:
    """Extract draft picks from ESPN league object."""
    picks = []
    try:
        draft = espn_league.draft
        for pick in draft:
            picks.append({
                "pick_number": pick.round_num * 100 + pick.round_pick,  # rough ordering
                "round_number": pick.round_num,
                "pick_in_round": pick.round_pick,
                "player_name": pick.playerName,
                "team_id": pick.team.team_id if pick.team else None,
            })
    except Exception:
        pass
    return picks


# ---------------------------------------------------------------------------
# FantasyPros ADP
# ---------------------------------------------------------------------------

def fantasypros_get_adp(scoring_type: str = "PPR", season: int = 2025) -> List[dict]:
    """
    Scrape FantasyPros consensus ADP.
    scoring_type: "PPR", "HALF", "STD"
    Returns list of dicts with name, position, adp, team.
    Falls back to empty list on failure (caller should use Sleeper projections as proxy).
    """
    url = f"https://www.fantasypros.com/nfl/adp/overall.php"
    params = {"scoring": scoring_type, "year": season}
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        # FantasyPros returns HTML — parse the JSON embedded in the page
        import re
        match = re.search(r"var ecrData\s*=\s*(\{.*?\});", resp.text, re.DOTALL)
        if not match:
            return []
        import json
        data = json.loads(match.group(1))
        players = data.get("players", [])
        result = []
        for rank, p in enumerate(players, 1):
            result.append({
                "name": p.get("player_name", ""),
                "position": p.get("player_position_id", ""),
                "team": p.get("player_team_id", ""),
                "adp_overall": p.get("avg_pick", rank),
                "source": "fantasypros",
            })
        return result
    except Exception:
        return []


def fantasypros_parse_local_csv(path: str) -> List[dict]:
    """
    Parse a locally-downloaded FantasyPros 'Draft ALL Rankings' CSV export.
    Columns: RK, TIERS, PLAYER NAME, TEAM, FANTASYPTS,
             passing YDS/TDS, REC/receiving YDS/TDS, rushing ATT/YDS/TDS.
    Returns raw dicts — normalize_fantasypros_local() converts to DB rows.
    """
    import csv as _csv

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = _csv.reader(f)
        next(reader, None)  # header
        for r in reader:
            if len(r) < 13:
                continue
            rows.append({
                "rank": int(r[0]),
                "tier": int(r[1]),
                "name": r[2],
                "team": r[3],
                "fantasy_pts": float(r[4] or 0),
                "pass_yd": float(r[5] or 0),
                "pass_td": float(r[6] or 0),
                "rec": float(r[7] or 0),
                "rec_yd": float(r[8] or 0),
                "rec_td": float(r[9] or 0),
                "rush_yd": float(r[11] or 0),
                "rush_td": float(r[12] or 0),
            })
    return rows


def fantasypros_parse_local_bye_weeks_csv(path: str) -> List[dict]:
    """
    Parse a locally-downloaded FantasyPros 'Draft ALL Rankings' cheat-sheet CSV
    (the variant with BYE WEEK / UPSIDE / BUST / SOS SEASON / ECR VS. ADP columns,
    as opposed to the stat-line variant handled by fantasypros_parse_local_csv()).
    """
    import csv as _csv

    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = _csv.reader(f)
        next(reader, None)  # header
        for r in reader:
            if len(r) < 6:
                continue
            try:
                bye = int(r[5])
            except (ValueError, IndexError):
                continue
            rows.append({"name": r[2], "team": r[3], "bye_week": bye})
    return rows


def fantasypros_get_projections(season: int = 2025, scoring: str = "PPR") -> List[dict]:
    """
    Fetch FantasyPros weekly projections via their data endpoint.
    Falls back to empty list — caller should use Sleeper projections.
    """
    try:
        url = f"https://www.fantasypros.com/nfl/projections/qb.php"
        # FantasyPros doesn't have a clean JSON API; return empty and use Sleeper
        return []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# nfl_data_py
# ---------------------------------------------------------------------------

def nfldata_import_ids() -> "pd.DataFrame":
    """Import player ID mapping table (Sleeper ↔ gsis_id ↔ ESPN)."""
    try:
        import nfl_data_py as nfl
        return nfl.import_ids()
    except Exception as e:
        raise RuntimeError(f"nfl_data_py import_ids failed: {e}")


def nfldata_import_seasonal(seasons: List[int]) -> "pd.DataFrame":
    """
    Import seasonal aggregate stats: target_share, air_yards_share, wopr,
    carry_share, snap counts, etc.
    """
    try:
        import nfl_data_py as nfl
        return nfl.import_seasonal_data(seasons)
    except Exception as e:
        raise RuntimeError(f"nfl_data_py import_seasonal_data failed: {e}")


def nfldata_import_weekly(seasons: List[int]) -> "pd.DataFrame":
    """Import weekly stats (carries, targets, receptions, TDs per week)."""
    try:
        import nfl_data_py as nfl
        return nfl.import_weekly_data(seasons)
    except Exception as e:
        raise RuntimeError(f"nfl_data_py import_weekly_data failed: {e}")


def nfldata_import_snap_counts(seasons: List[int]) -> "pd.DataFrame":
    """Import snap count percentages by player/week."""
    try:
        import nfl_data_py as nfl
        return nfl.import_snap_counts(seasons)
    except Exception as e:
        raise RuntimeError(f"nfl_data_py import_snap_counts failed: {e}")


def nfldata_import_schedules(seasons: List[int]) -> "pd.DataFrame":
    """Import schedules (for playoff SOS calculation)."""
    try:
        import nfl_data_py as nfl
        return nfl.import_schedules(seasons)
    except Exception as e:
        raise RuntimeError(f"nfl_data_py import_schedules failed: {e}")
