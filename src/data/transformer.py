"""
Transform raw API data → normalized DataFrames and DB-ready dicts.
All functions accept raw fetcher output and return lists of dicts
suitable for passing directly to cache.py upsert functions.
"""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K"}
OFFENSIVE_POSITIONS = {"QB", "RB", "WR", "TE"}


# ---------------------------------------------------------------------------
# Player directory normalization
# ---------------------------------------------------------------------------

def normalize_sleeper_players(raw: Dict[str, dict]) -> List[dict]:
    """
    Convert Sleeper /players/nfl response → list of normalized player dicts.
    Filters to skill positions only.
    """
    players = []
    for sleeper_id, p in raw.items():
        position = p.get("position", "")
        if position not in SKILL_POSITIONS:
            continue
        players.append({
            "id": sleeper_id,  # use sleeper_id as canonical id
            "name": _clean_name(p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}"),
            "position": position,
            "team": p.get("team", "FA"),
            "age": p.get("age"),
            "depth_chart_pos": p.get("depth_chart_position"),
            "injury_status": p.get("injury_status"),
            "gsis_id": p.get("gsis_id"),
            "sleeper_id": sleeper_id,
            "espn_id": str(p.get("espn_id", "")) if p.get("espn_id") else None,
        })
    return players


def _clean_name(name: str) -> str:
    return " ".join(name.strip().split())


# ---------------------------------------------------------------------------
# Projections normalization
# ---------------------------------------------------------------------------

def normalize_sleeper_projections(
    raw: Dict[str, dict],
    season: int,
    week: int = 0,
    scoring_config=None,
) -> List[dict]:
    """
    Convert Sleeper projections dict → list of projection dicts.
    Computes pts_ppr, pts_half_ppr, pts_std from stat components.
    """
    rows = []
    for player_id, stats in raw.items():
        if not stats:
            continue
        pts_ppr = _compute_pts(stats, rec_pts=1.0)
        pts_half = _compute_pts(stats, rec_pts=0.5)
        pts_std = _compute_pts(stats, rec_pts=0.0)
        if pts_ppr == 0 and pts_half == 0 and pts_std == 0:
            continue
        rows.append({
            "player_id": player_id,
            "season": season,
            "week": week,
            "source": "sleeper",
            "pts_ppr": round(pts_ppr, 2),
            "pts_half_ppr": round(pts_half, 2),
            "pts_std": round(pts_std, 2),
            "pass_yd": stats.get("pass_yd", 0),
            "pass_td": stats.get("pass_td", 0),
            "rush_yd": stats.get("rush_yd", 0),
            "rush_td": stats.get("rush_td", 0),
            "rec": stats.get("rec", 0),
            "rec_yd": stats.get("rec_yd", 0),
            "rec_td": stats.get("rec_td", 0),
        })
    return rows


_WEEKLY_SUM_FIELDS = {
    "pass_yd": "pass_yd", "pass_td": "pass_td", "pass_int": "int",
    "rush_yd": "rush_yd", "rush_td": "rush_td",
    "rec": "rec", "rec_yd": "rec_yd", "rec_td": "rec_td",
    "fum_lost": "fum_lost",
}
_WEEKLY_2PT_FIELDS = ["pass_2pt", "rush_2pt", "rec_2pt"]


def aggregate_sleeper_weekly_to_season(weekly_batch: Dict[int, Dict[str, dict]]) -> Dict[str, dict]:
    """
    Sum per-week Sleeper projections (from sleeper_get_weekly_projections_batch)
    into a season-total stats dict per player, in the same field shape
    normalize_sleeper_projections()/_compute_pts() expect (note: Sleeper's
    weekly payload uses 'pass_int' and split pass_2pt/rush_2pt/rec_2pt —
    remapped here to the unified 'int'/'2pt' keys _compute_pts reads).
    """
    totals: Dict[str, dict] = {}
    for week_data in weekly_batch.values():
        for player_id, stats in week_data.items():
            if not stats:
                continue
            bucket = totals.setdefault(player_id, {})
            for src_key, dst_key in _WEEKLY_SUM_FIELDS.items():
                bucket[dst_key] = bucket.get(dst_key, 0) + stats.get(src_key, 0)
            two_pt = sum(stats.get(k, 0) for k in _WEEKLY_2PT_FIELDS)
            bucket["2pt"] = bucket.get("2pt", 0) + two_pt
    return totals


