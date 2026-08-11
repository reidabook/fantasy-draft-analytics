"""
Page 5: Sleeper Radar
Sleeper candidates, bust watch, handcuff targets with evidence rows.
"""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Sleeper Radar", layout="wide")
st.title("📡 Sleeper Radar")

from src.data.cache import get_vbd_scores, get_advanced_metrics
from src.analytics.flags import flag_players

config = st.session_state.get("active_league")
if not config:
    st.info("Select a league in the sidebar first.")
    st.stop()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

@st.cache_data(ttl=120, show_spinner=False)
def load_df(league_id: str, season: int, scoring_type: str) -> pd.DataFrame:
    rows = get_vbd_scores(league_id, season, scoring_type)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # flag_players() expects 'id' column (compute_vbd output convention).
    # get_vbd_scores() returns 'player_id'. Rename to bridge the mismatch.
    df = df.rename(columns={"player_id": "id"})
    metrics_rows = get_advanced_metrics(season)
    metrics_df = pd.DataFrame(metrics_rows) if metrics_rows else pd.DataFrame()
    prior_rows = get_advanced_metrics(season - 1)
    prior_df = pd.DataFrame(prior_rows) if prior_rows else None
    df = flag_players(df, metrics_df, prior_df)
    return df


df = load_df(config.league_id, config.season, config.scoring.type)

if df.empty:
    st.info("No data yet. Go to VBD Rankings and click ↺ Recalc, or run prefetch.py.")
    st.stop()

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

pos_filter = st.multiselect(
    "Position filter",
    options=["QB", "RB", "WR", "TE"],
    default=["QB", "RB", "WR", "TE"],
)
if pos_filter:
    df = df[df["position"].isin(pos_filter)]

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

POS_COLOR = {"QB": "#FF6B6B", "RB": "#4ECDC4", "WR": "#45B7D1", "TE": "#96CEB4"}


def player_header(row: pd.Series):
    pos = row.get("position", "")
    color = POS_COLOR.get(pos, "#888")
    name = row.get("name", "")
    team = row.get("team", "")
    adp = row.get("adp_overall")
    adp_str = f"ADP #{adp:.0f}" if adp and adp < 999 else "ADP undrafted"
    vbd = row.get("vbd_surplus", 0)
    return (
        f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:4px'>"
        f"<span style='color:{color};font-weight:700;font-size:1.05em'>{name}</span>"
        f"<span style='color:#9ca3af;font-size:0.85em'>{pos} · {team}</span>"
        f"<span style='color:#6b7280;font-size:0.8em'>VBD {vbd:.1f} · {adp_str}</span>"
        f"</div>"
    )


def evidence_row(items: list):
    """Render a list of evidence bullets."""
    bullets = "".join(f"<li style='color:#d1d5db;font-size:0.85em'>{item}</li>" for item in items)
    return f"<ul style='margin:4px 0 8px 16px;padding:0'>{bullets}</ul>"


# ---------------------------------------------------------------------------
# Tab layout
# ---------------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs(["🟢 Sleeper Candidates", "🔴 Bust Watch", "🤝 Handcuff Targets"])

# ---------------------------------------------------------------------------
# Tab 1: Sleepers
# ---------------------------------------------------------------------------

