"""
Site copy (headline, recaps, team blurbs, round-up) written by Claude from the
week's stats, with a templated fallback (--no-ai). Runs through the local
Claude Code CLI (`claude -p`) so it bills the Claude Code subscription, not an
API key. AI copy is cached per week in data/site/ so re-renders don't re-run
it; pass refresh=True to regenerate.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, ValidationError

from src.site.awards import (
    game_of_the_week, injured_starters, injury_spotlight, playoff_picture, playoff_talk_ok,
    power_rankings, season_table, week_median, weekly_awards,
)

MODEL = "sonnet"  # Claude Code alias for the latest Sonnet
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "site"


class MatchupBlurb(BaseModel):
    home_id: str
    away_id: str
    blurb: str


class TeamBlurb(BaseModel):
    team_id: str
    blurb: str


class AwardQuip(BaseModel):
    key: str
    quip: str


class SiteCopy(BaseModel):
    # Upcoming week — the lead of the page.
    dek: str
    preview_headline: str
    preview_intro: List[str]
    game_of_week: Optional[MatchupBlurb]
    upcoming: List[MatchupBlurb]
    power: str
    injury_spotlight: str
    playoffs: str
    # Last week — below the fold.
    recap_headline: str
    recap: List[str]
    results: List[MatchupBlurb]
    teams: List[TeamBlurb]
    awards: List[AwardQuip]
    round_up: List[str]


SYSTEM = """You write the weekly newsletter for a 13-person friends' fantasy football league. \
It publishes right after a week's games go final, so it LEADS WITH THE UPCOMING WEEK — what's at stake, \
who's favored, which games matter — and treats last week as supporting context. \
Voice: a sharp sports columnist who knows everyone in the group chat — witty, specific, lightly roasting, \
never mean-spirited or crude. Refer to managers by the first names/nicknames given. \
Only use facts present in the data; never invent injuries, trades, or stats (injury designations \
listed on projected starters are real — use them). \
There is a "fake team" that scores exactly the league median every week — whoever plays it is \
really playing "the median"; call it The Median. It never wins awards and has no real projection.

