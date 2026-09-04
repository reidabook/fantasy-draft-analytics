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

SEASON = 2026


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
        league_id = league_data.get("league_id", "")
        league_name = league_data.get("name", league_id)
        filename = f"sleeper_{league_id}.json"

        # Preserve any previously-saved/manually-edited pick position and draft_id
        # as the fallback — Sleeper only assigns draft_order once the commissioner
        # randomizes slots, so a brand-new or not-yet-randomized draft has none.
        existing = load_config(filename)
        user_settings = {
            "my_pick_position": existing.draft.my_pick_position if existing else 6,
            "draft_id": existing.draft.draft_id if existing else "",
        }

        try:
            drafts = fetcher.sleeper_get_league_drafts(league_id)
        except Exception as e:
            drafts = []
            log(f"  Could not fetch draft info for {league_name}: {e}", log_cb)

        if drafts:
            draft = drafts[0]
            if draft.get("draft_id"):
                user_settings["draft_id"] = draft["draft_id"]

            draft_order = draft.get("draft_order")
            if draft_order and user_id in draft_order:
                user_settings["my_pick_position"] = draft_order[user_id]
                log(f"  {league_name}: draft position #{draft_order[user_id]}", log_cb)
            else:
                log(
                    f"  {league_name}: Sleeper hasn't set the draft order yet "
                    f"(commissioner randomizes it pre-draft) — keeping pick "
                    f"#{user_settings['my_pick_position']}; re-import once it's set",
                    log_cb,
                )

        config = build_league_config_from_sleeper(league_data, user_settings=user_settings)
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


def fetch_espn_projections(config: LeagueConfig, log_cb: Optional[Callable] = None) -> int:
    """
    Fetch league-scored projections directly from ESPN for an ESPN league.
    Used as a fallback when Sleeper hasn't published full-season projections yet
    (e.g. pre-kickoff) — ESPN's own projected_total_points is already computed
    under this league's actual scoring settings, so it's used in place of ADP too.
    """
    espn_s2 = os.getenv("ESPN_S2", "")
    swid = os.getenv("ESPN_SWID", "")

    log(f"Fetching ESPN player pool for league {config.league_id}...", log_cb)
    espn_league = fetcher.espn_get_league(
        league_id=int(config.league_id), year=config.season, espn_s2=espn_s2, swid=swid,
    )
    raw_pool = fetcher.espn_get_full_player_pool(espn_league)

    players = transformer.normalize_espn_players(raw_pool)
    cache.upsert_players(players)
    log(f"Cached {len(players)} players from ESPN", log_cb)

    projs = transformer.normalize_espn_projections(raw_pool, season=config.season)
    cache.upsert_projections(projs)
    log(f"Cached {len(projs)} projections from ESPN", log_cb)

    # Only write the proxy ADP if no real ADP source (e.g. a merged FantasyPros
    # CSV) already exists — the proxy is just points-rank restated as "ADP",
    # so it would win compute_vbd's min()-across-sources and silently override
    # real market ADP with this circular one on every re-run.
    existing_sources = {a["source"] for a in cache.get_adp(season=config.season)}
    if existing_sources - {"espn_proxy"}:
        log("Real ADP source already present — skipping proxy ADP", log_cb)
    else:
        adp = transformer.normalize_espn_adp_from_projections(projs, season=config.season)
        cache.upsert_adp(adp)
        log(f"Cached {len(adp)} proxy ADP entries (espn_proxy)", log_cb)

    return len(projs)


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

    if not normalized:
        # Sleeper hasn't computed the week=0 season aggregate yet (common
        # pre-kickoff) — build our own season total by summing weekly
        # projections, which are populated well before the aggregate is.
        log("Week=0 season aggregate not published yet — summing weekly projections instead...", log_cb)
        weekly_batch = fetcher.sleeper_get_weekly_projections_batch(season=SEASON)
        season_totals = transformer.aggregate_sleeper_weekly_to_season(weekly_batch)
        normalized = transformer.normalize_sleeper_projections(season_totals, season=SEASON, week=0)

    cache.upsert_projections(normalized)
    cache.mark_fetched("sleeper_projections")
    log(f"Cached {len(normalized)} projections", log_cb)
    return len(normalized)


def import_fantasypros_local(
    stats_csv_path: str,
    bye_csv_path: Optional[str] = None,
    log_cb: Optional[Callable] = None,
) -> dict:
    """
    Ingest a locally-downloaded FantasyPros 'Draft ALL Rankings' CSV export as PPR
    projections + ADP (source="fantasypros_local"), bypassing the live scrape in
    fetch_adp() when FantasyPros blocks it. Matches players by name against the
    already-cached player directory (run fetch_players()/--full first).

    stats_csv_path: the stat-line export (RK, TIERS, PLAYER NAME, TEAM, FANTASYPTS, ...)
    bye_csv_path: optional cheat-sheet export (..., BYE WEEK, UPSIDE, BUST, ...) —
    only its name/team/bye_week columns are used, to backfill players.bye_week.
    """
    players = cache.get_all_players()
    if not players:
        raise ValueError("No players cached — run fetch_players() / prefetch.py --full first")
    name_to_id = {p["name"].lower(): p["id"] for p in players}

    log(f"Parsing local FantasyPros CSV: {stats_csv_path}", log_cb)
    raw = fetcher.fantasypros_parse_local_csv(stats_csv_path)
    proj_rows, adp_rows = transformer.normalize_fantasypros_local(raw, name_to_id, season=SEASON)

    cache.upsert_projections(proj_rows)
    cache.upsert_adp(adp_rows)
    log(f"Cached {len(proj_rows)} projections and {len(adp_rows)} ADP entries (fantasypros_local)", log_cb)

    result = {"projections": len(proj_rows), "adp": len(adp_rows), "bye_weeks": 0}

    if bye_csv_path:
        log(f"Parsing local FantasyPros bye-week CSV: {bye_csv_path}", log_cb)
        bye_raw = fetcher.fantasypros_parse_local_bye_weeks_csv(bye_csv_path)
        bye_weeks = transformer.normalize_fantasypros_bye_weeks(bye_raw, name_to_id)
        cache.upsert_bye_weeks(bye_weeks)
        log(f"Cached {len(bye_weeks)} bye weeks", log_cb)
        result["bye_weeks"] = len(bye_weeks)

    return result


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

        # nflverse's player_stats release only has data through 2024 right now
        # (2025 season stats aren't published there yet) — use the latest
        # actually-available seasons rather than assuming season-1/season-2.
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
