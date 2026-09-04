"""
Page 4: Draft Board
Live draft assistant — pick tracker, scarcity alerts, recommendations, my roster.
Sleeper: WebSocket auto-sync. ESPN: manual one-click.
All state persisted to SQLite.
"""
from __future__ import annotations

import time
import streamlit as st
import pandas as pd

st.set_page_config(page_title="Draft Board", layout="wide")
st.title("🏟️ Draft Board")

from src.config.settings import LeagueConfig
from src.data.cache import (
    get_vbd_scores, get_all_players, get_projections, get_adp,
    upsert_vbd_scores, get_draft_picks, get_advanced_metrics, get_latest_metrics_season,
)
from src.analytics.vbd import compute_vbd, vbd_to_db_rows
from src.analytics.scarcity import compute_scarcity, scarcity_message
from src.analytics.flags import flag_players
from src.draft.board import DraftBoard
from src.draft.recommender import get_recommendations

# ---------------------------------------------------------------------------
# Require active league
# ---------------------------------------------------------------------------

config: LeagueConfig | None = st.session_state.get("active_league")
if not config:
    st.info("Select a league in the sidebar first.")
    st.stop()

board = DraftBoard(config)

# ---------------------------------------------------------------------------
# Sleeper WebSocket session management
# ---------------------------------------------------------------------------

def _init_ws():
    """Initialize WebSocket sync for Sleeper leagues."""
    if config.platform != "sleeper":
        return

    if "ws_sync" not in st.session_state:
        st.session_state.ws_sync = None

    # Fetch draft_id if not cached
    if "sleeper_draft_id" not in st.session_state:
        st.session_state.sleeper_draft_id = config.draft.draft_id if hasattr(config.draft, "draft_id") else None


_init_ws()

# ---------------------------------------------------------------------------
# Load VBD data (available players)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=30, show_spinner=False)
def load_vbd_df(league_id: str, season: int, scoring_type: str) -> pd.DataFrame:
    rows = get_vbd_scores(league_id, season, scoring_type)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # flag_players() (sleeper/bust/handcuff detection) expects an 'id' column
    # (compute_vbd's own convention); get_vbd_scores() returns 'player_id'.
    df = df.rename(columns={"player_id": "id"})
    metrics_season = get_latest_metrics_season()
    if metrics_season is not None:
        metrics_df = pd.DataFrame(get_advanced_metrics(metrics_season))
        prior_df = pd.DataFrame(get_advanced_metrics(metrics_season - 1))
    else:
        metrics_df, prior_df = pd.DataFrame(), None
    return flag_players(df, metrics_df, prior_df)


def get_available_df(board: DraftBoard) -> pd.DataFrame:
    df = load_vbd_df(config.league_id, config.season, config.scoring.type)
    if df.empty:
        return df
    drafted = board.get_drafted_player_ids()
    pid_col = "id" if "id" in df.columns else "player_id"
    avail = df[~df[pid_col].isin(drafted)].copy()
    return avail.sort_values("vbd_surplus", ascending=False)


# ---------------------------------------------------------------------------
# Top controls bar
# ---------------------------------------------------------------------------

current_pick = board.get_current_pick_number()
round_num, pick_in_round = board.pick_number_to_round_and_slot(current_pick)
picks_until_mine = board.picks_until_my_next(current_pick)
is_my_pick = board.is_my_pick(current_pick)

# Header metrics
h1, h2, h3, h4, h5 = st.columns(5)
h1.metric("Current Pick", f"#{current_pick}")
h2.metric("Round", f"{round_num} of {config.draft.total_rounds}")
h3.metric("Pick in Round", f"{pick_in_round} of {config.teams}")
h4.metric("Until My Pick", f"{picks_until_mine} picks" if picks_until_mine > 0 else "MY PICK NOW")
direction = "→" if round_num % 2 == 1 else "←"
h5.metric("Snake Direction", direction)

if is_my_pick:
    st.success("🎯 **IT'S YOUR PICK!**")

st.markdown("---")

# ---------------------------------------------------------------------------
# Scarcity alerts
# ---------------------------------------------------------------------------

available_df = get_available_df(board)
if not available_df.empty:
    scarcity = compute_scarcity(available_df, picks_until_mine)
    alert_parts = []
    for pos, info in scarcity.items():
        if info["level"] == "red":
            alert_parts.append(f"🔴 **{pos}** {scarcity_message(pos, info)}")
        elif info["level"] == "yellow":
            alert_parts.append(f"🟡 **{pos}** {scarcity_message(pos, info)}")
    if alert_parts:
        st.warning("  ·  ".join(alert_parts))
else:
    scarcity = {}