with tab1:
    st.markdown("Players with positive usage trends and potential ADP value.")

    has_flags = "flag_summary" in df.columns
    if has_flags:
        sleepers = df[df["flag_summary"].str.contains("SLEEPER", na=False)].copy()
    else:
        # Fallback: players with adp_gap > 10 (consensus undervalues them)
        sleepers = df[df.get("adp_gap", pd.Series(0, index=df.index)) > 10].copy()

    sleepers = sleepers.sort_values("adp_gap", ascending=False)

    if sleepers.empty:
        st.info("No sleeper candidates detected. Run prefetch.py --full to pull nfl_data_py metrics.")
    else:
        st.caption(f"{len(sleepers)} sleeper candidates found")
        for _, row in sleepers.iterrows():
            st.markdown(player_header(row), unsafe_allow_html=True)

            # Build evidence list
            evidence = []
            reasons = row.get("sleeper_reasons", "")
            if reasons:
                for r in str(reasons).split(";"):
                    r = r.strip()
                    if r:
                        evidence.append(r)

            # Metric evidence (if available)
            tgt = row.get("target_share")
            if tgt and tgt > 0:
                evidence.append(f"Target share: {tgt*100:.1f}%")
            wopr = row.get("wopr")
            if wopr and wopr > 0.35:
                evidence.append(f"WOPR: {wopr:.3f} (strong air yards + target share combo)")
            snap = row.get("snap_pct")
            if snap and snap > 0.75:
                evidence.append(f"Snap %: {snap*100:.0f}% (full starter workload)")
            adp_gap = row.get("adp_gap", 0)
            if adp_gap and adp_gap > 5:
                evidence.append(f"ADP gap: +{adp_gap:.0f} picks (VBD ranks higher than consensus)")
            schedule = row.get("schedule_grade", "")
            if schedule in ("A", "B"):
                evidence.append(f"Playoff schedule grade: {schedule} (favorable matchups in Wks 15-17)")

            if not evidence:
                evidence.append("Identified by flag engine — run --full for detailed metrics")

            st.markdown(evidence_row(evidence), unsafe_allow_html=True)
            st.markdown("<hr style='border-color:#374151;margin:4px 0'>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Tab 2: Bust Watch
# ---------------------------------------------------------------------------

with tab2:
    st.markdown("Players showing regression risk or rising ADP with declining metrics.")

    if has_flags:
        busts = df[df["flag_summary"].str.contains("BUST", na=False)].copy()
    else:
        # Fallback: players with adp_gap < -10 (consensus overvalues them)
        busts = df[df.get("adp_gap", pd.Series(0, index=df.index)) < -10].copy()

    busts = busts.sort_values("adp_gap", ascending=True)

    if busts.empty:
        st.info("No bust candidates detected. Run prefetch.py --full for detailed analytics.")
    else:
        st.caption(f"{len(busts)} bust candidates found")
        for _, row in busts.iterrows():
            st.markdown(player_header(row), unsafe_allow_html=True)

            evidence = []
            reasons = row.get("bust_reasons", "")
            if reasons:
                for r in str(reasons).split(";"):
                    r = r.strip()
                    if r:
                        evidence.append(r)

            # Metric evidence
            tgt = row.get("target_share")
            if tgt is not None and tgt < 0.12:
                evidence.append(f"Low target share: {tgt*100:.1f}% (below viable WR/TE threshold)")
            snap = row.get("snap_pct")
            if snap is not None and snap < 0.60:
                evidence.append(f"Snap %: {snap*100:.0f}% (part-time role)")
            adp_gap = row.get("adp_gap", 0)
            if adp_gap and adp_gap < -5:
                evidence.append(f"ADP gap: {adp_gap:.0f} picks (VBD ranks significantly lower than consensus)")
            schedule = row.get("schedule_grade", "")
            if schedule in ("C", "D"):
                evidence.append(f"Playoff schedule grade: {schedule} (tough matchups in Wks 15-17)")

            if not evidence:
                evidence.append("Identified by flag engine — run --full for detailed metrics")

            st.markdown(evidence_row(evidence), unsafe_allow_html=True)
            st.markdown("<hr style='border-color:#374151;margin:4px 0'>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Tab 3: Handcuffs
# ---------------------------------------------------------------------------

with tab3:
    st.markdown("Backup RBs worth rostering based on starter injury risk and workload opportunity.")

    if has_flags:
        handcuffs = df[df["flag_summary"].str.contains("HANDCUFF", na=False)].copy()
    else:
        # Fallback: RBs with ADP in rounds 8+ (backup tier)
        rb_df = df[df["position"] == "RB"].copy()
        handcuffs = rb_df[rb_df.get("adp_overall", pd.Series(999, index=rb_df.index)) > config.teams * 7].copy()

    handcuffs = handcuffs.sort_values("adp_overall", ascending=True) if not handcuffs.empty else handcuffs

    if handcuffs.empty:
        st.info("No handcuff targets identified. Run prefetch.py --full for depth chart data.")
    else:
        st.caption(f"{len(handcuffs)} handcuff targets found")
        for _, row in handcuffs.iterrows():
            st.markdown(player_header(row), unsafe_allow_html=True)

            evidence = []
            # Show handcuff info if available
            carry = row.get("carry_share")
            if carry and carry > 0.10:
                evidence.append(f"Carry share: {carry*100:.0f}% (meaningful committee role)")
            snap = row.get("snap_pct")
            if snap and snap > 0.30:
                evidence.append(f"Snap %: {snap*100:.0f}% (on-field presence, ready to step up)")
            adp = row.get("adp_overall")
            if adp and adp > config.teams * 10:
                evidence.append(f"ADP #{adp:.0f} — late-round value, low cost to roster")
            vbd = row.get("vbd_surplus", 0)
            if vbd > 0:
                evidence.append(f"VBD surplus {vbd:.1f} — standalone value if starter goes down")
            else:
                evidence.append("Roster for insurance — minimal standalone value but crucial if starter injured")

            st.markdown(evidence_row(evidence), unsafe_allow_html=True)
            st.markdown("<hr style='border-color:#374151;margin:4px 0'>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Footer: data quality note
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    "🔍 Sleeper Radar uses nfl_data_py metrics (target share, snap %, WOPR, carry share). "
    "Run `python prefetch.py --full` weekly during the preseason to keep signal current. "
    "Flags are computed in `src/analytics/flags.py`."
)
