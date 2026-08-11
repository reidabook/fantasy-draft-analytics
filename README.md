# Fantasy Draft Analytics

A personal, locally-run fantasy football analytics tool supporting pre-draft research, live draft assistance, and VBD (Value-Based Drafting) analysis. Supports Sleeper and ESPN leagues.

## Features

- **VBD Rankings** — tiered board with VBD surplus, ADP gap, custom notes and rank overrides
- **Player Research** — full metrics table, side-by-side comparison, radar chart vs positional average
- **Draft Board** — live pick tracker, scarcity alerts, top-3 recommendations, WebSocket auto-sync for Sleeper
- **Sleeper Radar** — sleeper candidates, bust watch, handcuff targets with evidence rows
- **Multi-league** — switch between leagues in the sidebar; VBD recalculated per-league scoring config

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

Copy `.env.template` to `.env` and fill in your values:

```bash
cp .env.template .env
```

```
# Sleeper (no auth needed — just your username)
SLEEPER_USERNAME=your_sleeper_username

# ESPN (required for ESPN leagues only)
ESPN_LEAGUE_ID=123456
ESPN_S2=AEBxxxxxxxx...
ESPN_SWID={xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}
```

**How to get ESPN credentials:**
1. Log in to ESPN Fantasy on the web
2. Open DevTools → Application → Cookies → `espn.com`
3. Copy `espn_s2` cookie value → `ESPN_S2`
4. Copy `SWID` cookie value → `ESPN_SWID` (include the curly braces)
5. Your league ID is in the URL: `fantasy.espn.com/football/league?leagueId=XXXXXX`

### 3. Fetch data

```bash
# Weekly (first time or start of season): pulls player directory + projections + ADP + nfl metrics
python prefetch.py --full

# Daily (during draft prep): updates projections + ADP only
python prefetch.py --quick

# After fetching, recompute VBD for all imported leagues
python prefetch.py --quick --vbd

# Force re-download even if cache is fresh
python prefetch.py --full --force
```

### 4. Launch the app

```bash
streamlit run app.py
```

Open your browser to `http://localhost:8501`. Import your leagues from the League Import page, then switch between them in the sidebar.

---

## Data Sources

| Source | What it provides | Refresh cadence |
|--------|-----------------|-----------------|
| Sleeper API | Player directory, full-season projections, league settings, live draft | Weekly (players), daily (projections) |
| ESPN API (`espn-api`) | League settings, roster slots, scoring weights | On import |
| FantasyPros | Consensus ADP | Daily |
| nfl_data_py | Target share, snap %, WOPR, carry share, EPA | Weekly |

---

## File Structure

```
fantasy/
├── app.py                    # Streamlit entrypoint + sidebar league switcher
├── prefetch.py               # CLI data refresh tool
├── requirements.txt
├── .env                      # Credentials (not committed)
├── .env.template             # Template for above
│
├── config/                   # Saved league configs (JSON)
├── data/
│   ├── cache/fantasy.db      # SQLite: all player/stats/draft/notes data
│   └── exports/              # CSV exports of rankings
│
├── src/
│   ├── config/settings.py    # LeagueConfig dataclass + load/save helpers
│   ├── data/
│   │   ├── fetcher.py        # API clients (Sleeper, ESPN, FantasyPros, nfl_data_py)
│   │   ├── transformer.py    # Raw → normalized DataFrames
│   │   ├── cache.py          # SQLite schema + read/write helpers
│   │   └── pipeline.py       # Orchestrates fetch → transform → cache
│   ├── analytics/
│   │   ├── vbd.py            # VBD surplus calculations
│   │   ├── scarcity.py       # Positional scarcity alerts
│   │   ├── flags.py          # Sleeper/bust/handcuff detection
│   │   └── schedule.py       # Playoff schedule grades (Wks 15-17)
│   └── draft/
│       ├── board.py          # Draft state management (SQLite-persisted)
│       ├── recommender.py    # Pick recommendation engine
│       └── websocket.py      # Sleeper WebSocket live sync
│
└── pages/
    ├── 1_League_Import.py    # Import leagues from Sleeper/ESPN
    ├── 2_VBD_Rankings.py     # Primary tiered board
    ├── 3_Player_Research.py  # Search, compare, radar chart
    ├── 4_Draft_Board.py      # Live draft assistant
    └── 5_Sleeper_Radar.py    # Sleeper/bust/handcuff radar
```

---

## VBD Methodology

**Value-Based Drafting** scores players by their surplus over positional replacement level — not raw projected points. A 200-point RB in a 12-team PPR league is far more valuable than a 250-point QB because the QB position has much more depth.

```
replacement_threshold = n_teams × starter_slots_at_position
  QB: 12 teams × 1 QB = 12th QB
  RB: 12 teams × (2 + 0.5 FLEX) ≈ 30th RB
  WR: 12 teams × (2 + 0.5 FLEX) ≈ 30th WR
  TE: 12 teams × 1 TE = 12th TE

vbd_surplus = player_projected_pts − replacement_player_projected_pts
adp_gap    = adp_overall_rank − vbd_overall_rank  (positive = undervalued vs consensus)
```

VBD is recalculated per-league using each league's exact scoring config and team count.

---

## Draft Day Workflow

1. Run `python prefetch.py --quick --vbd` the morning of your draft
2. Launch `streamlit run app.py`
3. Select your league from the sidebar
4. Go to **Draft Board**
5. For Sleeper leagues: enter your Draft ID and click **Connect WebSocket** — picks auto-sync
6. For ESPN leagues: mark picks manually with the **Mine** / **Other** buttons
7. All picks persist to SQLite — safe to refresh the page at any time

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| No VBD data | Run `prefetch.py --full`, then click ↺ Recalc on VBD Rankings |
| ESPN import fails | Re-extract `espn_s2` + `SWID` cookies (they expire) |
| Sleeper WebSocket drops | Click Disconnect → reconnect; or mark picks manually |
| nfl_data_py metrics missing | Run `prefetch.py --full` (not --quick); metrics require weekly fetch |
| Stale data after re-fetch | Run `prefetch.py --quick --force` to bypass cache TTL |
