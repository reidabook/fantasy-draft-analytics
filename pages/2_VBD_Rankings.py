"""
Page 2: VBD Rankings
Full tiered board with VBD surplus, position coloring, inline notes, CSV export.
"""
import io
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="VBD Rankings", layout="wide")
st.title("📊 VBD Rankings")

from src.data.cache import (
    get_vbd_scores, get_all_players, get_projections, get_adp,
    upsert_vbd_scores, upsert_player_note, get_all_player_notes,
)
from src.analytics.vbd import compute_vbd, vbd_to_db_rows

# ---------------------------------------------------------------------------
# Require active league
# ---------------------------------------------------------------------------

config = st.session_state.get("active_league")
if not config:
    st.info("Select a league in the sidebar first.")
    st.stop()

# ---------------------------------------------------------------------------
# Load VBD data
# ---------------------------------------------------------------------------

@st.cache_data(ttl=60, show_spinner=False)
def load_vbd(league_id: str, season: int, scoring_type: str):
    rows = get_vbd_scores(league_id, season, scoring_type)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df


@st.cache_data(ttl=60, show_spinner=False)
def load_notes(league_id: str):
    return get_all_player_notes(league_id)


def refresh_vbd():
    """Recompute VBD from raw data and write to DB."""
    players = get_all_players(positions=["QB", "RB", "WR", "TE"])
    projs = get_projections(season=config.season, week=0)
    adp = get_adp(season=config.season)
    notes = load_notes(config.league_id)
    if not players or not projs:
        st.warning("No player/projection data. Run prefetch.py first.")
        return False
    vbd_df = compute_vbd(players, projs, adp, config, notes)
    db_rows = vbd_to_db_rows(vbd_df, config.league_id, config.season, config.scoring.type)
    upsert_vbd_scores(db_rows)
    load_vbd.clear()
    return True


# ---------------------------------------------------------------------------
# Controls bar
# ---------------------------------------------------------------------------

col_refresh, col_pos, col_sort, col_search, col_export = st.columns([1, 2, 2, 3, 1])

with col_refresh:
    if st.button("↺ Recalc", help="Recompute VBD from current projections"):
        with st.spinner("Recalculating..."):
            ok = refresh_vbd()
        if ok:
            st.success("Done")
            st.rerun()

with col_pos:
    pos_filter = st.multiselect(
        "Position",
        options=["QB", "RB", "WR", "TE"],
        default=["QB", "RB", "WR", "TE"],
        label_visibility="collapsed",
    )

with col_sort:
    sort_col = st.selectbox(
        "Sort by",
        options=["overall_rank", "vbd_surplus", "adp_gap", "adp_overall", "projected_pts", "tier"],
        index=0,
        label_visibility="collapsed",
    )

with col_search:
    name_search = st.text_input("Search player name", placeholder="Search...", label_visibility="collapsed")

# ---------------------------------------------------------------------------
# Load + filter data
# ---------------------------------------------------------------------------

df = load_vbd(config.league_id, config.season, config.scoring.type)

if df.empty:
    st.info("No VBD data yet. Click ↺ Recalc or run prefetch.py first.")
    st.stop()

notes_map = {n["player_id"]: n for n in load_notes(config.league_id)}

# Apply filters
if pos_filter:
    df = df[df["position"].isin(pos_filter)]
if name_search:
    df = df[df["name"].str.contains(name_search, case=False, na=False)]

df = df.sort_values(sort_col, ascending=True if sort_col in ("overall_rank", "adp_overall", "tier") else False)

# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