# ---------------------------------------------------------------------------
# Top 3 Recommendations
# ---------------------------------------------------------------------------

if is_my_pick and not available_df.empty:
    st.subheader("💡 Recommendations for Your Pick")
    recs = get_recommendations(available_df, board, scarcity, top_n=3)
    rec_cols = st.columns(3)
    for i, rec in enumerate(recs):
        with rec_cols[i]:
            pos_colors = {"QB": "#FF6B6B", "RB": "#4ECDC4", "WR": "#45B7D1", "TE": "#96CEB4"}
            color = pos_colors.get(rec["position"], "#888")
            st.markdown(
                f"<div style='border:2px solid {color};border-radius:8px;padding:12px;height:140px;'>"
                f"<div style='color:{color};font-weight:700;font-size:1.1em'>{rec['name']}</div>"
                f"<div style='color:#9ca3af;font-size:0.8em'>{rec['position']} · {rec['team']}</div>"
                f"<div style='margin-top:6px;font-size:0.85em'>"
                f"VBD: <b>{rec['vbd_surplus']}</b> &nbsp;|&nbsp; "
                f"ADP Gap: <b>{'+' if rec['adp_gap']>0 else ''}{rec['adp_gap']}</b>"
                f"</div>"
                f"<div style='margin-top:6px;color:#d1d5db;font-size:0.78em;font-style:italic'>{rec['reasoning']}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("")

st.markdown("---")

# ---------------------------------------------------------------------------
# Main layout: available players (left) | my team (right)
# ---------------------------------------------------------------------------

left_col, right_col = st.columns([3, 2])

# ---------------------------------------------------------------------------
# LEFT: Available players
# ---------------------------------------------------------------------------

with left_col:
    st.subheader("Available Players")
    st.markdown(
        "<div style='color:#6b7280;font-size:0.85em;margin-bottom:4px'>"
        "🟢 Sleeper &nbsp;·&nbsp; 🔴 Bust risk &nbsp;·&nbsp; 🤝 Handcuff &nbsp;&nbsp;|&nbsp;&nbsp; "
        "Gap: <span style='color:#4ade80'>green</span> = value vs ADP, "
        "<span style='color:#f87171'>red</span> = reach vs ADP"
        "</div>",
        unsafe_allow_html=True,
    )

    # Filters
    fc1, fc2, fc3, fc4 = st.columns([2, 3, 1, 1])
    with fc1:
        pos_filter = st.multiselect(
            "Position",
            options=["QB", "RB", "WR", "TE"],
            default=["QB", "RB", "WR", "TE"],
            label_visibility="collapsed",
        )
    with fc2:
        name_filter = st.text_input("Search", placeholder="Player name...", label_visibility="collapsed")
    with fc3:
        sleeper_only = st.checkbox("🟢 Sleepers", help="Show only SLEEPER-flagged players")
    with fc4:
        handcuff_only = st.checkbox("🤝 Handcuffs", help="Show only HC-flagged players")

    disp_df = available_df.copy()
    if pos_filter:
        disp_df = disp_df[disp_df["position"].isin(pos_filter)]
    if name_filter:
        disp_df = disp_df[disp_df["name"].str.contains(name_filter, case=False, na=False)]
    if sleeper_only and "is_sleeper" in disp_df.columns:
        disp_df = disp_df[disp_df["is_sleeper"] == True]
    if handcuff_only and "is_handcuff" in disp_df.columns:
        disp_df = disp_df[disp_df["is_handcuff"] == True]

    if disp_df.empty:
        st.info("No players match filter.")
    else:
        pid_col = "id" if "id" in disp_df.columns else "player_id"

        # Table header
        th = st.columns([0.5, 2.0, 0.6, 0.5, 0.7, 0.6, 0.8, 0.8, 0.9, 1.5])
        for col, lbl in zip(th, ["Rank", "Name", "Pos", "Tier", "Team", "Bye", "VBD", "ADP", "Gap", "Action"]):
            col.markdown(f"<span style='color:#6b7280;font-size:0.8em'>{lbl}</span>", unsafe_allow_html=True)

        POS_COLOR = {"QB": "#FF6B6B", "RB": "#4ECDC4", "WR": "#45B7D1", "TE": "#96CEB4"}

        for _, row in disp_df.head(60).iterrows():
            pid = str(row.get(pid_col, ""))
            pos = row.get("position", "")
            color = POS_COLOR.get(pos, "#888")
            adp_gap = row.get("adp_gap", 0) or 0
            gap_color = "#4ade80" if adp_gap >= 5 else ("#f87171" if adp_gap <= -5 else "#9ca3af")
            adp_val = row.get("adp_overall")
            adp_str = f"{adp_val:.0f}" if adp_val and adp_val < 999 else "—"
            bye_val = row.get("bye_week")
            bye_str = f"{int(bye_val)}" if pd.notna(bye_val) else "—"
            flag = str(row.get("flag_summary", ""))
            flag_icons = []
            if "SLEEPER" in flag:
                flag_icons.append("🟢")
            if "BUST" in flag:
                flag_icons.append("🔴")
            if "HC" in flag:
                flag_icons.append("🤝")
            flag_icon = "".join(flag_icons)

            tier_val = row.get("tier")
            tier_str = f"{int(tier_val)}" if pd.notna(tier_val) else "—"

            tc = st.columns([0.5, 2.0, 0.6, 0.5, 0.7, 0.6, 0.8, 0.8, 0.9, 1.5])
            tc[0].markdown(f"<span style='font-size:0.85em;color:#9ca3af'>{int(row.get('overall_rank',0))}</span>", unsafe_allow_html=True)
            tc[1].markdown(
                f"<span style='color:{color};font-weight:600;font-size:0.9em'>{row.get('name','')} {flag_icon}</span>",
                unsafe_allow_html=True,
            )
            tc[2].markdown(f"<span style='color:{color};font-size:0.85em;font-weight:700'>{pos}</span>", unsafe_allow_html=True)
            tc[3].markdown(f"<span style='font-size:0.85em;color:#9ca3af'>{tier_str}</span>", unsafe_allow_html=True)
            tc[4].markdown(f"<span style='font-size:0.85em;color:#9ca3af'>{row.get('team','')}</span>", unsafe_allow_html=True)
            tc[5].markdown(f"<span style='font-size:0.85em;color:#9ca3af'>{bye_str}</span>", unsafe_allow_html=True)
            tc[6].markdown(f"<span style='font-size:0.85em'>{row.get('vbd_surplus',0):.1f}</span>", unsafe_allow_html=True)
            tc[7].markdown(f"<span style='font-size:0.85em;color:#9ca3af'>{adp_str}</span>", unsafe_allow_html=True)
            tc[8].markdown(
                f"<span style='font-size:0.85em;color:{gap_color};font-weight:600'>"
                f"{'+' if adp_gap > 0 else ''}{adp_gap:.0f}</span>",
                unsafe_allow_html=True,
            )

            # Draft buttons
            btn_col1, btn_col2 = tc[9].columns(2)
            if btn_col1.button("Mine", key=f"mine_{pid}", help="Draft to my team"):
                board.mark_pick(pid, team_number=config.draft.my_pick_position)
                load_vbd_df.clear()
                st.rerun()
            if btn_col2.button("Other", key=f"other_{pid}", help="Draft to another team"):
                # team_number=0 is a sentinel meaning "not me, unspecified team" -
                # never equals a real 1..n_teams slot, so this can never be
                # mistaken for my pick even if snake-slot math or config drifts.
                board.mark_pick(pid, team_number=0)
                load_vbd_df.clear()
                st.rerun()

# ---------------------------------------------------------------------------
# RIGHT: My team + controls
# ---------------------------------------------------------------------------

with right_col:
    st.subheader("My Team")

    my_roster = board.get_my_roster()
    needs = board.positional_needs()

    if not my_roster:
        st.info("No picks yet. Start drafting!")
    else:
        SLOT_ORDER = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DST", "BN"]
        POS_COLOR = {"QB": "#FF6B6B", "RB": "#4ECDC4", "WR": "#45B7D1", "TE": "#96CEB4", "K": "#FBBF24", "DST": "#A78BFA"}

        # Bye-week stacking: flag any week where 2+ starters (non-K/DST) share a bye
        bye_counts: dict = {}
        for pick in my_roster:
            wk = pick.get("bye_week")
            pos = pick.get("position", "?")
            if wk and pos not in ("K", "DST"):
                bye_counts[wk] = bye_counts.get(wk, 0) + 1
        stacked_byes = {wk: n for wk, n in bye_counts.items() if n >= 2}
        if stacked_byes:
            parts = ", ".join(f"Week {wk} ({n} players)" for wk, n in sorted(stacked_byes.items()))
            st.warning(f"⚠️ Bye week stacking: {parts}")

        for pick in my_roster:
            pos = pick.get("position", "?")
            name = pick.get("name", pick.get("player_id", "?"))
            rnd = pick.get("round_number", "?")
            bye = pick.get("bye_week")
            bye_str = f"Bye {int(bye)}" if pd.notna(bye) else ""
            color = POS_COLOR.get(pos, "#888")

            row_col, btn_col = st.columns([6, 1])
            row_col.markdown(
                f"<div style='display:flex;gap:8px;align-items:center;margin:2px 0;'>"
                f"<span style='color:{color};font-weight:700;font-size:0.8em;width:30px'>{pos}</span>"
                f"<span style='font-size:0.9em'>{name}</span>"
                f"<span style='color:#6b7280;font-size:0.72em;width:50px'>{bye_str}</span>"
                f"<span style='color:#6b7280;font-size:0.75em;margin-left:auto'>Rd {rnd}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if btn_col.button("✕", key=f"remove_{pick['id']}", help=f"Remove {name} from my team"):
                board.remove_pick(pick["id"])
                load_vbd_df.clear()
                st.rerun()

    st.markdown("---")

    # Positional needs
    st.subheader("Positional Needs")
    need_cols = st.columns(4)
    need_colors = {"critical": "#f87171", "needed": "#fbbf24", "ok": "#4ade80", "full": "#6b7280"}
    need_labels = {"critical": "CRITICAL", "needed": "NEED", "ok": "OK", "full": "FULL"}
    for i, (pos, urgency) in enumerate(needs.items()):
        with need_cols[i % 4]:
            color = need_colors.get(urgency, "#888")
            st.markdown(
                f"<div style='text-align:center;padding:4px;border:1px solid {color};border-radius:4px;margin:2px;'>"
                f"<div style='font-weight:700;color:#e5e7eb'>{pos}</div>"
                f"<div style='color:{color};font-size:0.75em'>{need_labels.get(urgency,'')}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # Draft controls
    st.subheader("Controls")

    ctrl1, ctrl2 = st.columns(2)
    with ctrl1:
        if st.button("↩ Undo Last Pick", use_container_width=True):
            undone = board.undo()
            if undone:
                st.success(f"Undone: pick #{undone.get('pick_number')}")
                load_vbd_df.clear()
                st.rerun()
            else:
                st.warning("No picks to undo.")
    with ctrl2:
        if st.button("🔄 Reset Draft", use_container_width=True, type="secondary"):
            if st.session_state.get("confirm_reset"):
                board.reset()
                st.session_state.confirm_reset = False
                load_vbd_df.clear()
                st.rerun()
            else:
                st.session_state.confirm_reset = True
                st.warning("Click Reset again to confirm.")

    # Sleeper WebSocket
    if config.platform == "sleeper":
        st.markdown("---")
        st.subheader("Live Sleeper Sync")
        draft_id = st.session_state.get("sleeper_draft_id") or ""
        draft_id_input = st.text_input("Draft ID", value=draft_id, placeholder="Sleeper draft ID")
        if draft_id_input:
            st.session_state.sleeper_draft_id = draft_id_input

        ws = st.session_state.get("ws_sync")
        ws_connected = ws is not None and ws.connected

        if ws_connected:
            st.success("🟢 WebSocket connected — picks auto-sync")
            if st.button("Disconnect", use_container_width=True):
                ws.stop()
                st.session_state.ws_sync = None
                st.rerun()
        else:
            if st.button("Connect WebSocket", use_container_width=True, type="primary"):
                if not draft_id_input:
                    st.error("Enter a Draft ID first")
                else:
                    try:
                        from src.draft.websocket import SleeperDraftSync, parse_sleeper_pick

                        def _on_pick(payload: dict):
                            pick_data = parse_sleeper_pick(payload)
                            board.mark_pick(
                                player_id=pick_data["player_id"],
                                team_number=pick_data["team_number"],
                            )

                        def _on_error(msg: str):
                            pass  # Logged internally; UI shows status via ws.connected

                        new_ws = SleeperDraftSync(
                            draft_id=draft_id_input,
                            on_pick=_on_pick,
                            on_error=_on_error,
                        )
                        new_ws.start()
                        st.session_state.ws_sync = new_ws
                        time.sleep(1)  # Brief wait for connection
                        st.rerun()
                    except ImportError:
                        st.error("Install websockets: pip install websockets")

# ---------------------------------------------------------------------------
# Pick history
# ---------------------------------------------------------------------------

st.markdown("---")
with st.expander("📋 Full Pick History"):
    all_picks = board.get_all_picks()
    if not all_picks:
        st.info("No picks recorded yet.")
    else:
        picks_df = pd.DataFrame(all_picks)
        display_picks = picks_df[["pick_number", "round_number", "pick_in_round",
                                   "name", "position", "team", "team_number", "is_my_pick"]].copy()
        display_picks["is_my_pick"] = display_picks["is_my_pick"].apply(lambda x: "✓" if x else "")
        display_picks.columns = ["Pick#", "Round", "Slot", "Player", "Pos", "NFL Team", "Draft Team", "Mine"]
        st.dataframe(display_picks, use_container_width=True, hide_index=True)