def _compute_pts(stats: dict, rec_pts: float = 1.0) -> float:
    """Compute fantasy points from stat dict with configurable reception scoring."""
    pts = 0.0
    pts += stats.get("pass_yd", 0) * 0.04
    pts += stats.get("pass_td", 0) * 4.0
    pts += stats.get("rush_yd", 0) * 0.1
    pts += stats.get("rush_td", 0) * 6.0
    pts += stats.get("rec", 0) * rec_pts
    pts += stats.get("rec_yd", 0) * 0.1
    pts += stats.get("rec_td", 0) * 6.0
    pts += stats.get("fum_lost", 0) * -2.0
    pts += stats.get("int", 0) * -2.0
    pts += stats.get("2pt", 0) * 2.0
    return pts


def compute_pts_with_config(stats: dict, scoring) -> float:
    """Compute fantasy points using a ScoringConfig object."""
    pts = 0.0
    pts += stats.get("pass_yd", 0) * scoring.passing_yard
    pts += stats.get("pass_td", 0) * scoring.pass_td
    pts += stats.get("rush_yd", 0) * scoring.rushing_yard
    pts += stats.get("rush_td", 0) * scoring.rush_td
    pts += stats.get("rec", 0) * scoring.reception
    pts += stats.get("rec_yd", 0) * scoring.receiving_yard
    pts += stats.get("rec_td", 0) * scoring.rec_td
    pts += stats.get("fum_lost", 0) * scoring.fumble_lost
    pts += stats.get("int", 0) * scoring.interception
    pts += stats.get("2pt", 0) * scoring.two_point_conversion
    return pts


# ---------------------------------------------------------------------------
# FantasyPros local CSV normalization
# ---------------------------------------------------------------------------

def normalize_fantasypros_local(
    raw: List[dict],
    player_id_map: Dict[str, str],
    season: int,
    source: str = "fantasypros_local",
) -> Tuple[List[dict], List[dict]]:
    """
    Convert fetcher.fantasypros_parse_local_csv() output → (projection rows, adp rows).
    player_id_map: lower-case player name → our internal player id (e.g. espn_12345).
    Points are computed with the same formula normalize_sleeper_projections uses
    (0.04/pass-yd, 0.1/rush-yd, 0.1/rec-yd, 4/pass-td, 6/rush-td, 6/rec-td), which
    matches this league's actual scoring exactly except for reception value.
    Unmatched names are skipped rather than guessed at.

    QBs are the exception: this CSV export has no interception/fumble columns,
    so recomputing from the raw stat line silently drops turnover penalties —
    a ~9-point average (up to 22) undercount of how bad that is became visible
    comparing the recompute against FantasyPros' own published FANTASYPTS
    total for the same row. Since reception value never applies to a QB's
    score anyway, QBs use FantasyPros' own total directly (all three
    scoring-type columns get the same value, same as normalize_espn_projections
    does when PPR doesn't affect the number) instead of the partial recompute.
    """
    suffix_stripped_map = {
        _strip_suffix(k): v for k, v in player_id_map.items()
    }

    proj_rows = []
    adp_rows = []
    unmatched = []
    for p in raw:
        name_key = p["name"].lower()
        player_id = (
            player_id_map.get(name_key)
            or suffix_stripped_map.get(_strip_suffix(name_key))
            or _fuzzy_lookup(name_key, player_id_map)
        )
        if not player_id:
            unmatched.append(p["name"])
            continue

        stats = {
            "pass_yd": p["pass_yd"], "pass_td": p["pass_td"],
            "rush_yd": p["rush_yd"], "rush_td": p["rush_td"],
            "rec": p["rec"], "rec_yd": p["rec_yd"], "rec_td": p["rec_td"],
        }
        is_qb = p["pass_yd"] > 0
        if is_qb:
            pts_ppr = pts_half = pts_std = round(p.get("fantasy_pts", 0.0), 2)
        else:
            pts_ppr = round(_compute_pts(stats, rec_pts=1.0), 2)
            pts_half = round(_compute_pts(stats, rec_pts=0.5), 2)
            pts_std = round(_compute_pts(stats, rec_pts=0.0), 2)
        if pts_ppr == 0 and pts_half == 0 and pts_std == 0:
            continue

        proj_rows.append({
            "player_id": player_id,
            "season": season,
            "week": 0,
            "source": source,
            "pts_ppr": pts_ppr,
            "pts_half_ppr": pts_half,
            "pts_std": pts_std,
            "pass_yd": stats["pass_yd"], "pass_td": stats["pass_td"],
            "rush_yd": stats["rush_yd"], "rush_td": stats["rush_td"],
            "rec": stats["rec"], "rec_yd": stats["rec_yd"], "rec_td": stats["rec_td"],
        })
        adp_rows.append({
            "player_id": player_id,
            "season": season,
            "source": source,
            "adp_overall": float(p["rank"]),
            "adp_ppr": float(p["rank"]),
            "adp_half_ppr": float(p["rank"]),
            "adp_std": float(p["rank"]),
        })

    if unmatched:
        print(f"  fantasypros_local: {len(unmatched)} unmatched names (skipped): {unmatched[:10]}{'...' if len(unmatched) > 10 else ''}")

    return proj_rows, adp_rows