with col_export:
    csv_cols = ["overall_rank", "tier", "name", "position", "team",
                "projected_pts", "vbd_surplus", "adp_overall", "adp_gap"]
    export_df = df[[c for c in csv_cols if c in df.columns]].copy()
    csv_buf = io.StringIO()
    export_df.to_csv(csv_buf, index=False)
    st.download_button(
        "⬇ CSV",
        data=csv_buf.getvalue(),
        file_name=f"vbd_{config.league_id}_{config.scoring.type}.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.markdown("---")

# ---------------------------------------------------------------------------
# Position color mapping
# ---------------------------------------------------------------------------

POS_COLOR = {
    "QB": "#FF6B6B",   # red-ish
    "RB": "#4ECDC4",   # teal
    "WR": "#45B7D1",   # blue
    "TE": "#96CEB4",   # green
}

POS_BG = {
    "QB": "rgba(255,107,107,0.12)",
    "RB": "rgba(78,205,196,0.12)",
    "WR": "rgba(69,183,209,0.12)",
    "TE": "rgba(150,206,180,0.12)",
}

# ---------------------------------------------------------------------------
# Tier-grouped display
# ---------------------------------------------------------------------------

tiers = sorted(df["tier"].dropna().unique().astype(int))

for tier in tiers:
    tier_df = df[df["tier"] == tier].copy()
    if tier_df.empty:
        continue

    # Tier header with divider
    top_surplus = tier_df["vbd_surplus"].max()
    st.markdown(
        f"<div style='background:#1e1e2e;border-left:4px solid #7c3aed;"
        f"padding:6px 12px;margin:8px 0 4px;border-radius:4px;'>"
        f"<b style='color:#a78bfa'>Tier {tier}</b>"
        f"<span style='color:#6b7280;font-size:0.85em;margin-left:16px'>"
        f"Top surplus: {top_surplus:.1f}</span></div>",
        unsafe_allow_html=True,
    )

    # Column headers (once per tier)
    hdr = st.columns([0.5, 0.7, 2.5, 0.7, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 3.5, 1.0])
    labels = ["Rank", "Tier", "Name", "Pos", "Team", "Proj Pts", "VBD Sur", "ADP", "ADP Gap",
              "Tgt%", "Snap%", "Notes", "Custom Rank"]
    for h, lbl in zip(hdr, labels):
        h.markdown(f"<span style='color:#6b7280;font-size:0.78em'>{lbl}</span>", unsafe_allow_html=True)

    for _, row in tier_df.iterrows():
        pid = str(row.get("id") or row.get("player_id", ""))
        pos = row.get("position", "")
        note_data = notes_map.get(pid, {})
        bg = POS_BG.get(pos, "")
        color = POS_COLOR.get(pos, "#ffffff")

        adp_gap = row.get("adp_gap", 0) or 0
        adp_gap_color = "#4ade80" if adp_gap >= 5 else ("#f87171" if adp_gap <= -5 else "#9ca3af")

        cols = st.columns([0.5, 0.7, 2.5, 0.7, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 3.5, 1.0])
        cols[0].markdown(f"<span style='font-size:0.9em'>{int(row.get('overall_rank',0))}</span>", unsafe_allow_html=True)
        cols[1].markdown(f"<span style='font-size:0.9em'>{int(row.get('tier',0))}</span>", unsafe_allow_html=True)
        cols[2].markdown(
            f"<span style='background:{bg};color:{color};font-weight:600;"
            f"padding:2px 6px;border-radius:3px;font-size:0.9em'>{row.get('name','')}</span>",
            unsafe_allow_html=True,
        )
        cols[3].markdown(f"<span style='color:{color};font-weight:700;font-size:0.85em'>{pos}</span>", unsafe_allow_html=True)
        cols[4].markdown(f"<span style='font-size:0.85em;color:#9ca3af'>{row.get('team','')}</span>", unsafe_allow_html=True)
        cols[5].markdown(f"<span style='font-size:0.85em'>{row.get('projected_pts',0):.1f}</span>", unsafe_allow_html=True)
        cols[6].markdown(f"<span style='font-size:0.85em;font-weight:600'>{row.get('vbd_surplus',0):.1f}</span>", unsafe_allow_html=True)

        adp_val = row.get("adp_overall")
        adp_str = f"{adp_val:.0f}" if adp_val and adp_val < 999 else "—"
        cols[7].markdown(f"<span style='font-size:0.85em;color:#9ca3af'>{adp_str}</span>", unsafe_allow_html=True)
        cols[8].markdown(
            f"<span style='font-size:0.85em;color:{adp_gap_color};font-weight:600'>"
            f"{'+' if adp_gap > 0 else ''}{adp_gap:.0f}</span>",
            unsafe_allow_html=True,
        )

        # Advanced metrics if available
        tgt = row.get("target_share")
        snap = row.get("snap_pct")
        cols[9].markdown(
            f"<span style='font-size:0.8em;color:#9ca3af'>{f'{tgt*100:.0f}%' if tgt else '—'}</span>",
            unsafe_allow_html=True,
        )
        cols[10].markdown(
            f"<span style='font-size:0.8em;color:#9ca3af'>{f'{snap*100:.0f}%' if snap else '—'}</span>",
            unsafe_allow_html=True,
        )

        # Inline notes (text_input with unique key)
        current_note = note_data.get("notes", "")
        new_note = cols[11].text_input(
            "note",
            value=current_note,
            key=f"note_{pid}",
            label_visibility="collapsed",
            placeholder="Add note...",
        )
        if new_note != current_note:
            upsert_player_note({
                "player_id": pid,
                "league_id": config.league_id,
                "notes": new_note,
                "custom_rank": note_data.get("custom_rank", 0),
            })
            load_notes.clear()

        # Custom rank
        current_rank = note_data.get("custom_rank", 0) or 0
        new_rank = cols[12].number_input(
            "rank",
            value=int(current_rank),
            min_value=0,
            max_value=500,
            step=1,
            key=f"rank_{pid}",
            label_visibility="collapsed",
            help="0 = use VBD rank",
        )
        if new_rank != current_rank:
            upsert_player_note({
                "player_id": pid,
                "league_id": config.league_id,
                "notes": new_note,
                "custom_rank": int(new_rank),
            })
            load_notes.clear()

st.markdown("---")

# ---------------------------------------------------------------------------
# Summary charts
# ---------------------------------------------------------------------------

with st.expander("📈 VBD Distribution by Position"):
    chart_df = load_vbd(config.league_id, config.season, config.scoring.type)
    if not chart_df.empty:
        fig = go.Figure()
        for pos in ["QB", "RB", "WR", "TE"]:
            pdata = chart_df[chart_df["position"] == pos]["vbd_surplus"].dropna()
            if not pdata.empty:
                fig.add_trace(go.Box(
                    y=pdata,
                    name=pos,
                    marker_color=POS_COLOR.get(pos, "#888"),
                ))
        fig.update_layout(
            height=350,
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#9ca3af"),
        )
        st.plotly_chart(fig, use_container_width=True)
