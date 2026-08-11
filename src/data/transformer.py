"""
Transform raw API data → normalized DataFrames and DB-ready dicts.
All functions accept raw fetcher output and return lists of dicts
suitable for passing directly to cache.py upsert functions.
"""
from __future__ import annotations

import difflib
from typing import Any, Dict, List, Optional

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


def _fuzzy_lookup(name: str, name_map: Dict[str, str], cutoff: float = 0.85) -> Optional[str]:
    """Fuzzy name match fallback."""
    matches = difflib.get_close_matches(name, name_map.keys(), n=1, cutoff=cutoff)
    return name_map[matches[0]] if matches else None


# ---------------------------------------------------------------------------
# ID mapping (nfl_data_py ↔ Sleeper)
# ---------------------------------------------------------------------------

def build_id_map(ids_df: "pd.DataFrame") -> Dict[str, str]:
    """
    Build sleeper_id → gsis_id map from nfl_data_py import_ids() output.
    Also returns name → sleeper_id map for ADP fuzzy matching.
    """
    sleeper_to_gsis = {}
    name_to_sleeper = {}

    for _, row in ids_df.iterrows():
        sleeper_id = str(row.get("sleeper_id", "")) if pd.notna(row.get("sleeper_id")) else None
        gsis_id = str(row.get("gsis_id", "")) if pd.notna(row.get("gsis_id")) else None
        name = str(row.get("name", "")).lower().strip() if pd.notna(row.get("name")) else None

        if sleeper_id and gsis_id:
            sleeper_to_gsis[sleeper_id] = gsis_id
        if name and sleeper_id:
            name_to_sleeper[name] = sleeper_id

    return sleeper_to_gsis, name_to_sleeper


# ---------------------------------------------------------------------------
# nfl_data_py seasonal metrics normalization
# ---------------------------------------------------------------------------

def normalize_seasonal_metrics(
    seasonal_df: "pd.DataFrame",
    sleeper_to_gsis: Dict[str, str],
    season: int,
) -> List[dict]:
    """
    Convert nfl_data_py seasonal DataFrame → advanced_metrics DB rows.
    Maps gsis_id back to sleeper_id for joining.
    """
    # Build reverse map gsis → sleeper
    gsis_to_sleeper = {v: k for k, v in sleeper_to_gsis.items()}

    rows = []
    for _, row in seasonal_df.iterrows():
        if row.get("season") != season:
            continue
        player_id = row.get("player_id", "")  # gsis_id in nfl_data_py
        sleeper_id = gsis_to_sleeper.get(str(player_id))
        if not sleeper_id:
            continue

        rows.append({
            "player_id": sleeper_id,
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
