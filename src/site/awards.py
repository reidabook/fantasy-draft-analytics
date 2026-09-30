"""
Derived stats + weekly awards over the dict from collect.py. Pure functions,
no network — unit-tested in tests/test_site_awards.py.

The fake team (the weekly league-median stand-in, see weekly_update.py) is
excluded from every leaderboard/award as a *winner*; games against it still
count for the real team that drew it.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from src.weekly.payout import compute_median, find_high_scorer


def week_results(data: dict, week: int) -> List[dict]:
    """One row per team that played: {team_id, score, opp_id, opp_score, margin, won}."""
    rows = []
    for m in data["weeks"].get(str(week), []):
        for me, opp in (("home", "away"), ("away", "home")):
            a, b = m[me], m[opp]
            rows.append({
                "team_id": a["team_id"],
                "score": a["score"],
                "opp_id": b["team_id"],
                "opp_score": b["score"],
                "margin": round(a["score"] - b["score"], 2),
                "won": a["score"] > b["score"],
            })
    return rows


def _real(data: dict, rows: List[dict]) -> List[dict]:
    return [r for r in rows if r["team_id"] != data["fake_team_id"]]


def week_scores(data: dict, week: int) -> Dict[str, float]:
    """{team_id: score} for the week, fake team included (as compute_median expects)."""
    return {r["team_id"]: r["score"] for r in week_results(data, week)}


def week_median(data: dict, week: int) -> Optional[float]:
    scores = week_scores(data, week)
    if data["fake_team_id"] not in scores:
        return None
    return compute_median(scores, data["fake_team_id"])


def season_table(data: dict) -> List[dict]:
    """
    Standings rows for real teams, with all-play record (your score vs every
    other real team, every week) and record vs the league median — sorted by
    ESPN's actual standing. `power` is the all-play rank.
    """
    table = {
        tid: {**t, "ap_w": 0, "ap_l": 0, "med_w": 0, "med_l": 0, "scores": []}
        for tid, t in data["teams"].items() if not t["is_fake"]
    }
    for w in range(1, data["week"] + 1):
        real = _real(data, week_results(data, w))
        median = week_median(data, w)
        for r in real:
            row = table[r["team_id"]]
            row["scores"].append(r["score"])
            others = [o["score"] for o in real if o["team_id"] != r["team_id"]]
            row["ap_w"] += sum(r["score"] > s for s in others)
            row["ap_l"] += sum(r["score"] < s for s in others)
            if median is not None:
                if r["score"] > median:
                    row["med_w"] += 1
                elif r["score"] < median:
                    row["med_l"] += 1

    rows = list(table.values())
    by_power = sorted(rows, key=lambda r: (r["ap_w"] / max(1, r["ap_w"] + r["ap_l"]), r["pf"]), reverse=True)
    for i, r in enumerate(by_power, 1):
        r["power"] = i
        r["luck"] = r["wins"] - round(r["ap_w"] / max(1, r["ap_w"] + r["ap_l"]) * (r["wins"] + r["losses"]), 1)
    return sorted(rows, key=lambda r: r["standing"])


def weekly_awards(data: dict, week: int) -> List[dict]:
    """
    Awards for one completed week. Each: {key, title, team_id, value, detail}.
    `detail` is short factual copy; the AI writer riffs on top of it.
    """
    rows = week_results(data, week)
    real = _real(data, rows)
    if not real:
        return []
    fake = data["fake_team_id"]
    name = lambda tid: data["teams"][tid]["name"]  # noqa: E731
    awards = []

    top_id, top = find_high_scorer(week_scores(data, week), fake)
    awards.append({"key": "top_dog", "title": "Top Dog", "team_id": top_id, "value": top,
                   "detail": f"Week-high {top:.1f} — takes the weekly payout."})

    low = min(real, key=lambda r: r["score"])
    awards.append({"key": "basement", "title": "Basement Dweller", "team_id": low["team_id"], "value": low["score"],
                   "detail": f"Week-low {low['score']:.1f}."})

    # Blowout / nail-biter consider each game once, from the (real) winner's side.
    games = [r for r in real if r["won"]]
    if games:
        blow = max(games, key=lambda r: r["margin"])
        awards.append({"key": "blowout", "title": "Biggest Blowout", "team_id": blow["team_id"], "value": blow["margin"],
                       "detail": f"Beat {name(blow['opp_id'])} by {blow['margin']:.1f}."})
        close = min(games, key=lambda r: r["margin"])
        awards.append({"key": "nail_biter", "title": "Nail-Biter", "team_id": close["team_id"], "value": close["margin"],
                       "detail": f"Survived {name(close['opp_id'])} by {close['margin']:.1f}."})

    real_wins = [r for r in real if r["won"]]
    real_losses = [r for r in real if not r["won"]]
    if real_wins:
        rob = min(real_wins, key=lambda r: r["score"])
        awards.append({"key": "robbery", "title": "Daylight Robbery", "team_id": rob["team_id"], "value": rob["score"],
                       "detail": f"Won with just {rob['score']:.1f}."})
    if real_losses:
        heart = max(real_losses, key=lambda r: r["score"])
        awards.append({"key": "heartbreaker", "title": "Heartbreaker", "team_id": heart["team_id"], "value": heart["score"],
                       "detail": f"Lost despite scoring {heart['score']:.1f}."})

    sides = [s for m in data["weeks"].get(str(week), []) for s in (m["home"], m["away"]) if s["team_id"] != fake]
    starters = [(s["team_id"], s["top_starter"]) for s in sides if s["top_starter"]]
    if starters:
        tid, p = max(starters, key=lambda x: x[1]["pts"])
        awards.append({"key": "mvp", "title": "Player of the Week", "team_id": tid, "value": p["pts"],
                       "detail": f"{p['name']} ({p['pos']}) dropped {p['pts']:.1f}."})
    # Bench blunder: biggest gap between a benched player and a same-position
    # starter he'd have replaced.
    blunders = []
    for s in sides:
        for b in s["bench"]:
            same_pos = [p for p in s["starters"] if p["pos"] == b["pos"]]
            if same_pos:
                w = min(same_pos, key=lambda p: p["pts"])
                if b["pts"] > w["pts"]:
                    blunders.append((s["team_id"], b, w))
    if blunders:
        tid, b, w = max(blunders, key=lambda x: x[1]["pts"] - x[2]["pts"])
        awards.append({"key": "bench_blunder", "title": "Bench Blunder", "team_id": tid, "value": round(b["pts"] - w["pts"], 2),
                       "detail": f"Left {b['name']} ({b['pts']:.1f}) on the bench, started {w['name']} ({w['pts']:.1f})."})
    return awards


def power_rankings(data: dict) -> List[dict]:
    """season_table rows ordered by power rank, with per-game scoring average."""
    rows = sorted(season_table(data), key=lambda r: r["power"])
    for r in rows:
        r["avg"] = round(sum(r["scores"]) / len(r["scores"]), 2) if r["scores"] else 0.0
    return rows


PLAYOFF_TALK_WEEKS_OUT = 5


def playoff_talk_ok(data: dict) -> bool:
    """Playoff races only get airtime in the last few regular-season weeks."""
    upcoming = data["next_week"] or data["week"]
    return data["reg_season_weeks"] - upcoming < PLAYOFF_TALK_WEEKS_OUT


def playoff_picture(data: dict) -> Dict[str, List[dict]]:
    """
    If the season ended today: the top `playoff_teams` by ESPN standing are in,
    the next two are knocking, winless teams need a miracle, the rest are long
    shots.
    """
    n = data.get("playoff_teams") or 6
    tiers: Dict[str, List[dict]] = {"in": [], "knocking": [], "long_shots": [], "miracle": []}
    for r in season_table(data):
        if r["standing"] <= n:
            tiers["in"].append(r)
        elif r["standing"] <= n + 2:
            tiers["knocking"].append(r)
        elif r["wins"] == 0:
            tiers["miracle"].append(r)
        else:
            tiers["long_shots"].append(r)
    return tiers


def injured_starters(side: dict) -> List[dict]:
    """Projected starters carrying an injury designation (OUT, QUESTIONABLE, ...)."""
    return [p for p in side.get("starters", []) if p.get("injury")]


def game_of_the_week(data: dict) -> Optional[dict]:
    """
    Upcoming matchup (excluding The Median's) with the best combined power
    rank, ties broken by closest projection — the default spotlight when the
    AI copy doesn't pick one.
    """
    table = {r["id"]: r for r in season_table(data)}
    games = [m for m in data["upcoming"]
             if m["home"]["team_id"] in table and m["away"]["team_id"] in table]
    if not games:
        return None
    return min(games, key=lambda m: (
        table[m["home"]["team_id"]]["power"] + table[m["away"]["team_id"]]["power"],
        abs(m["home"]["projected"] - m["away"]["projected"]),
    ))


def injury_report(data: dict) -> List[dict]:
    """
    Every real team's injured players (starters, bench and IR) from the
    upcoming week's rosters — or the last completed week's if there's no
    upcoming week. Most-injured team first. Each player gets `role`:
    "starter" / "bench" / "ir"; `dead_slot` flags starters projected 0.
    """
    matchups = data["upcoming"] or data["weeks"].get(str(data["week"]), [])
    report = []
    for m in matchups:
        for side in (m["home"], m["away"]):
            tid = side["team_id"]
            if data["teams"][tid]["is_fake"]:
                continue
            players = [
                {**p, "role": role, "dead_slot": role == "starter" and p["proj"] == 0}
                for role, group in (("starter", side.get("starters", [])), ("bench", side.get("bench", [])), ("ir", side.get("ir", [])))
                for p in group if p.get("injury")
            ]
            report.append({"team_id": tid, "players": players,
                           "starters_hurt": sum(p["role"] == "starter" for p in players)})
    return sorted(report, key=lambda r: (len(r["players"]), r["starters_hurt"]), reverse=True)


def injury_spotlight(data: dict, pinned: Optional[str] = None) -> Optional[dict]:
    """
    The team to feature in the Training Room: `pinned` (manager label or team
    name, e.g. INJURY_SPOTLIGHT=Medvene) if that team has anyone hurt,
    otherwise the most-injured team. None if the whole league is healthy.
    """
    report = [r for r in injury_report(data) if r["players"]]
    if not report:
        return None
    if pinned:
        key = pinned.strip().lower()
        for r in report:
            t = data["teams"][r["team_id"]]
            if key in (t["manager"].lower(), t["name"].lower()):
                return r
    return report[0]