def normalize_fantasypros_bye_weeks(raw: List[dict], player_id_map: Dict[str, str]) -> Dict[str, int]:
    """
    Convert fetcher.fantasypros_parse_local_bye_weeks_csv() output → {player_id: bye_week},
    ready for cache.upsert_bye_weeks(). Same name-matching strategy as normalize_fantasypros_local.
    """
    suffix_stripped_map = {_strip_suffix(k): v for k, v in player_id_map.items()}

    bye_weeks: Dict[str, int] = {}
    unmatched = []
    for p in raw:
        name_key = p["name"].lower()
        player_id = (
            player_id_map.get(name_key)
            or suffix_stripped_map.get(_strip_suffix(name_key))
            or _fuzzy_lookup(name_key, player_id_map)
        )
        if not player_id:
            unmatched.append(p["name"])
            continue
        bye_weeks[player_id] = p["bye_week"]

    if unmatched:
        print(f"  fantasypros_bye_weeks: {len(unmatched)} unmatched names (skipped): {unmatched[:10]}{'...' if len(unmatched) > 10 else ''}")

    return bye_weeks


# ---------------------------------------------------------------------------
# ESPN player pool normalization
# ---------------------------------------------------------------------------

def normalize_espn_players(raw: List[dict]) -> List[dict]:
    """Convert espn_get_full_player_pool() output → normalized player dicts."""
    players = []
    for p in raw:
        position = p.get("position", "")
        if position not in SKILL_POSITIONS:
            continue
        players.append({
            "id": f"espn_{p['espn_id']}",
            "name": _clean_name(p.get("name", "")),
            "position": position,
            "team": p.get("team") or "FA",
            "age": None,
            "depth_chart_pos": None,
            "injury_status": p.get("injury_status") if isinstance(p.get("injury_status"), str) else None,
            "gsis_id": None,
            "sleeper_id": None,
            "espn_id": str(p["espn_id"]),
        })
    return players


def normalize_espn_projections(raw: List[dict], season: int) -> List[dict]:
    """
    Convert espn_get_full_player_pool() output → projection rows.
    projected_total_points is already scored under the league's real settings by
    espn_api, so it's used as-is for whichever scoring column the league needs;
    the other two columns are filled with the same value as a reasonable proxy
    (not accurate if this data is later reused for a differently-scored league).
    """
    rows = []
    for p in raw:
        position = p.get("position", "")
        if position not in SKILL_POSITIONS:
            continue
        pts = float(p.get("projected_total_points", 0.0) or 0.0)
        if pts <= 0:
            continue
        rows.append({
            "player_id": f"espn_{p['espn_id']}",
            "season": season,
            "week": 0,
            "source": "espn",
            "pts_ppr": pts,
            "pts_half_ppr": pts,
            "pts_std": pts,
            "pass_yd": 0, "pass_td": 0, "rush_yd": 0, "rush_td": 0,
            "rec": 0, "rec_yd": 0, "rec_td": 0,
        })
    return rows


