"""
Value-Based Drafting (VBD) surplus calculations.

VBD surplus = player_projected_pts - replacement_player_projected_pts
Replacement level is set by the league's roster configuration.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.config.settings import LeagueConfig


def compute_vbd(
    players: List[dict],
    projections: List[dict],
    adp: List[dict],
    config: LeagueConfig,
    notes: Optional[Dict[str, dict]] = None,
) -> pd.DataFrame:
    """
    Core VBD computation.

    Args:
        players: list of player dicts from cache
        projections: list of projection dicts from cache
        adp: list of ADP dicts from cache
        config: LeagueConfig for this league
        notes: optional {player_id: {custom_rank, notes}} from cache

    Returns:
        DataFrame with all VBD columns, sorted by overall_rank.
    """
    # Build DataFrames
    players_df = pd.DataFrame(players)
    if players_df.empty:
        return pd.DataFrame()

    proj_df = pd.DataFrame(projections)
    if proj_df.empty:
        return pd.DataFrame()

    adp_df = pd.DataFrame(adp) if adp else pd.DataFrame(columns=["player_id", "adp_overall"])

    # Determine which projection column to use based on scoring type
    scoring_type = config.scoring.type
    pts_col = {"ppr": "pts_ppr", "half_ppr": "pts_half_ppr", "standard": "pts_std"}.get(
        scoring_type, "pts_ppr"
    )

    # Take the best (highest) projection if multiple sources
    proj_best = (
        proj_df.groupby("player_id")[pts_col]
        .max()
        .reset_index()
        .rename(columns={pts_col: "projected_pts"})
    )

    # Merge players ← projections ← ADP
    df = players_df.merge(proj_best, left_on="id", right_on="player_id", how="left")
    df["projected_pts"] = df["projected_pts"].fillna(0.0)

    if not adp_df.empty:
        adp_best = adp_df.groupby("player_id")["adp_overall"].min().reset_index()
        df = df.merge(adp_best, left_on="id", right_on="player_id", how="left")
        df["adp_overall"] = df["adp_overall"].fillna(999.0)
    else:
        df["adp_overall"] = 999.0

    # Limit to skill positions with an actual projection — players with no
    # projection data would otherwise dump into one giant tier and skew the
    # tier-gap statistics for everyone else (see _assign_tiers)
    df = df[df["position"].isin(["QB", "RB", "WR", "TE"]) & (df["projected_pts"] > 0)].copy()

    # Position ranks by projected points
    df["position_rank"] = df.groupby("position")["projected_pts"].rank(
        ascending=False, method="min"
    )

    # Replacement thresholds
    replacement = config.replacement_rank  # {QB: 12, RB: 30, WR: 30, TE: 12}

    # Look up replacement player points per position
    replacement_pts_map = _get_replacement_pts(df, replacement)

    df["replacement_pts"] = df["position"].map(replacement_pts_map).fillna(0.0)
    df["vbd_surplus"] = (df["projected_pts"] - df["replacement_pts"]).clip(lower=0)

    # Overall VBD rank
    df["overall_rank"] = df["vbd_surplus"].rank(ascending=False, method="min").astype(int)

    # ADP gap: positive = value (ADP thinks they're worse than VBD says)
    df["adp_gap"] = df["adp_overall"] - df["overall_rank"]

    # Auto-detect tiers from VBD cliffs
    df = _assign_tiers(df)

    # Apply custom ranks from notes
    if notes:
        for player_id, note in notes.items():
            cr = note.get("custom_rank")
            if cr:
                mask = df["id"] == player_id
                df.loc[mask, "custom_rank"] = cr
        # Re-sort respecting custom ranks (lower custom rank wins)
        df["sort_key"] = df.apply(
            lambda r: r["custom_rank"] if pd.notna(r.get("custom_rank")) else r["overall_rank"] + 1000,
            axis=1,
        )
        df = df.sort_values("sort_key").reset_index(drop=True)
    else:
        df = df.sort_values("overall_rank").reset_index(drop=True)

    # Add notes
    if notes:
        df["notes"] = df["id"].map(
            {pid: n.get("notes", "") for pid, n in notes.items()}
        ).fillna("")
        df["custom_rank"] = df["id"].map(
            {pid: n.get("custom_rank") for pid, n in notes.items()}
        )
    else:
        df["notes"] = ""
        df["custom_rank"] = None

    return df


def _get_replacement_pts(df: pd.DataFrame, replacement: Dict[str, int]) -> Dict[str, float]:
    """
    For each position, find the projected points of the replacement-level player.
    Returns {position: replacement_pts}.
    """
    result = {}
    for pos, threshold in replacement.items():
        pos_df = df[df["position"] == pos].sort_values("projected_pts", ascending=False)
        if len(pos_df) >= threshold:
            result[pos] = pos_df.iloc[threshold - 1]["projected_pts"]
        elif not pos_df.empty:
            result[pos] = pos_df.iloc[-1]["projected_pts"]
        else:
            result[pos] = 0.0
    return result


def _assign_tiers(df: pd.DataFrame, n_tiers: int = 40) -> pd.DataFrame:
    """
    Auto-detect tiers from VBD cliffs (gaps in vbd_surplus distribution).
    Assigns tier 1 (best) through n_tiers.
    """
    if df.empty:
        df["tier"] = 1
        return df

    sorted_surplus = df["vbd_surplus"].sort_values(ascending=False).reset_index(drop=True)

    # Find gaps between consecutive players
    gaps = sorted_surplus.diff().abs().fillna(0)
    # A 0.5 std threshold produces only ~2-3 tiers across a full draft-relevant
    # pool (too coarse to be useful round-to-round); 0.15 yields ~10-15 tiers,
    # which lines up with real draft-day value cliffs.
    threshold = sorted_surplus.std() * 0.15
    tier_breaks = set(gaps[gaps > threshold].index.tolist())

    # The tail of the pool declines too smoothly for any gap threshold to find
    # cliffs, which would otherwise dump hundreds of players into one final
    # tier. Force a break every max_tier_size players so tiers stay usable
    # round-to-round even without a clean value cliff.
    max_tier_size = 12
    tier_map = {}  # index in sorted → tier
    current_tier = 1
    size_in_tier = 0
    for i, surplus in enumerate(sorted_surplus):
        if i > 0 and (i in tier_breaks or size_in_tier >= max_tier_size):
            current_tier += 1
            size_in_tier = 0
        if current_tier > n_tiers:
            current_tier = n_tiers
        tier_map[i] = current_tier
        size_in_tier += 1

    # Map back to df by rank order
    rank_to_tier = {}
    sorted_df = df.sort_values("vbd_surplus", ascending=False)
    for i, (idx, row) in enumerate(sorted_df.iterrows()):
        rank_to_tier[idx] = tier_map.get(i, n_tiers)

    df["tier"] = df.index.map(rank_to_tier)
    return df


def vbd_to_db_rows(df: pd.DataFrame, league_id: str, season: int, scoring_type: str) -> List[dict]:
    """Convert VBD DataFrame to list of dicts for cache.upsert_vbd_scores()."""
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "player_id": row.get("id", ""),
            "league_id": league_id,
            "season": season,
            "scoring_type": scoring_type,
            "projected_pts": float(row.get("projected_pts", 0)),
            "replacement_pts": float(row.get("replacement_pts", 0)),
            "vbd_surplus": float(row.get("vbd_surplus", 0)),
            "position_rank": int(row.get("position_rank", 0)),
            "overall_rank": int(row.get("overall_rank", 0)),
            "adp_gap": float(row.get("adp_gap", 0)),
            "tier": int(row.get("tier", 8)),
        })
    return rows
