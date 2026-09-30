"""
Render the collected data + copy into a static site:

    <out>/index.html            latest issue
    <out>/weeks/week{N}.json    snapshot of each issue: collected data (incl. that
                                week's injury statuses) + Claude copy
    <out>/weeks/week{N}.html    each issue, re-rendered from its snapshot
    <out>/data.json             raw collected data for the latest issue

Issues are numbered by the week they preview (the masthead week), not the
week they recap. Every build re-renders all archived issues from their
snapshots, so old pages pick up template changes and the full archive list.

Everything is a single self-contained HTML file (inline CSS/JS, Google Fonts
the only external request besides team logos).
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.site.awards import (
    game_of_the_week, injured_starters, injury_report, injury_spotlight, playoff_picture,
    playoff_talk_ok, power_rankings, season_table, week_median, weekly_awards,
)
from src.site.writer import SiteCopy

_TEMPLATES = Path(__file__).parent / "templates"


def issue_week(data: dict) -> int:
    """The week an issue leads with: the upcoming week, or the last one once the regular season's done."""
    return data["next_week"] or data["week"]


def _context(data: dict, copy: SiteCopy, spotlight_pin: Optional[str]) -> dict:
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
    return {
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
        "hero_week": issue_week(data),
        "power": power_rankings(data),
        "tiers": playoff_picture(data),
        "playoffs_early": not playoff_talk_ok(data),
        "spotlight": injury_spotlight(data, spotlight_pin),
        "injury_counts": [r for r in injury_report(data) if r["players"]],
        "team_blurbs": {b.team_id: b.blurb for b in copy.teams},
        "as_of": datetime.fromisoformat(data["generated_at"]).strftime("%b %-d, %Y").upper(),
    }


def render_site(data: dict, copy: SiteCopy, out: Path) -> Path:
    out = Path(out)
    weeks_dir = out / "weeks"
    weeks_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot this issue. The spotlight pin is stored so re-renders of old
    # issues don't shift if INJURY_SPOTLIGHT changes later.
    snapshot = {"data": data, "copy": copy.model_dump(), "spotlight_pin": os.getenv("INJURY_SPOTLIGHT")}
    (weeks_dir / f"week{issue_week(data)}.json").write_text(json.dumps(snapshot, indent=1))
    (out / "data.json").write_text(json.dumps(data, indent=1))

    snapshots = {}
    for f in weeks_dir.glob("week*.json"):
        snap = json.loads(f.read_text())
        snapshots[issue_week(snap["data"])] = snap
    archive = sorted(snapshots, reverse=True)

    # HTML pages are derived from snapshots — drop any without one (e.g. pre-snapshot builds).
    for f in weeks_dir.glob("week*.html"):
        if f.with_suffix(".json").name not in {f"week{n}.json" for n in snapshots}:
            f.unlink()

    env = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
    template = env.get_template("index.html")
    for n, snap in snapshots.items():
        ctx = _context(snap["data"], SiteCopy.model_validate(snap["copy"]), snap.get("spotlight_pin"))
        (weeks_dir / f"week{n}.html").write_text(template.render(**ctx, archive=archive, root="../"))

    ctx = _context(data, copy, snapshot["spotlight_pin"])
    (out / "index.html").write_text(template.render(**ctx, archive=archive, root=""))
    return out / "index.html"