def normalize_espn_adp_from_projections(projections: List[dict], season: int) -> List[dict]:
    """Proxy ADP from ESPN-scored projection ranking (used when no real ADP source is reachable)."""
    sorted_proj = sorted(projections, key=lambda x: x.get("pts_half_ppr", 0), reverse=True)
    rows = []
    for rank, proj in enumerate(sorted_proj, 1):
        rows.append({
            "player_id": proj["player_id"],
            "season": season,
            "source": "espn_proxy",
            "adp_overall": float(rank),
            "adp_ppr": float(rank),
            "adp_half_ppr": float(rank),
            "adp_std": float(rank),
        })
    return rows


# ---------------------------------------------------------------------------
# ADP normalization
# ---------------------------------------------------------------------------

def normalize_fantasypros_adp(raw: List[dict], season: int, player_id_map: Dict[str, str]) -> List[dict]:
    """
    Convert FantasyPros ADP list → DB-ready dicts with player_id resolved.
    player_id_map: dict mapping lower-case player name → sleeper player_id
    """
    rows = []
    for rank, p in enumerate(raw, 1):
        name = p.get("name", "").lower()
        player_id = player_id_map.get(name) or _fuzzy_lookup(name, player_id_map)
        if not player_id:
            continue
        adp_val = float(p.get("adp_overall", rank))
        rows.append({
            "player_id": player_id,
            "season": season,
            "source": "fantasypros",
            "adp_overall": adp_val,
            "adp_ppr": adp_val,
            "adp_half_ppr": adp_val,
            "adp_std": adp_val,
        })
    return rows


def normalize_sleeper_adp_from_projections(projections: List[dict], season: int) -> List[dict]:
    """
    Create proxy ADP from Sleeper projection rankings (pts_ppr descending).
    Used when FantasyPros is unavailable.
    """
    sorted_proj = sorted(projections, key=lambda x: x.get("pts_ppr", 0), reverse=True)
    rows = []
    for rank, proj in enumerate(sorted_proj, 1):
        rows.append({
            "player_id": proj["player_id"],
            "season": season,
            "source": "sleeper_proxy",
            "adp_overall": float(rank),
            "adp_ppr": float(rank),
            "adp_half_ppr": float(rank),
            "adp_std": float(rank),
        })
    return rows


def _strip_suffix(name: str) -> str:
    """Strip trailing Jr./Sr./II/III/IV suffixes for cross-source name matching."""
    import re
    return re.sub(r"\s+(jr\.?|sr\.?|ii|iii|iv)$", "", name.strip())


def _fuzzy_lookup(name: str, name_map: Dict[str, str], cutoff: float = 0.85) -> Optional[str]:
    """Fuzzy name match fallback."""
    matches = difflib.get_close_matches(name, name_map.keys(), n=1, cutoff=cutoff)
    return name_map[matches[0]] if matches else None


# ---------------------------------------------------------------------------
# ID mapping (nfl_data_py ↔ Sleeper)
# ---------------------------------------------------------------------------

def build_id_map(ids_df: "pd.DataFrame") -> Dict[str, str]:
    """
    Build our canonical player_id → gsis_id map from nfl_data_py import_ids() output.
    Canonical player_id matches whatever players.id convention was used to store the
    player: raw sleeper_id for Sleeper-sourced players, "espn_{espn_id}" for
    ESPN-sourced ones (see normalize_espn_players) — nfl_data_py's id table carries
    both sleeper_id and espn_id directly, so both map to the same gsis_id per player.
    Also returns name → sleeper_id map for ADP fuzzy matching.
    """
    player_to_gsis = {}
    name_to_sleeper = {}

    for _, row in ids_df.iterrows():
        sleeper_id = str(row.get("sleeper_id", "")) if pd.notna(row.get("sleeper_id")) else None
        espn_id = str(int(row["espn_id"])) if pd.notna(row.get("espn_id")) else None
        gsis_id = str(row.get("gsis_id", "")) if pd.notna(row.get("gsis_id")) else None
        name = str(row.get("name", "")).lower().strip() if pd.notna(row.get("name")) else None

        if gsis_id:
            if sleeper_id:
                player_to_gsis[sleeper_id] = gsis_id
            if espn_id:
                player_to_gsis[f"espn_{espn_id}"] = gsis_id
        if name and sleeper_id:
            name_to_sleeper[name] = sleeper_id

    return player_to_gsis, name_to_sleeper


