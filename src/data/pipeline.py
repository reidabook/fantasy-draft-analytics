"""
Pipeline orchestration: fetch → transform → cache.
Used by both prefetch.py CLI and the in-app "Quick Refresh" button.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from dotenv import load_dotenv

load_dotenv()

from src.data import cache, fetcher, transformer
from src.config.settings import (
    LeagueConfig,
    build_league_config_from_sleeper,
    load_config,
    save_config,
    list_saved_leagues,
)

SEASON = 2025


def log(msg: str, callback: Optional[Callable] = None) -> None:
    if callback:
        callback(msg)
    else:
        print(msg)


# ---------------------------------------------------------------------------
# Sleeper import
# ---------------------------------------------------------------------------

def import_sleeper_league(username: str, log_cb: Optional[Callable] = None) -> list[LeagueConfig]:
    """
    Full import of all Sleeper leagues for a username.
    Returns list of LeagueConfig objects (also saved to config/).
    """
    log(f"Fetching Sleeper user: {username}", log_cb)
    user = fetcher.sleeper_get_user(username)
    if not user or "user_id" not in user:
        raise ValueError(f"Sleeper user '{username}' not found")

    user_id = user["user_id"]
    log(f"User ID: {user_id}", log_cb)

    leagues = fetcher.sleeper_get_leagues(user_id, SEASON)
    log(f"Found {len(leagues)} leagues", log_cb)

    configs = []
    for league_data in leagues:
        config = build_league_config_from_sleeper(league_data, user_settings={})
        filename = f"sleeper_{config.league_id}.json"
        save_config(config, filename)
        configs.append(config)
        log(f"  Saved: {config.league_name} ({config.league_id})", log_cb)

    return configs


def import_espn_league(log_cb: Optional[Callable] = None) -> Optional[LeagueConfig]:
    """Import ESPN league from .env credentials."""
    from src.config.settings import build_league_config_from_espn

    league_id = os.getenv("ESPN_LEAGUE_ID")
    espn_s2 = os.getenv("ESPN_S2", "")
    swid = os.getenv("ESPN_SWID", "")

    if not league_id:
        raise ValueError("ESPN_LEAGUE_ID not set in .env")

    log(f"Connecting to ESPN league {league_id}...", log_cb)
    try:
        espn_league = fetcher.espn_get_league(
            league_id=int(league_id),
            year=SEASON,
            espn_s2=espn_s2,
            swid=swid,
        )
        config = build_league_config_from_espn(espn_league, user_settings={})
        filename = f"espn_{config.league_id}.json"
        save_config(config, filename)
        log(f"Saved ESPN: {config.league_name}", log_cb)
        return config
    except Exception as e:
        raise RuntimeError(f"ESPN import failed: {e}")


# ---------------------------------------------------------------------------
# Player directory + projections
# ---------------------------------------------------------------------------

def fetch_players(log_cb: Optional[Callable] = None) -> int:
    """Download and cache Sleeper player directory. Returns count."""
    if not cache.is_stale("sleeper_players", max_age_hours=168):  # weekly
        log("Players cache is fresh (< 7 days), skipping", log_cb)
        return 0

    log("Downloading Sleeper player directory...", log_cb)
    raw = fetcher.sleeper_get_all_players()
    normalized = transformer.normalize_sleeper_players(raw)
    cache.upsert_players(normalized)
    cache.mark_fetched("sleeper_players")
    log(f"Cached {len(normalized)} players", log_cb)
    return len(normalized)


def fetch_projections(log_cb: Optional[Callable] = None) -> int:
    """Download and cache Sleeper full-season projections. Returns count."""
    if not cache.is_stale("sleeper_projections", max_age_hours=24):
        log("Projections cache is fresh (< 24h), skipping", log_cb)
        return 0

    log("Downloading Sleeper projections...", log_cb)
    raw = fetcher.sleeper_get_projections(season=SEASON, week=0)
    normalized = transformer.normalize_sleeper_projections(raw, season=SEASON, week=0)
    cache.upsert_projections(normalized)
    cache.mark_fetched("sleeper_projections")
    log(f"Cached {len(normalized)} projections", log_cb)
    return len(normalized)


def fetch_adp(log_cb: Optional[Callable] = None) -> int:
    """Fetch FantasyPros ADP; fall back to Sleeper proxy if blocked."""
    if not cache.is_stale("adp", max_age_hours=24):
        log("ADP cache is fresh (< 24h), skipping", log_cb)
        return 0

    # Build name → player_id map for resolution
    players = cache.get_all_players()
    name_to_id = {p["name"].lower(): p["id"] for p in players}

    log("Fetching FantasyPros ADP (PPR)...", log_cb)
    raw = fetcher.fantasypros_get_adp(scoring_type="PPR", season=SEASON)

    if raw:
        normalized = transformer.normalize_fantasypros_adp(raw, SEASON, name_to_id)
        cache.upsert_adp(normalized)
        log(f"Cached {len(normalized)} ADP entries (FantasyPros)", log_cb)
    else:
        log("FantasyPros blocked — using Sleeper projections as proxy ADP", log_cb)
        projs = cache.get_projections(season=SEASON, week=0)
        normalized = transformer.normalize_sleeper_adp_from_projections(projs, SEASON)
        cache.upsert_adp(normalized)
        log(f"Cached {len(normalized)} ADP entries (Sleeper proxy)", log_cb)

    cache.mark_fetched("adp")
    return len(normalized)


def fetch_nfl_metrics(log_cb: Optional[Callable] = None) -> int:
    """Download nfl_data_py seasonal metrics and snap counts."""
    if not cache.is_stale("nfl_metrics", max_age_hours=168):
        log("NFL metrics cache is fresh (< 7 days), skipping", log_cb)
        return 0

    log("Downloading nfl_data_py ID map...", log_cb)
    try:
        ids_df = fetcher.nfldata_import_ids()
        sleeper_to_gsis, name_to_sleeper = transformer.build_id_map(ids_df)

        log("Downloading seasonal stats (2023-2024)...", log_cb)
        seasons = [2023, 2024]
        seasonal_df = fetcher.nfldata_import_seasonal(seasons)

        all_metrics = []
        for season in seasons:
            metrics = transformer.normalize_seasonal_metrics(seasonal_df, sleeper_to_gsis, season)
            all_metrics.extend(metrics)

        cache.upsert_advanced_metrics(all_metrics)
        cache.mark_fetched("nfl_metrics")
        log(f"Cached {len(all_metrics)} advanced metric rows", log_cb)
        return len(all_metrics)
    except Exception as e:
        log(f"nfl_data_py fetch failed: {e}", log_cb)
        return 0


# ---------------------------------------------------------------------------
# Pipeline entry points
# ---------------------------------------------------------------------------

def run_quick(log_cb: Optional[Callable] = None) -> dict:
    """
    Quick daily refresh:
    - Sleeper projections (24h cache)
    - ADP (24h cache)
    - Trending news (always)
    Does NOT re-download players or nfl_data_py (weekly).
    """
    results = {}
    try:
        results["projections"] = fetch_projections(log_cb)
    except Exception as e:
        log(f"Projections failed: {e}", log_cb)
        results["projections"] = 0

    try:
        results["adp"] = fetch_adp(log_cb)
    except Exception as e:
        log(f"ADP failed: {e}", log_cb)
        results["adp"] = 0

    log("Quick refresh complete", log_cb)
    return results


def run_full(log_cb: Optional[Callable] = None) -> dict:
    """
    Full weekly refresh:
    - Players directory (weekly cache)
    - Projections
    - ADP
    - nfl_data_py metrics
    """
    results = {}

    try:
        results["players"] = fetch_players(log_cb)
    except Exception as e:
        log(f"Players failed: {e}", log_cb)
        results["players"] = 0

    try:
        results["projections"] = fetch_projections(log_cb)
    except Exception as e:
        log(f"Projections failed: {e}", log_cb)
        results["projections"] = 0

    try:
        results["adp"] = fetch_adp(log_cb)
    except Exception as e:
        log(f"ADP failed: {e}", log_cb)
        results["adp"] = 0

    try:
        results["nfl_metrics"] = fetch_nfl_metrics(log_cb)
    except Exception as e:
        log(f"NFL metrics failed: {e}", log_cb)
        results["nfl_metrics"] = 0

    log("Full refresh complete", log_cb)
    return results
