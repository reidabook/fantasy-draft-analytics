#!/usr/bin/env python3
"""
weekly_update.py — Weekly median-score override + high-score payout report.

Fetches this week's ESPN scores, computes the league median (excluding the
"Fake team"), overrides the Fake team's score to that median via ESPN's
commissioner tool (Playwright), and emails a report with the median, the
override's success/failure, and the week's high scorer (for the Venmo
payout). The override failing never blocks the email — you'll get the
median and payout winner either way.

Usage:
    python weekly_update.py                  # most recently completed week
    python weekly_update.py --week 3
    python weekly_update.py --week 3 --dry-run   # fills the ESPN form, never submits
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from src.data.fetcher import espn_get_league, espn_get_weekly_scores, espn_get_fake_team_opponent, espn_get_team_managers
from src.data.pipeline import SEASON
from src.weekly.payout import compute_median, find_high_scorer, find_high_scorers, parse_venmo_handles, payout_line
from src.weekly.commish_override import override_fake_team_score, NotConfiguredError, NoSavedSessionError
from src.weekly.notify import send_weekly_report
from src.weekly.imessage import build_group_text
from build_site import SITE_URL, build_site

PENDING_GROUP_TEXT_PATH = "logs/pending_group_text.txt"
# The site link goes out as its own text, after the recap.
PENDING_GROUP_LINK_PATH = "logs/pending_group_link.txt"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--week", type=int, default=None, help="NFL week to process (default: most recently completed)")
    parser.add_argument("--dry-run", action="store_true", help="Fill the ESPN override form but don't submit")
    args = parser.parse_args()

    league_id = int(os.environ["ESPN_LEAGUE_ID"])
    espn_s2 = os.environ["ESPN_S2"]
    swid = os.environ["ESPN_SWID"]
    fake_team_name = os.getenv("FAKE_TEAM_NAME", "Fake team")
    # ^ espn_s2/swid are only used for the read-only ESPN API below — the
    # Playwright override step reuses a saved browser session instead, see
    # src/weekly/commish_override.py.
    fake_team_id = int(os.environ["FAKE_TEAM_ID"])

    league = espn_get_league(league_id, year=SEASON, espn_s2=espn_s2, swid=swid)
    week = args.week if args.week is not None else max(1, league.current_week - 1)

    print(f"Fetching week {week} scores...")
    scores = espn_get_weekly_scores(league, week=week)

    median = compute_median(scores, fake_team_name)
    high_scorer, high_score = find_high_scorer(scores, fake_team_name)
    print(f"Median (excl. {fake_team_name}): {median:.2f}")
    print(f"High scorer: {high_scorer} ({high_score:.2f})")

    # Venmo pay link for the high scorer — regular season only, None in the playoffs.
    team_to_manager = espn_get_team_managers(league)
    winners, _ = find_high_scorers(scores, fake_team_name)
    payout = payout_line(
        week=week,
        reg_season_weeks=league.settings.reg_season_count,
        winners=winners,
        high_score=high_score,
        team_to_manager=team_to_manager,
        handles=parse_venmo_handles(os.getenv("VENMO_HANDLES")),
        amount=float(os.getenv("HIGH_SCORE_PAYOUT") or 5),
    )
    print(payout or "No high score payout (regular season over).")

    override_ok = False
    error = None
    try:
        override_fake_team_score(
            league_id=league_id,
            season=SEASON,
            fake_team_name=fake_team_name,
            fake_team_id=fake_team_id,
            current_score=scores[fake_team_name],
            target_score=median,
            week=week,
            dry_run=args.dry_run,
            verify_fn=(lambda: espn_get_weekly_scores(league, week=week)[fake_team_name]) if not args.dry_run else None,
        )
        override_ok = True
        print(f"{'[dry-run] would set' if args.dry_run else 'Set'} {fake_team_name} to {median:.2f}")
    except (NotConfiguredError, NoSavedSessionError) as e:
        error = str(e)
        print(f"Override skipped: {e}")
    except Exception as e:
        error = str(e)
        print(f"Override FAILED: {e}")

    if not args.dry_run:
        send_weekly_report(
            week=week,
            scores=scores,
            median=median,
            fake_team_name=fake_team_name,
            override_ok=override_ok,
            high_scorer=high_scorer,
            high_score=high_score,
            error=error,
            payout_line=payout,
        )
        print("Report emailed.")

        group_chat_id = os.getenv("IMESSAGE_GROUP_CHAT_ID")
        if group_chat_id:
            fake_opponent_info = espn_get_fake_team_opponent(league, week, fake_team_name)
            text = build_group_text(
                week=week,
                median=median,
                fake_team_name=fake_team_name,
                override_ok=override_ok,
                high_scorer=high_scorer,
                high_score=high_score,
                scores=scores,
                fake_opponent=fake_opponent_info[0] if fake_opponent_info else None,
                fake_opponent_score=fake_opponent_info[1] if fake_opponent_info else None,
                team_to_manager=team_to_manager,
                sender=os.getenv("GROUP_TEXT_SENDER") or None,
            )
            os.makedirs(os.path.dirname(PENDING_GROUP_TEXT_PATH), exist_ok=True)
            with open(PENDING_GROUP_TEXT_PATH, "w") as f:
                f.write(text)
            with open(PENDING_GROUP_LINK_PATH, "w") as f:
                f.write(SITE_URL)
            print()
            print("GROUP TEXTS (not sent yet — review, then run send_group_text.py to send both):")
            print("-" * 60)
            print(text)
            print("-" * 60)
            print(SITE_URL)
            print("-" * 60)

        # Rebuild + publish the league site. Refetches the league rather than
        # reusing `league`, whose records predate the override (which can flip
        # the Fake team's result). Never blocks the email/group text above.
        try:
            build_site(week, do_publish=True)
        except Exception as e:
            print(f"Site build/publish FAILED: {e}")
    else:
        print("(dry-run: skipping email, group text and site)")


if __name__ == "__main__":
    main()
