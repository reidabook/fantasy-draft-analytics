"""
Render the collected data + copy into a static site:

    <out>/index.html            latest week
    <out>/weeks/week{N}.html    permanent archive copy of each week
    <out>/data.json             raw collected data for the latest week

Everything is a single self-contained HTML file (inline CSS/JS, Google Fonts
the only external request besides team logos).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.site.awards import (
    game_of_the_week, injured_starters, injury_report, injury_spotlight, playoff_picture,
    playoff_talk_ok, power_rankings, season_table, week_median, weekly_awards,
)
from src.site.writer import SiteCopy

_TEMPLATES = Path(__file__).parent / "templates"


def _archive_weeks(out: Path, current: int) -> list:
    weeks = {current}
    for f in (out / "weeks").glob("week*.html"):
        m = re.fullmatch(r"week(\d+)\.html", f.name)
        if m:
            weeks.add(int(m.group(1)))
    return sorted(weeks, reverse=True)


def render_site(data: dict, copy: SiteCopy, out: Path) -> Path:
    out = Path(out)
    (out / "weeks").mkdir(parents=True, exist_ok=True)
    week = data["week"]

    def keyed(blurbs):
        return {frozenset((b.home_id, b.away_id)): b.blurb for b in blurbs}

    result_blurbs, upcoming_blurbs = keyed(copy.results), keyed(copy.upcoming)
    quips = {a.key: a.quip for a in copy.awards}

    # Game of the week: Claude's pick if it names a real upcoming matchup,
    # else the computed default. It's pulled out of the regular matchup list.
    upcoming = [
        {**m, "blurb": upcoming_blurbs.get(frozenset((m["home"]["team_id"], m["away"]["team_id"])), ""),
         "injuries": injured_starters(m["home"]) + injured_starters(m["away"])}
        for m in data["upcoming"]
    ]
    pick = frozenset((copy.game_of_week.home_id, copy.game_of_week.away_id)) if copy.game_of_week else None
    default = game_of_the_week(data)
    default = frozenset((default["home"]["team_id"], default["away"]["team_id"])) if default else None
    key = lambda m: frozenset((m["home"]["team_id"], m["away"]["team_id"]))  # noqa: E731
    gotw = next((m for m in upcoming if key(m) == pick), None) or next((m for m in upcoming if key(m) == default), None)
    if gotw is not None:
        upcoming = [m for m in upcoming if m is not gotw]
        if copy.game_of_week and key(gotw) == pick:
            gotw = {**gotw, "why": copy.game_of_week.blurb}
    ctx = {
        "data": data,
        "teams": data["teams"],
        "copy": copy,
        "week": week,
        "median": week_median(data, week),
        "table": season_table(data),
        "awards": [{**a, "quip": quips.get(a["key"], a["detail"])} for a in weekly_awards(data, week)],
        "results": [
            {**m, "blurb": result_blurbs.get(frozenset((m["home"]["team_id"], m["away"]["team_id"])), "")}
            for m in data["weeks"][str(week)]
        ],
        "upcoming": upcoming,
        "gotw": gotw,
        "hero_week": data["next_week"] or week,
        "power": power_rankings(data),
        "tiers": playoff_picture(data),
        "playoffs_early": not playoff_talk_ok(data),
        "spotlight": injury_spotlight(data, os.getenv("INJURY_SPOTLIGHT")),
        "injury_counts": [r for r in injury_report(data) if r["players"]],
        "team_blurbs": {b.team_id: b.blurb for b in copy.teams},
        "archive": _archive_weeks(out, week),
        "as_of": datetime.fromisoformat(data["generated_at"]).strftime("%b %-d, %Y").upper(),
    }

    env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
    template = env.get_template("index.html")
    (out / "index.html").write_text(template.render(**ctx, root=""))
    (out / "weeks" / f"week{week}.html").write_text(template.render(**ctx, root="../"))
    (out / "data.json").write_text(json.dumps(data, indent=1))
    return out / "index.html"
