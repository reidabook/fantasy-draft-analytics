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
│   ├── draft/
│   │   ├── board.py          # Draft state management (SQLite-persisted)
│   │   ├── recommender.py    # Pick recommendation engine
│   │   └── websocket.py      # Sleeper WebSocket live sync
│   └── weekly/                       # In-season: median override + payout report
│       ├── payout.py                 # Median / high-scorer logic (pure, unit-tested)
│       ├── commish_override.py       # Playwright: ESPN commissioner score override
│       ├── notify.py                 # Email report (Gmail SMTP)
│       └── imessage.py               # Snarky group-text builder + Messages.app sender
│
├── weekly_update.py          # CLI: run the weekly median override + payout report
├── save_espn_session.py      # One-time/periodic manual ESPN login for Playwright
├── list_imessage_chats.py    # One-time: find your league group chat's id
├── send_group_text.py        # Send the group text weekly_update.py staged, after approval
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

## In-Season: Weekly Median Override + Payout Report

For leagues with an odd number of real teams padded out with a "Fake team": after each
week's games finish, `weekly_update.py` fetches every team's score, computes the median
(excluding the Fake team), overrides the Fake team's ESPN score to that median, and
emails you the median plus the week's high scorer (for a Venmo payout). See
`docs/data/fetchers.md` for the full design.

### One-time setup

```bash
# 1. Install Playwright's browser binary (already in requirements.txt)
playwright install chromium

# 2. Add to .env (see .env.template):
#    FAKE_TEAM_NAME=Fake team          # must match the ESPN team name exactly
#    FAKE_TEAM_ID=...                  # ESPN team id, from .../team?...&teamId=N
#    GMAIL_ADDRESS=you@gmail.com
#    GMAIL_APP_PASSWORD=...            # https://myaccount.google.com/apppasswords
#    ESPN_USERNAME=...                 # for automatic re-login when the session expires
#    ESPN_PASSWORD=...                 # stored in plaintext — the tradeoff for a fully
#                                       # unattended cron job; see docs/data/fetchers.md

# 3. Log into ESPN once so the Playwright automation has a real session to reuse
#    (cookie-only auth works for reads but not for the commissioner website UI).
#    Optional if ESPN_USERNAME/ESPN_PASSWORD are set above — the automation will
#    log in on its own the first time and whenever the session later expires.
python save_espn_session.py
```

### Running it

```bash
python weekly_update.py --week 3 --dry-run   # fills the ESPN form, never submits, no email/text
python weekly_update.py --week 3             # real run: overrides + emails the report
python weekly_update.py                      # defaults to the most recently completed week
```

If `IMESSAGE_GROUP_CHAT_ID` is set, a real run also stages a snarky group-text
summary at `logs/pending_group_text.txt` and prints it — it is **not** sent
automatically. Review it, then send it with:

```bash
python send_group_text.py
```

(Re-running `weekly_update.py` regenerates that file; you can also hand-edit
it before sending — `send_group_text.py` just sends whatever's in it.)

### Running it manually each week (current setup)

The saved ESPN session (`.espn_session.json`) eventually expires, and headless
auto-relogin via `ESPN_USERNAME`/`ESPN_PASSWORD` turned out to be unreliable
(ESPN's login flow appears to hit a verification step that a scripted login
can't get past). Rather than fight that, the current setup is manual: each
week, log in once and run the update —

```bash
python save_espn_session.py     # only if weekly_update.py reports the session expired
python weekly_update.py         # defaults to the most recently completed week
```

### Automate it instead (cron, Tuesday mornings)

The code still fully supports unattended cron — pick this back up if you'd
rather not run it by hand. `ESPN_USERNAME`/`ESPN_PASSWORD` in `.env` enable
best-effort auto-relogin (may not always get past ESPN's verification step,
but the weekly email still reports the median/high-scorer either way and
tells you if a manual `save_espn_session.py` run is needed). Only add the
cron job after a real (non-dry-run) test run has been verified against
ESPN's site by hand — this writes to a live league:

```bash
crontab -e
# Add:
0 9 * * 2 cd /Users/reidfrancis/projects/fantasy-draft-analytics && .venv/bin/python weekly_update.py >> logs/weekly_update.log 2>&1
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| No VBD data | Run `prefetch.py --full`, then click ↺ Recalc on VBD Rankings |
| ESPN import fails | Re-extract `espn_s2` + `SWID` cookies (they expire) |
| Sleeper WebSocket drops | Click Disconnect → reconnect; or mark picks manually |
| nfl_data_py metrics missing | Run `prefetch.py --full` (not --quick); metrics require weekly fetch |
| Stale data after re-fetch | Run `prefetch.py --quick --force` to bypass cache TTL |
| `weekly_update.py` raises `NotConfiguredError` | Selectors not recorded yet — run `playwright codegen` and fill in `src/weekly/commish_override.py` |
| `weekly_update.py` email says override failed | ESPN cookies likely expired, or ESPN changed its UI — re-extract cookies or re-record selectors; median is still reported for a manual override |
