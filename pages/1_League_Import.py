"""
Page 1: League Import
Auto-import from Sleeper or ESPN + manual settings override.
"""
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src.config.settings import (
    LeagueConfig, ScoringConfig, RosterSlots, DraftConfig,
    load_config, save_config, list_saved_leagues,
)
from src.data.pipeline import import_sleeper_league, import_espn_league

st.set_page_config(page_title="League Import", layout="wide")
st.title("🏟️ League Import")


# ---------------------------------------------------------------------------
# Sleeper import
# ---------------------------------------------------------------------------

st.header("Sleeper Import")
username = st.text_input(
    "Sleeper Username",
    value=os.getenv("SLEEPER_USERNAME", ""),
    placeholder="your_sleeper_username",
)

col1, col2 = st.columns([2, 5])
with col1:
    do_import_sleeper = st.button("Import from Sleeper", type="primary", use_container_width=True)

if do_import_sleeper:
    if not username:
        st.error("Enter your Sleeper username first")
    else:
        logs = []
        with st.spinner("Connecting to Sleeper..."):
            try:
                configs = import_sleeper_league(username, log_cb=logs.append)
                for msg in logs:
                    st.caption(msg)
                st.success(f"Imported {len(configs)} league(s) from Sleeper")
                for c in configs:
                    st.write(f"- **{c.league_name}** ({c.teams} teams, {c.scoring.type.upper()})")
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")
                for msg in logs:
                    st.caption(msg)

st.markdown("---")


# ---------------------------------------------------------------------------
# ESPN import
# ---------------------------------------------------------------------------

st.header("ESPN Import")
espn_league_id = st.text_input(
    "ESPN League ID",
    value=os.getenv("ESPN_LEAGUE_ID", ""),
    placeholder="your_espn_league_id",
)

with st.expander("ESPN Cookie credentials (espn_s2 + SWID)"):
    st.markdown("""
    **How to get your ESPN cookies:**
    1. Log in to ESPN Fantasy Football in Chrome
    2. Open DevTools (F12) → Network tab
    3. Click any page in ESPN Fantasy
    4. Find any request to espn.com → Headers → Request Headers → Cookie
    5. Copy `espn_s2=...` and `SWID={...}` into your `.env` file
    """)
    espn_s2 = st.text_input("espn_s2", value=os.getenv("ESPN_S2", ""), type="password")
    espn_swid = st.text_input("SWID", value=os.getenv("ESPN_SWID", ""), type="password")

do_import_espn = st.button("Import from ESPN", use_container_width=False)

if do_import_espn:
    if not espn_league_id:
        st.error("Enter your ESPN League ID")
    else:
        os.environ["ESPN_LEAGUE_ID"] = espn_league_id
        os.environ["ESPN_S2"] = espn_s2
        os.environ["ESPN_SWID"] = espn_swid
        logs = []
        with st.spinner("Connecting to ESPN..."):
            try:
                config = import_espn_league(log_cb=logs.append)
                for msg in logs:
                    st.caption(msg)
                st.success(f"Imported: {config.league_name}")
                st.rerun()
            except Exception as e:
                st.error(f"ESPN import failed: {e}")
                for msg in logs:
                    st.caption(msg)

st.markdown("---")


# ---------------------------------------------------------------------------
# Saved leagues — view + edit settings
# ---------------------------------------------------------------------------

st.header("Saved Leagues")
saved = list_saved_leagues()
if not saved:
    st.info("No leagues imported yet.")
else:
    selected_file = st.selectbox("Select a league to view/edit", saved)
    config = load_config(selected_file)

    if config:
        st.subheader(f"Settings: {config.league_name}")

        col1, col2, col3 = st.columns(3)
        with col1:
            new_name = st.text_input("League Name", value=config.league_name)
            new_teams = st.number_input("# Teams", value=config.teams, min_value=8, max_value=20)
        with col2:
            scoring_options = ["ppr", "half_ppr", "standard"]
            new_scoring = st.selectbox(
                "Scoring Type",
                scoring_options,
                index=scoring_options.index(config.scoring.type),
            )
            new_rec = {"ppr": 1.0, "half_ppr": 0.5, "standard": 0.0}[new_scoring]
        with col3:
            new_pick = st.number_input(
                "My Draft Pick Position",
                value=config.draft.my_pick_position,
                min_value=1,
                max_value=config.teams,
            )

        st.subheader("Roster Slots")
        rc1, rc2, rc3, rc4, rc5, rc6 = st.columns(6)
        with rc1:
            new_qb = st.number_input("QB", value=config.roster_slots.QB, min_value=0, max_value=3)
        with rc2:
            new_rb = st.number_input("RB", value=config.roster_slots.RB, min_value=0, max_value=5)
        with rc3:
            new_wr = st.number_input("WR", value=config.roster_slots.WR, min_value=0, max_value=5)
        with rc4:
            new_te = st.number_input("TE", value=config.roster_slots.TE, min_value=0, max_value=3)
        with rc5:
            new_flex = st.number_input("FLEX", value=config.roster_slots.FLEX, min_value=0, max_value=4)
        with rc6:
            new_bn = st.number_input("BN", value=config.roster_slots.BN, min_value=3, max_value=15)

        do_save = st.button("Save Changes + Recalculate VBD", type="primary")
        if do_save:
            config.league_name = new_name
            config.teams = int(new_teams)
            config.draft.my_pick_position = int(new_pick)
            config.scoring.type = new_scoring
            config.scoring.reception = new_rec
            config.roster_slots.QB = int(new_qb)
            config.roster_slots.RB = int(new_rb)
            config.roster_slots.WR = int(new_wr)
            config.roster_slots.TE = int(new_te)
            config.roster_slots.FLEX = int(new_flex)
            config.roster_slots.BN = int(new_bn)
            save_config(config, selected_file)

            # Recalculate VBD with new settings
            from src.data.cache import get_all_players, get_projections, get_adp, upsert_vbd_scores, get_all_player_notes
            from src.analytics.vbd import compute_vbd, vbd_to_db_rows
            players = get_all_players(positions=["QB", "RB", "WR", "TE"], platform=config.platform)
            projs = get_projections(season=config.season, week=0)
            adp = get_adp(season=config.season)
            notes = get_all_player_notes(config.league_id)
            if players and projs:
                vbd_df = compute_vbd(players, projs, adp, config, notes)
                db_rows = vbd_to_db_rows(vbd_df, config.league_id, config.season, config.scoring.type)
                upsert_vbd_scores(db_rows)
                st.success(f"Saved and recalculated VBD for {len(db_rows)} players")
            else:
                st.warning("Saved settings. Run prefetch.py first to populate player/projection data.")
            st.rerun()

        # Show current imported settings summary
        with st.expander("Replacement level thresholds (auto-computed)"):
            rl = config.replacement_rank
            st.json(rl)
