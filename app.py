"""
Fantasy Football Draft Analytics — Streamlit entrypoint.
Run with: streamlit run app.py
"""
import os
import streamlit as st
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Must be first Streamlit call
st.set_page_config(
    page_title="Fantasy Draft Analytics",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from src.config.settings import load_config, list_saved_leagues, load_default_config
from src.data.cache import freshness_label, init_db

# Ensure DB exists
init_db()


# ---------------------------------------------------------------------------
# Sidebar — league switcher + data freshness
# ---------------------------------------------------------------------------

def build_sidebar():
    with st.sidebar:
        st.title("🏈 Fantasy Draft")
        st.markdown("---")

        # League selector
        saved = list_saved_leagues()
        league_options = ["(no league imported)"] + saved

        if "selected_league_file" not in st.session_state:
            st.session_state.selected_league_file = saved[0] if saved else None

        selected = st.selectbox(
            "League Name",
            options=league_options,
            index=0 if not saved else 1,
            key="league_selector",
        )

        if selected and selected != "(no league imported)":
            st.session_state.selected_league_file = selected
            config = load_config(selected)
            if config:
                st.session_state.active_league = config
                badge = "🟢 PPR" if config.scoring.type == "ppr" else (
                    "🟡 Half" if config.scoring.type == "half_ppr" else "⚪ Std"
                )
                st.caption(f"{config.platform.upper()} · {config.teams}-team · {badge}")
        else:
            st.session_state.active_league = None

        st.markdown("---")

        # Data freshness
        st.subheader("Data Freshness")
        sources = {
            "Players": "sleeper_players",
            "Projections": "sleeper_projections",
            "ADP": "adp",
            "NFL Metrics": "nfl_metrics",
        }
        for label, key in sources.items():
            fl = freshness_label(key)
            icon = {"fresh": "🟢", "stale": "🟡", "old": "🔴", "never": "⚫"}.get(fl, "⚫")
            st.caption(f"{icon} {label}: {fl}")

        # Refresh buttons
        st.markdown("---")
        if st.button("Run Quick Refresh", use_container_width=True, help="Projections + ADP only (respects 24h cache)"):
            with st.spinner("Refreshing..."):
                from src.data.pipeline import run_quick
                logs = []
                run_quick(log_cb=logs.append)
                for msg in logs:
                    st.caption(msg)
            st.success("Refresh complete")
            st.rerun()

        if st.button("Run Full Refresh", use_container_width=True, help="Players + Projections + ADP + NFL Metrics (respects 7-day cache on Players/NFL Metrics)"):
            with st.spinner("Refreshing everything — this can take a few minutes..."):
                from src.data.pipeline import run_full
                logs = []
                run_full(log_cb=logs.append)
                for msg in logs:
                    st.caption(msg)
            st.success("Full refresh complete — go to VBD Rankings and click ↺ Recalc")
            st.rerun()

        st.markdown("---")
        st.caption("v0.1 · [GitHub](https://github.com)")


build_sidebar()


# ---------------------------------------------------------------------------
# Home page content
# ---------------------------------------------------------------------------

st.title("🏈 Fantasy Draft Analytics")

config = st.session_state.get("active_league")
if config:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("League", config.league_name)
    with col2:
        st.metric("Teams", config.teams)
    with col3:
        st.metric("Scoring", config.scoring.type.replace("_", " ").title())
    with col4:
        st.metric("My Pick", f"#{config.draft.my_pick_position}")

    st.markdown("---")
    st.markdown("""
    ### Quick Navigation
    Use the sidebar to switch between pages:
    - **1 League Import** — Import from Sleeper or ESPN
    - **2 VBD Rankings** — Full tiered board with VBD surplus
    - **3 Player Research** — Deep dive metrics and comparisons
    - **4 Draft Board** — Live draft assistant
    - **5 Sleeper Radar** — Sleeper candidates and bust watch
    """)
else:
    st.info(
        "No league imported yet. Go to **League Import** to connect your Sleeper or ESPN league."
    )
    st.markdown("""
    ### Getting Started
    1. Copy `.env.template` to `.env` and fill in your credentials
    2. Run `python prefetch.py --full` to download player data
    3. Go to **League Import** to connect your league
    4. Open **VBD Rankings** to see your draft board
    """)
