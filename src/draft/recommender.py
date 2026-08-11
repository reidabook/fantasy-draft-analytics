"""
Pick recommendation engine for the draft board.
Returns top 3 recommended players with one-line reasoning.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from src.draft.board import DraftBoard


def get_recommendations(
    available_df: pd.DataFrame,
    board: DraftBoard,
    scarcity: dict,
    top_n: int = 3,
) -> List[dict]:
    """
    Recommend top N picks for the current selection.

    Strategy:
    1. Positional need: boost positions we're thin on
    2. Scarcity: if a position is RED alert, prioritize best available there
    3. VBD surplus: baseline ranking
    4. BPA (Best Player Available) as tiebreaker

    Returns list of dicts: {player_id, name, position, team, vbd_surplus,
                             reasoning, score}
    """
    if available_df.empty:
        return []

    needs = board.positional_needs()
    df = available_df.copy()

    # Score each player
    df["rec_score"] = df["vbd_surplus"]

    # Scarcity boost: RED positions get +50 points to recommendation score
    for pos, info in scarcity.items():
        if info["level"] == "red":
            mask = df["position"] == pos
            df.loc[mask, "rec_score"] += 50
        elif info["level"] == "yellow":
            mask = df["position"] == pos
            df.loc[mask, "rec_score"] += 20

    # Positional need boost
    need_boost = {"critical": 30, "needed": 15, "ok": 5, "full": -10}
    for pos, urgency in needs.items():
        mask = df["position"] == pos
        df.loc[mask, "rec_score"] += need_boost.get(urgency, 0)

    # Top N by recommendation score
    top = df.nlargest(top_n, "rec_score")

    results = []
    for _, row in top.iterrows():
        results.append({
            "player_id": row.get("id", ""),
            "name": row.get("name", ""),
            "position": row.get("position", ""),
            "team": row.get("team", ""),
            "vbd_surplus": round(float(row.get("vbd_surplus", 0)), 1),
            "adp_gap": round(float(row.get("adp_gap", 0)), 1),
            "tier": int(row.get("tier", 8)),
            "flag": row.get("flag_summary", ""),
            "reasoning": _build_reasoning(row, needs, scarcity),
            "rec_score": round(float(row.get("rec_score", 0)), 1),
        })
    return results


def _build_reasoning(row: pd.Series, needs: dict, scarcity: dict) -> str:
    """Build a one-line reason string for a recommendation."""
    pos = row.get("position", "")
    vbd = round(float(row.get("vbd_surplus", 0)), 1)
    adp_gap = round(float(row.get("adp_gap", 0)), 1)
    tier = int(row.get("tier", 8))
    flags = row.get("flag_summary", "")

    parts = []

    # Scarcity
    if scarcity.get(pos, {}).get("level") == "red":
        parts.append(f"{pos} is scarce")
    elif scarcity.get(pos, {}).get("level") == "yellow":
        parts.append(f"{pos} thinning")

    # Value
    if adp_gap >= 15:
        parts.append(f"value pick (+{adp_gap} vs ADP)")
    elif adp_gap >= 5:
        parts.append(f"slight value (+{adp_gap} vs ADP)")
    elif adp_gap <= -15:
        parts.append(f"reaching ({adp_gap} vs ADP)")

    # Tier
    if tier <= 2:
        parts.append(f"Tier {tier} player")

    # VBD
    parts.append(f"VBD surplus {vbd}")

    # Flags
    if "SLEEPER" in flags:
        parts.append("sleeper upside")

    return "; ".join(parts) if parts else f"BPA — VBD surplus {vbd}"