Fields:
- dek: 1-2 sentences under the big "Week N" masthead setting up the upcoming week.
- preview_headline: 2-5 punchy words about the upcoming week (like "Somebody's Getting Exposed").
- preview_intro: 1-2 short paragraphs framing the upcoming week — storylines, stakes, standings pressure; \
end by teeing up the matchups.
- game_of_week: pick the single most compelling upcoming matchup; blurb 2-3 sentences on why.
- upcoming: one entry per upcoming matchup (include the game of the week too), 2-3 sentences each: \
the stakes, the projection, and any injured starters.
- power: 2-3 sentences on the power rankings (all-play based) — who's better or worse than their record, \
name the luckiest and unluckiest.
- injury_spotlight: 2-4 sentences on the spotlighted team's injury situation (the "Training Room") — \
who's hurt, how it hits this week's lineup (flag any starter projected 0), and the matchup consequences. \
Sympathetic-but-roasting. Empty string if no spotlight is given.
- playoffs: 2-4 sentences on the playoff picture, using the tiers given. If playoff_talk is "too_early", \
frame it as way-too-early standings trivia (a lot can change) and keep ALL playoff/seeding talk inside this \
field only — don't mention playoffs, playoff lines or seeding anywhere else in the newsletter.
- recap_headline: 2-5 words on last week. recap: 1-2 short paragraphs on last week.
- results: one 1-2 sentence blurb per completed matchup last week.
- teams: 1-2 sentences per team on their season so far. awards: one sentence per award.
- round_up: 3-5 short paragraphs: state of the league, trends, what to watch.
Plain text, no markdown."""


def _spotlight_brief(data: dict, label) -> Optional[dict]:
    spot = injury_spotlight(data, os.getenv("INJURY_SPOTLIGHT"))
    if not spot:
        return None
    return {
        "team": label(spot["team_id"]),
        "injured": [
            {"player": f"{p['name']} ({p['pos']})", "status": p["injury"], "role": p["role"],
             "projected": p["proj"], "starting_while_projected_zero": p["dead_slot"]}
            for p in spot["players"]
        ],
    }


def _brief(data: dict) -> dict:
    """Compact, model-friendly view of the week — names resolved, no full lineups."""
    week = data["week"]
    teams = data["teams"]
    table = {r["id"]: r for r in season_table(data)}
    label = lambda tid: f"{teams[tid]['name']} ({teams[tid]['manager']})" if not teams[tid]["is_fake"] else "The Median"  # noqa: E731

    def team_ctx(tid):
        r = table.get(tid)
        return {"record": f"{r['wins']}-{r['losses']}", "power_rank": r["power"], "streak": r["streak"]} if r else None

    def games(matchups, upcoming=False):
        out = []
        for m in matchups:
            h, a = m["home"], m["away"]
            g = {"home_id": h["team_id"], "away_id": a["team_id"], "home": label(h["team_id"]), "away": label(a["team_id"])}
            if upcoming:
                for side, s in (("home", h), ("away", a)):
                    if teams[s["team_id"]]["is_fake"]:
                        continue  # The Median's own projection is meaningless (its score is set after the fact).
                    g[f"{side}_proj"] = s["projected"]
                    g[f"{side}_context"] = team_ctx(s["team_id"])
                    g[f"{side}_injured_starters"] = [f"{p['name']} ({p['pos']}, {p['injury']})" for p in injured_starters(s)]
            else:
                g.update(home_score=h["score"], away_score=a["score"],
                         home_top=h["top_starter"], away_top=a["top_starter"])
            out.append(g)
        return out

    gotw = game_of_the_week(data)
    return {
        "league": data["league_name"],
        "upcoming_week": data["next_week"],
        "last_completed_week": week,
        "playoff_spots": data.get("playoff_teams"),
        "regular_season_weeks": data["reg_season_weeks"],
        "upcoming": games(data["upcoming"], upcoming=True),
        "suggested_game_of_week": [gotw["home"]["team_id"], gotw["away"]["team_id"]] if gotw else None,
        "power_rankings": [
            {"power_rank": r["power"], "team": label(r["id"]), "record": f"{r['wins']}-{r['losses']}",
             "all_play": f"{r['ap_w']}-{r['ap_l']}", "avg_score": r["avg"], "luck": r["luck"]}
            for r in power_rankings(data)
        ],
        "playoff_talk": "on" if playoff_talk_ok(data) else "too_early",
        "playoff_picture": {
            tier: [f"{label(r['id'])} {r['wins']}-{r['losses']}" for r in rows]
            for tier, rows in playoff_picture(data).items()
        },
        "injury_spotlight": _spotlight_brief(data, label),
        "standings": [
            {"team_id": r["id"], "team": label(r["id"]), "record": f"{r['wins']}-{r['losses']}",
             "points_for": r["pf"], "vs_median": f"{r['med_w']}-{r['med_l']}", "streak": r["streak"],
             "weekly_scores": r["scores"]}
            for r in table.values()
        ],
        "last_week_median": week_median(data, week),
        "last_week_results": games(data["weeks"][str(week)]),
        "last_week_awards": [{**a, "team": label(a["team_id"])} for a in weekly_awards(data, week)],
    }


def _claude_bin() -> str:
    # launchd/cron PATHs often lack Homebrew, so fall back to its usual spot.
    found = os.getenv("CLAUDE_BIN") or shutil.which("claude") or "/opt/homebrew/bin/claude"
    if not Path(found).exists():
        raise RuntimeError("Claude Code CLI not found — install it or set CLAUDE_BIN.")
    return found


def _ai_copy(data: dict) -> SiteCopy:
    # Lean headless run: custom system prompt, no tools/MCP/settings/session
    # files — otherwise Claude Code loads its full agent context (~270k tokens).
    cmd = [
        _claude_bin(), "-p", "This week's data:\n" + json.dumps(_brief(data), indent=1),
        "--model", MODEL,
        "--system-prompt", SYSTEM,
        "--output-format", "json",
        "--json-schema", json.dumps(SiteCopy.model_json_schema()),
        "--tools", "",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    # Drop API-key/nested-session env so it uses the logged-in subscription.
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE")}
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=CACHE_DIR.parent, timeout=600)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p failed (exit {proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    if result.get("is_error") or not result.get("structured_output"):
        raise RuntimeError(f"claude -p returned no copy: {result.get('subtype')} {result.get('result')}")
    return SiteCopy.model_validate(result["structured_output"])


def _templated_spotlight(data: dict) -> str:
    spot = injury_spotlight(data, os.getenv("INJURY_SPOTLIGHT"))
    if not spot:
        return ""
    t = data["teams"][spot["team_id"]]
    dead = [p["name"] for p in spot["players"] if p["dead_slot"]]
    return (f"{t['name']} has {len(spot['players'])} players on the injury report"
            + (f", including {', '.join(dead)} in the starting lineup projected for 0." if dead else "."))


def templated_copy(data: dict) -> SiteCopy:
    """Rule-based copy — no API call. Good enough to publish, just not funny."""
    week = data["week"]
    teams = data["teams"]
    label = lambda tid: "The Median" if teams[tid]["is_fake"] else teams[tid]["name"]  # noqa: E731
    awards = weekly_awards(data, week)
    top = next((a for a in awards if a["key"] == "top_dog"), None)
    table = season_table(data)

    def blurb(m, final):
        h, a = m["home"], m["away"]
        if not final:
            if teams[h["team_id"]]["is_fake"] or teams[a["team_id"]]["is_fake"]:
                real = a if teams[h["team_id"]]["is_fake"] else h
                return MatchupBlurb(home_id=h["team_id"], away_id=a["team_id"],
                                    blurb=f"{label(real['team_id'])} (proj. {real['projected']:.1f}) needs to beat the league median.")
            fav, dog = (h, a) if h["projected"] >= a["projected"] else (a, h)
            return MatchupBlurb(home_id=h["team_id"], away_id=a["team_id"],
                                blurb=f"{label(fav['team_id'])} projected {fav['projected']:.1f} to {dog['projected']:.1f}.")
        w, l = (h, a) if h["score"] >= a["score"] else (a, h)
        return MatchupBlurb(home_id=h["team_id"], away_id=a["team_id"],
                            blurb=f"{label(w['team_id'])} beat {label(l['team_id'])} {w['score']:.1f}–{l['score']:.1f}.")

    power = power_rankings(data)
    tiers = playoff_picture(data)
    gotw = game_of_the_week(data)
    nxt = data["next_week"]
    return SiteCopy(
        dek=(f"{len(data['upcoming'])} matchups are set for Week {nxt}. Week {week} is final." if nxt
             else f"Week {week} is final."),
        preview_headline=f"Week {nxt} Preview" if nxt else f"Week {week} in the Books",
        preview_intro=[f"{table[0]['name']} leads the league at {table[0]['wins']}-{table[0]['losses']}."] if table else [],
        game_of_week=MatchupBlurb(home_id=gotw["home"]["team_id"], away_id=gotw["away"]["team_id"],
                                  blurb="The best combined power ranking on the slate.") if gotw else None,
        upcoming=[blurb(m, False) for m in data["upcoming"]],
        power=(f"{power[0]['name']} tops the power rankings with an all-play record of "
               f"{power[0]['ap_w']}-{power[0]['ap_l']}.") if power else "",
        injury_spotlight=_templated_spotlight(data),
        playoffs=(f"{len(tiers['in'])} teams would be in if the season ended today"
                  + ("." if playoff_talk_ok(data) else " — way too early to read into it.")),
        recap_headline=f"Week {week} in the Books",
        recap=[(f"{label(top['team_id'])} led the league with {top['value']:.1f}. " if top else "")
               + f"League median: {week_median(data, week) or 0:.1f}."],
        results=[blurb(m, True) for m in data["weeks"][str(week)]],
        teams=[TeamBlurb(team_id=r["id"], blurb=f"{r['wins']}-{r['losses']}, {r['pf']:.1f} PF, power rank #{r['power']}.")
               for r in table],
        awards=[AwardQuip(key=a["key"], quip=a["detail"]) for a in awards],
        round_up=[f"{table[0]['name']} sits atop the standings at {table[0]['wins']}-{table[0]['losses']}."] if table else [],
    )


def get_copy(data: dict, use_ai: bool = True, refresh: bool = False) -> SiteCopy:
    if not use_ai:
        return templated_copy(data)
    cache = CACHE_DIR / f"{data['season']}_week{data['week']}_copy.json"
    if cache.exists() and not refresh:
        try:
            return SiteCopy.model_validate_json(cache.read_text())
        except ValidationError:
            pass  # cached under an older SiteCopy schema — regenerate
    copy = _ai_copy(data)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(copy.model_dump_json(indent=2))
    return copy
