#!/usr/bin/env python3
"""
prefetch.py — CLI data refresh tool for the Fantasy Draft Analytics app.

Usage:
    python prefetch.py --quick     # Daily: projections + ADP (fast, ~30s)
    python prefetch.py --full      # Weekly: players + projections + ADP + nfl_metrics (~5min)
    python prefetch.py --vbd       # Recompute VBD for all saved leagues (no fetch)
    python prefetch.py --full --vbd  # Fetch everything + recompute VBD

After fetching, use --vbd (or pass it alongside --full) to recompute VBD scores
for all saved leagues so the Streamlit app is ready to use immediately.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure the project root is on the path so src.* imports work
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from src.data.pipeline import run_quick, run_full, import_fantasypros_local, SEASON
from src.config.settings import list_saved_leagues, load_config
from src.data.cache import (
    get_all_players,
    get_projections,
    get_adp,
    upsert_vbd_scores,
    get_all_player_notes,
)
from src.analytics.vbd import compute_vbd, vbd_to_db_rows


# ---------------------------------------------------------------------------
# VBD recompute across all saved leagues
# ---------------------------------------------------------------------------

def recompute_all_vbd() -> int:
    """
    Recompute VBD scores for every saved league config.
    Returns number of leagues processed.
    """
    saved = list_saved_leagues()
    if not saved:
        print("  No saved leagues found. Import a league in the app first.")
        return 0

    players = get_all_players(positions=["QB", "RB", "WR", "TE"])
    projs = get_projections(season=SEASON, week=0)
    adp = get_adp(season=SEASON)

    if not players:
        print("  No player data. Run --full first to populate the player directory.")
        return 0
    if not projs:
        print("  No projection data. Run --quick or --full first.")
        return 0

    processed = 0
    for filename in saved:
        config = load_config(filename)
        if not config:
            print(f"  Skipping {filename} (failed to load)")
            continue

        notes = get_all_player_notes(config.league_id)
        try:
            vbd_df = compute_vbd(players, projs, adp, config, notes)
            db_rows = vbd_to_db_rows(vbd_df, config.league_id, config.season, config.scoring.type)
            upsert_vbd_scores(db_rows)
            print(f"  {config.league_name}: {len(db_rows)} players ranked")
            processed += 1
        except Exception as e:
            print(f"  {config.league_name}: VBD failed — {e}")

    return processed


# ---------------------------------------------------------------------------
# Progress printer
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fantasy Draft Analytics — data prefetch CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--quick",
        action="store_true",
        help="Daily refresh: projections + ADP only (respects 24h cache)",
    )
    mode_group.add_argument(
        "--full",
        action="store_true",
        help="Weekly refresh: players + projections + ADP + nfl_data_py metrics",
    )

    parser.add_argument(
        "--vbd",
        action="store_true",
        help="Recompute VBD rankings for all saved leagues after fetching",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass cache freshness checks and re-download everything",
    )
    parser.add_argument(
        "--local-csv",
        metavar="PATH",
        help="Import a locally-downloaded FantasyPros 'Draft ALL Rankings' CSV "
             "(stat-line export) as PPR projections + ADP, bypassing the live scrape",
    )
    parser.add_argument(
        "--local-bye-csv",
        metavar="PATH",
        help="Optional companion FantasyPros cheat-sheet CSV export (has a BYE WEEK "
             "column) to backfill players.bye_week. Only used alongside --local-csv",
    )

    args = parser.parse_args()

    if not args.quick and not args.full and not args.vbd and not args.local_csv:
        parser.print_help()
        print("\nError: specify at least one of --quick, --full, --vbd, or --local-csv")
        sys.exit(1)

    print("=" * 60)
    print("Fantasy Draft Analytics — Data Prefetch")
    print("=" * 60)

    # Force-expire caches if requested
    if args.force:
        from src.data import cache as _cache
        _log("--force: clearing cache freshness markers")
        for key in ["sleeper_players", "sleeper_projections", "adp", "nfl_metrics"]:
            _cache._set_meta(key, None)  # reset timestamp so is_stale returns True

    # ---------------------------------------------------------------------------
    # Fetch
    # ---------------------------------------------------------------------------

    if args.full:
        _log("Starting FULL refresh (players + projections + ADP + nfl_metrics)...")
        t0 = time.time()
        results = run_full(log_cb=_log)
        elapsed = time.time() - t0

        print()
        print("Full refresh results:")
        for key, count in results.items():
            status = f"{count} rows" if count else "skipped (cache fresh)"
            print(f"  {key:<20} {status}")
        print(f"  Elapsed: {elapsed:.1f}s")

    elif args.quick:
        _log("Starting QUICK refresh (projections + ADP)...")
        t0 = time.time()
        results = run_quick(log_cb=_log)
        elapsed = time.time() - t0

        print()
        print("Quick refresh results:")
        for key, count in results.items():
            status = f"{count} rows" if count else "skipped (cache fresh)"
            print(f"  {key:<20} {status}")
        print(f"  Elapsed: {elapsed:.1f}s")

    # ---------------------------------------------------------------------------
    # Local FantasyPros CSV import
    # ---------------------------------------------------------------------------

    if args.local_csv:
        _log(f"Importing local FantasyPros CSV: {args.local_csv}")
        t0 = time.time()
        try:
            result = import_fantasypros_local(args.local_csv, args.local_bye_csv, log_cb=_log)
            elapsed = time.time() - t0
            print()
            print("Local CSV import results:")
            for key, count in result.items():
                print(f"  {key:<20} {count} rows")
            print(f"  Elapsed: {elapsed:.1f}s")
        except Exception as e:
            print(f"  Local CSV import failed: {e}")
            sys.exit(1)

    # ---------------------------------------------------------------------------
    # VBD recompute
    # ---------------------------------------------------------------------------

    if args.vbd or args.full or args.local_csv:
        print()
        _log("Recomputing VBD scores for all saved leagues...")
        n = recompute_all_vbd()
        if n > 0:
            print(f"  VBD recomputed for {n} league(s)")
        print()

    print("=" * 60)
    print("Done. Launch the app: streamlit run app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
