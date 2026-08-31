"""
Sleeper/bust/handcuff detection logic.

Sleeper signals (green):
- target_share growing YoY > 3%
- wopr > 0.4 (WR/TE)
- snap_pct > 75% but ADP implies backup
- carry_share growth YoY > 5% (RB)

Bust signals (red):
- td_luck = actual_td_rate - xTD_rate > 0.05 (regression likely)
- target_share declining despite rising ADP
- snap_pct < 60% but ADP implies starter
- depth_chart_pos = backup but ADP suggests starter
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd


def compute_td_luck(
    metrics_current: pd.Series,
    metrics_prior: Optional[pd.Series] = None,
) -> Optional[float]:
    """
    td_luck approximation: compare observed TD rate to expected.
    Uses red zone target share as proxy for xTD.
    Returns positive = over-performer (bust risk), negative = under-performer (sleeper).
    """
    tds = metrics_current.get("tds", 0)
    targets = metrics_current.get("targets", 1) or 1
    rz_target_share = metrics_current.get("rz_target_share") or 0
    # xTD proxy: rz_target_share * league_avg_rz_tds (approx 30 for WR/TE)
    # Simplified: actual_td_rate vs expected from rz share
    actual_td_rate = tds / targets
    expected_td_rate = rz_target_share * 0.25  # rough conversion
    return round(actual_td_rate - expected_td_rate, 3)


def _compute_handcuffs(
    df: pd.DataFrame,
    min_projected_pts: float = 20.0,
    max_starter_ratio: float = 0.75,
) -> Dict[int, str]:
    """
    Infer handcuff RBs by grouping same-team RBs and comparing their own
    projected points — no depth-chart field required (ours is unpopulated
    for ESPN-sourced players anyway). The team's top-projected RB is the
    "starter"; any teammate projecting for at least min_projected_pts but
    under max_starter_ratio of the starter's total is a handcuff candidate
    (has standalone value, but is clearly behind the lead back).
    Returns {df_index: starter_name}.
    """
    handcuff_of: Dict[int, str] = {}
    rb_df = df[df["position"] == "RB"]
    for team, group in rb_df.groupby("team"):
        # Players with no real team (free agents, missing data) would otherwise
        # get grouped together as if they shared a backfield — exclude them.
        if not team or team in ("FA", "None") or len(group) < 2:
            continue
        group = group.sort_values("projected_pts", ascending=False)
        starter = group.iloc[0]
        for idx, row in group.iloc[1:].iterrows():
            pts = row.get("projected_pts", 0) or 0
            if pts >= min_projected_pts and pts < starter["projected_pts"] * max_starter_ratio:
                handcuff_of[idx] = starter.get("name", "")
    return handcuff_of


def flag_players(
    vbd_df: pd.DataFrame,
    metrics_df: pd.DataFrame,
    prior_metrics_df: Optional[pd.DataFrame] = None,
    adp_cutoff_rank: int = 100,
) -> pd.DataFrame:
    """
    Add flag columns to the VBD DataFrame.

    Columns added:
    - is_sleeper: bool
    - is_bust: bool
    - is_handcuff: bool
    - sleeper_reasons: list of strings
    - bust_reasons: list of strings
    - flag_summary: short display string
    """
    df = vbd_df.copy()

    # Merge metrics
    if not metrics_df.empty:
        df = df.merge(
            metrics_df[["player_id", "snap_pct", "target_share", "wopr", "carry_share",
                        "rz_target_share", "td_luck"]],
            left_on="id", right_on="player_id", how="left",
        )
    else:
        for col in ["snap_pct", "target_share", "wopr", "carry_share", "rz_target_share", "td_luck"]:
            df[col] = None

    # Merge prior year metrics if available
    if prior_metrics_df is not None and not prior_metrics_df.empty:
        prior = prior_metrics_df[["player_id", "target_share", "carry_share", "snap_pct"]].rename(
            columns={"target_share": "prev_target_share", "carry_share": "prev_carry_share",
                     "snap_pct": "prev_snap_pct"}
        )
        df = df.merge(prior, left_on="id", right_on="player_id", how="left")
    else:
        df["prev_target_share"] = None
        df["prev_carry_share"] = None
        df["prev_snap_pct"] = None

    handcuff_of = _compute_handcuffs(df)

    df["is_sleeper"] = False
    df["is_bust"] = False
    df["is_handcuff"] = False
    df["handcuff_of"] = None
    df["sleeper_reasons"] = [[] for _ in range(len(df))]
    df["bust_reasons"] = [[] for _ in range(len(df))]

    for idx, row in df.iterrows():
        pos = row.get("position", "")
        adp = row.get("adp_overall", 999)
        sleeper_reasons = []
        bust_reasons = []

        # -----------------------------------------------
        # Sleeper signals
        # -----------------------------------------------
        ts = row.get("target_share")
        prev_ts = row.get("prev_target_share")
        if ts and prev_ts and (ts - prev_ts) > 0.03:
            sleeper_reasons.append(f"Target share +{round((ts - prev_ts)*100, 1)}% YoY")

        wopr = row.get("wopr")
        if wopr and wopr > 0.4 and pos in ("WR", "TE"):
            sleeper_reasons.append(f"High WOPR ({round(wopr, 2)})")

        snap = row.get("snap_pct")
        if snap and snap > 0.75 and adp > adp_cutoff_rank:
            sleeper_reasons.append(f"High snap% ({round(snap*100)}%) but late ADP")

        cs = row.get("carry_share")
        prev_cs = row.get("prev_carry_share")
        if cs and prev_cs and (cs - prev_cs) > 0.05 and pos == "RB":
            sleeper_reasons.append(f"Carry share +{round((cs - prev_cs)*100, 1)}% YoY")

        # -----------------------------------------------
        # Bust signals
        # -----------------------------------------------
        td_luck = row.get("td_luck")
        if td_luck and td_luck > 0.05:
            bust_reasons.append(f"TD luck +{round(td_luck, 3)} (regression risk)")

        if ts and prev_ts and (ts - prev_ts) < -0.03 and adp < adp_cutoff_rank:
            bust_reasons.append(f"Target share declining ({round(ts*100)}% from {round(prev_ts*100)}%)")

        depth = row.get("depth_chart_pos", "")
        if snap and snap < 0.60 and adp < adp_cutoff_rank:
            bust_reasons.append(f"Low snap% ({round(snap*100)}%) despite early ADP")

        if depth and "backup" in str(depth).lower() and adp < adp_cutoff_rank:
            bust_reasons.append(f"Depth chart: {depth}, ADP={round(adp)}")

        # -----------------------------------------------
        # Handcuff: same-team RB with standalone value clearly behind the lead back
        # -----------------------------------------------
        if idx in handcuff_of:
            df.at[idx, "is_handcuff"] = True
            df.at[idx, "handcuff_of"] = handcuff_of[idx]

        df.at[idx, "is_sleeper"] = len(sleeper_reasons) >= 1
        df.at[idx, "is_bust"] = len(bust_reasons) >= 1
        df.at[idx, "sleeper_reasons"] = sleeper_reasons
        df.at[idx, "bust_reasons"] = bust_reasons

    # Flag summary for display
    def _flag_str(row):
        flags = []
        if row["is_sleeper"]:
            flags.append("SLEEPER")
        if row["is_bust"]:
            flags.append("BUST?")
        if row["is_handcuff"]:
            flags.append("HC")
        return ", ".join(flags)

    df["flag_summary"] = df.apply(_flag_str, axis=1)
    return df