# ---------------------------------------------------------------------------
# nfl_data_py seasonal metrics normalization
# ---------------------------------------------------------------------------

def normalize_seasonal_metrics(
    seasonal_df: "pd.DataFrame",
    player_to_gsis: Dict[str, str],
    season: int,
) -> List[dict]:
    """
    Convert nfl_data_py seasonal DataFrame → advanced_metrics DB rows.
    Maps gsis_id back to our canonical player_id(s) — a single gsis_id can map to
    both a sleeper_id and an "espn_{id}" form (see build_id_map), so one metrics
    row is emitted per canonical id to match whichever convention players.id uses.
    """
    # Build reverse map gsis → [canonical player_ids] (one-to-many)
    gsis_to_players: Dict[str, List[str]] = {}
    for player_id, gsis_id in player_to_gsis.items():
        gsis_to_players.setdefault(gsis_id, []).append(player_id)

    rows = []
    for _, row in seasonal_df.iterrows():
        if row.get("season") != season:
            continue
        gsis_id = str(row.get("player_id", ""))  # gsis_id in nfl_data_py
        player_ids = gsis_to_players.get(gsis_id)
        if not player_ids:
            continue

        for player_id in player_ids:
            rows.append({
                "player_id": player_id,
                "season": season,
                "snap_pct": _safe_float(row.get("snap_pct")),
                "target_share": _safe_float(row.get("target_share")),
                "air_yards_share": _safe_float(row.get("air_yards_share")),
                "wopr": _safe_float(row.get("wopr")),
                "carry_share": _safe_float(row.get("carry_share")),
                "rz_target_share": _safe_float(row.get("racr")),  # proxy
                "epa_per_play": _safe_float(row.get("receiving_epa")),
                "td_luck": None,  # computed separately in flags.py
            })
    return rows


def normalize_historical_stats(
    weekly_df: "pd.DataFrame",
    sleeper_to_gsis: Dict[str, str],
    season: int,
) -> List[dict]:
    """Aggregate weekly stats → historical_stats DB rows per player/season."""
    gsis_to_sleeper = {v: k for k, v in sleeper_to_gsis.items()}

    relevant = weekly_df[weekly_df["season"] == season].copy()
    agg = relevant.groupby("player_id").agg(
        games=("week", "count"),
        targets=("targets", "sum"),
        carries=("carries", "sum"),
        receptions=("receptions", "sum"),
        rush_yards=("rushing_yards", "sum"),
        rec_yards=("receiving_yards", "sum"),
        tds=("touchdown", "sum"),
    ).reset_index()

    rows = []
    for _, row in agg.iterrows():
        gsis_id = str(row["player_id"])
        sleeper_id = gsis_to_sleeper.get(gsis_id)
        if not sleeper_id:
            continue
        rows.append({
            "player_id": sleeper_id,
            "season": season,
            "games": int(row.get("games", 0)),
            "targets": int(row.get("targets", 0)),
            "carries": int(row.get("carries", 0)),
            "receptions": int(row.get("receptions", 0)),
            "rush_yards": int(row.get("rush_yards", 0)),
            "rec_yards": int(row.get("rec_yards", 0)),
            "tds": int(row.get("tds", 0)),
            "pts_ppr_per_game": 0.0,  # filled in after projections are loaded
        })
    return rows


def _safe_float(val: Any) -> Optional[float]:
    try:
        return float(val) if val is not None and val == val else None
    except (TypeError, ValueError):
        return None
