"""
ADP vs VBD discrepancy scoring.
"""
from __future__ import annotations

import pandas as pd


def compute_adp_gap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add adp_gap column: positive = undervalued by consensus (value pick).
    adp_gap = adp_overall_rank - vbd_overall_rank
    Positive means ADP thinks they should be drafted later than VBD says.
    """
    df = df.copy()
    df["adp_gap"] = df["adp_overall"] - df["overall_rank"]
    return df


def get_value_picks(df: pd.DataFrame, min_gap: float = 10.0, top_n: int = 20) -> pd.DataFrame:
    """Return top value picks: players where ADP is much later than VBD rank."""
    return df[df["adp_gap"] >= min_gap].nlargest(top_n, "adp_gap")


def get_overvalued(df: pd.DataFrame, min_gap: float = 10.0, top_n: int = 20) -> pd.DataFrame:
    """Return players who are overvalued: ADP much earlier than VBD rank."""
    return df[df["adp_gap"] <= -min_gap].nsmallest(top_n, "adp_gap")
