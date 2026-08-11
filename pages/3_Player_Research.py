"""
Page 3: Player Research
Search + metrics table, side-by-side comparison, radar chart vs positional average.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="Player Research", layout="wide")
st.title("🔬 Player Research")

from src.data.cache import get_vbd_scores, get_all_players

config = st.session_state.get("active_league")
if not config:
    st.info("Select a league in the sidebar first.")
    st.stop()

# ---------------------------------------------------------------------------
# Load full player + VBD dataset
# ---------------------------------------------------------------------------

@st.cache_data(ttl=120, show_spinner=False)
def load_full(league_id: str, season: int, scoring_type: str) -> pd.DataFrame:
    rows = get_vbd_scores(league_id, season, scoring_type)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


df = load_full(config.league_id, config.season, config.scoring.type)

if df.empty:
    st.info("No data yet. Go to VBD Rankings and click ↺ Recalc, or run prefetch.py first.")
    st.stop()

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

col_search, col_pos, col_team = st.columns([3, 2, 2])
with col_search:
    query = st.text_input("Search player", placeholder="Name...", label_visibility="collapsed")
with col_pos:
    pos_opts = ["All"] + sorted(df["position"].dropna().unique().tolist())
    pos_sel = st.selectbox("Position", pos_opts, label_visibility="collapsed")
with col_team:
    team_opts = ["All"] + sorted(df["team"].dropna().unique().tolist())
    team_sel = st.selectbox("Team", team_opts, label_visibility="collapsed")

fdf = df.copy()
if query:
    fdf = fdf[fdf["name"].str.contains(query, case=False, na=False)]
if pos_sel != "All":
    fdf = fdf[fdf["position"] == pos_sel]
if team_sel != "All":
    fdf = fdf[fdf["team"] == team_sel]

fdf = fdf.sort_values("overall_rank", ascending=True)

# ---------------------------------------------------------------------------
# Metrics table
# ---------------------------------------------------------------------------

DISPLAY_COLS = {
    "overall_rank": "Rank",
    "tier": "Tier",
    "name": "Name",
    "position": "Pos",
    "team": "Team",
    "projected_pts": "Proj Pts",
    "vbd_surplus": "VBD Surplus",
    "adp_overall": "ADP",
    "adp_gap": "ADP Gap",
    "target_share": "Tgt%",
    "snap_pct": "Snap%",
    "carry_share": "Carry%",
    "wopr": "WOPR",
    "schedule_grade": "SOS",
    "flag_summary": "Flags",
}

show_cols = [c for c in DISPLAY_COLS if c in fdf.columns]
display_df = fdf[show_cols].copy()
display_df = display_df.rename(columns=DISPLAY_COLS)

# Format percentage columns
for col_name, display_name in [("target_share", "Tgt%"), ("snap_pct", "Snap%"), ("carry_share", "Carry%")]:
    if display_name in display_df.columns:
        display_df[display_name] = display_df[display_name].apply(
            lambda x: f"{x*100:.1f}%" if pd.notna(x) and x else "—"
        )
if "ADP" in display_df.columns:
    display_df["ADP"] = display_df["ADP"].apply(
        lambda x: f"{x:.0f}" if pd.notna(x) and x < 999 else "—"
    )
if "Proj Pts" in display_df.columns:
    display_df["Proj Pts"] = display_df["Proj Pts"].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")
if "VBD Surplus" in display_df.columns:
    display_df["VBD Surplus"] = display_df["VBD Surplus"].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "—")
if "ADP Gap" in display_df.columns:
    display_df["ADP Gap"] = display_df["ADP Gap"].apply(
        lambda x: f"+{x:.0f}" if pd.notna(x) and x > 0 else (f"{x:.0f}" if pd.notna(x) else "—")
    )
if "WOPR" in display_df.columns:
    display_df["WOPR"] = display_df["WOPR"].apply(lambda x: f"{x:.3f}" if pd.notna(x) and x else "—")

st.dataframe(
    display_df,
    use_container_width=True,
    height=400,
    hide_index=True,
)

st.caption(f"{len(fdf)} players shown")
st.markdown("---")

# ---------------------------------------------------------------------------
# Side-by-side comparison
# ---------------------------------------------------------------------------

st.subheader("⚖️ Side-by-Side Comparison")

all_names = sorted(df["name"].dropna().unique().tolist())

comp_col1, comp_col2 = st.columns(2)
with comp_col1:
    player_a = st.selectbox("Player A", ["(select)"] + all_names, key="cmp_a")
with comp_col2:
    player_b = st.selectbox("Player B", ["(select)"] + all_names, key="cmp_b")

if player_a != "(select)" and player_b != "(select)" and player_a != player_b:
    row_a = df[df["name"] == player_a].iloc[0]
    row_b = df[df["name"] == player_b].iloc[0]

    CMP_FIELDS = [
        ("overall_rank", "Overall Rank", False),
        ("tier", "Tier", False),
        ("projected_pts", "Projected Pts", True),
        ("vbd_surplus", "VBD Surplus", True),
        ("adp_overall", "ADP", False),
        ("adp_gap", "ADP Gap", True),
        ("target_share", "Target Share", True),
        ("snap_pct", "Snap %", True),
        ("carry_share", "Carry Share", True),
        ("wopr", "WOPR", True),
        ("schedule_grade", "Schedule Grade", None),
    ]

    cmp_data = []
    for field, label, higher_is_better in CMP_FIELDS:
        val_a = row_a.get(field)
        val_b = row_b.get(field)
        if val_a is None and val_b is None:
            continue

        def fmt(v, field=field):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return "—"
            if field in ("target_share", "snap_pct", "carry_share"):
                return f"{v*100:.1f}%"
            if isinstance(v, float):
                return f"{v:.1f}"
            return str(v)

        # Winner highlighting
        winner = None
        if higher_is_better is not None and val_a is not None and val_b is not None:
            try:
                a_num, b_num = float(val_a), float(val_b)
                if higher_is_better:
                    winner = "a" if a_num > b_num else ("b" if b_num > a_num else None)
                else:
                    winner = "a" if a_num < b_num else ("b" if b_num < a_num else None)
            except (ValueError, TypeError):
                pass

        cmp_data.append({
            "Metric": label,
            player_a: fmt(val_a),
            player_b: fmt(val_b),
            "_winner": winner,
        })

    # Render comparison table manually for color highlighting
    hdr_cols = st.columns([2, 2, 2])
    hdr_cols[0].markdown("**Metric**")
    hdr_cols[1].markdown(f"**{player_a}** ({row_a.get('position','')}, {row_a.get('team','')})")
    hdr_cols[2].markdown(f"**{player_b}** ({row_b.get('position','')}, {row_b.get('team','')})")

    for row in cmp_data:
        r_cols = st.columns([2, 2, 2])
        r_cols[0].markdown(f"<span style='color:#6b7280;font-size:0.9em'>{row['Metric']}</span>", unsafe_allow_html=True)
        color_a = "#4ade80" if row["_winner"] == "a" else ("#f87171" if row["_winner"] == "b" else "#e5e7eb")
        color_b = "#4ade80" if row["_winner"] == "b" else ("#f87171" if row["_winner"] == "a" else "#e5e7eb")
        r_cols[1].markdown(f"<span style='color:{color_a};font-weight:{'700' if row['_winner']=='a' else '400'}'>{row[player_a]}</span>", unsafe_allow_html=True)
        r_cols[2].markdown(f"<span style='color:{color_b};font-weight:{'700' if row['_winner']=='b' else '400'}'>{row[player_b]}</span>", unsafe_allow_html=True)

    # ---------------------------------------------------------------------------
    # Radar chart vs positional average
    # ---------------------------------------------------------------------------

    st.markdown("---")
    st.subheader("📡 Radar vs Positional Average")

    RADAR_FIELDS = ["projected_pts", "vbd_surplus", "target_share", "snap_pct", "carry_share", "wopr"]
    RADAR_LABELS = ["Proj Pts", "VBD Surplus", "Tgt Share", "Snap %", "Carry%", "WOPR"]

    def get_radar_values(player_row: pd.Series, pos: str) -> list:
        pos_df = df[df["position"] == pos]
        values = []
        for field in RADAR_FIELDS:
            val = player_row.get(field)
            col_data = pos_df[field].dropna() if field in pos_df.columns else pd.Series()
            if col_data.empty or val is None or pd.isna(val):
                values.append(0.0)
                continue
            col_min, col_max = col_data.min(), col_data.max()
            if col_max == col_min:
                values.append(0.5)
            else:
                values.append(float((val - col_min) / (col_max - col_min)))
        return values

    fig = go.Figure()
    for player_name, row_data in [(player_a, row_a), (player_b, row_b)]:
        vals = get_radar_values(row_data, row_data.get("position", "WR"))
        vals_closed = vals + [vals[0]]
        labels_closed = RADAR_LABELS + [RADAR_LABELS[0]]
        fig.add_trace(go.Scatterpolar(
            r=vals_closed,
            theta=labels_closed,
            fill="toself",
            name=player_name,
            opacity=0.6,
        ))

    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
        height=450,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#9ca3af"),
        legend=dict(orientation="h", yanchor="bottom", y=-0.15),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Values normalized 0–1 within each player's position group")

elif player_a != "(select)" and player_b != "(select)" and player_a == player_b:
    st.warning("Select two different players to compare.")
