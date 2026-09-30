#!/usr/bin/env python3
"""
build_site.py — Build (and optionally publish) the weekly league site.

Pulls ESPN data, has Claude write the headline/recaps/round-up (cached per
week in data/site/), renders a static site, and with --publish commits +
pushes it to the public GitHub Pages repo at SITE_REPO_PATH.

Usage:
    python build_site.py                          # most recently completed week -> SITE_REPO_PATH
    python build_site.py --week 3 --no-ai --out /tmp/site
    python build_site.py --week 3 --refresh-copy  # regenerate Claude copy
    python build_site.py --publish
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from src.data.fetcher import espn_get_league
from src.data.pipeline import SEASON
from src.site.collect import collect_league_data
from src.site.render import render_site
from src.site.writer import get_copy

DEFAULT_SITE_REPO = str(Path(__file__).resolve().parent.parent / "ticerado-bowl")
SITE_URL = os.getenv("SITE_URL", "https://reidabook.github.io/ticerado-bowl/")


def publish(repo: Path, week: int) -> None:
    """Commit + push the rendered site. No-op commit (nothing changed) is fine."""
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)  # noqa: E731
    git("add", "-A")
    if subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--quiet"]).returncode == 0:
        print("Site unchanged — nothing to publish.")
        return
    git("commit", "-m", f"Week {week} update")
    git("push")
    print(f"Published: {SITE_URL}")


def build_site(week: Optional[int] = None, use_ai: bool = True, refresh_copy: bool = False,
               out: Optional[str] = None, do_publish: bool = False, league=None) -> Path:
    if league is None:
        league = espn_get_league(int(os.environ["ESPN_LEAGUE_ID"]), year=SEASON,
                                 espn_s2=os.environ["ESPN_S2"], swid=os.environ["ESPN_SWID"])
    week = week if week is not None else max(1, league.current_week - 1)
    fake_team_name = os.getenv("FAKE_TEAM_NAME", "Fake team")
    out_dir = Path(out or os.getenv("SITE_REPO_PATH", DEFAULT_SITE_REPO))

    print(f"Collecting week {week} data...")
    data = collect_league_data(league, week, fake_team_name)
    print("Writing copy with Claude..." if use_ai else "Writing templated copy (no AI)...")
    copy = get_copy(data, use_ai=use_ai, refresh=refresh_copy)
    index = render_site(data, copy, out_dir)
    print(f"Rendered {index}")

    if do_publish:
        publish(out_dir, week)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", type=int, default=None, help="Week to recap (default: most recently completed)")
    parser.add_argument("--no-ai", action="store_true", help="Templated copy instead of Claude")
    parser.add_argument("--refresh-copy", action="store_true", help="Ignore cached Claude copy for this week")
    parser.add_argument("--out", default=None, help=f"Output dir (default: SITE_REPO_PATH or {DEFAULT_SITE_REPO})")
    parser.add_argument("--publish", action="store_true", help="git commit + push the output dir")
    args = parser.parse_args()
    build_site(args.week, use_ai=not args.no_ai, refresh_copy=args.refresh_copy, out=args.out, do_publish=args.publish)


if __name__ == "__main__":
    main()
