"""
Real-time positional scarcity alerts for the draft board.
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd


def compute_scarcity(
    available_df: pd.DataFrame,
    my_next_pick_in: int,
    positions: List[str] = ("QB", "RB", "WR", "TE"),
) -> Dict[str, dict]:
    """
    Compute scarcity status for each position.

    Logic:
    - For each position, count players with VBD >= 70% of top available player's VBD
    - Compare that count to picks until my next turn
    - RED: count < picks_until_my_turn / 2
    - YELLOW: count < picks_until_my_turn
    - GREEN: otherwise

    Args:
        available_df: DataFrame of un-drafted players with vbd_surplus column
        my_next_pick_in: number of picks until I pick next
        positions: which positions to evaluate

    Returns:
        Dict: {position: {level: "red"|"yellow"|"green", count: int, threshold: float}}
    """
    result = {}
    for pos in positions:
        pos_df = available_df[available_df["position"] == pos].copy()
        if pos_df.empty:
            result[pos] = {"level": "green", "count": 0, "threshold": 0.0, "top_surplus": 0.0}
            continue

        top_surplus = pos_df["vbd_surplus"].max()
        threshold = top_surplus * 0.70

        # Count players who are "quality starters" (VBD within 70% of top)
        quality_count = (pos_df["vbd_surplus"] >= threshold).sum()

        if quality_count < max(1, my_next_pick_in / 2):
            level = "red"
        elif quality_count < my_next_pick_in:
            level = "yellow"
        else:
            level = "green"

        result[pos] = {
            "level": level,
            "count": int(quality_count),
            "threshold": round(float(threshold), 1),
            "top_surplus": round(float(top_surplus), 1),
        }
    return result


def scarcity_message(pos: str, info: dict) -> str:
    """Return a human-readable scarcity alert message."""
    level = info["level"]
    count = info["count"]
    if level == "red":
        return f"⚠️ {pos} SCARCE — only {count} quality players left"
    elif level == "yellow":
        return f"⚡ {pos} thinning — {count} quality players remaining"
    return ""
