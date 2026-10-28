# Data: External Fetchers

File: `src/data/fetcher.py`

---

## Overview

All network I/O lives here. Three data sources: Sleeper API (free, no auth), ESPN API
(unofficial package, cookies), FantasyPros (HTML scrape), and nfl_data_py (Python package).

---

## HTTP Utility

### `_get(url, params=None)`

```python
for attempt in range(3):
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()
    # on failure: sleep 2^attempt seconds, retry
```

- 3 attempts total
- 15-second timeout per request
- Exponential backoff: 1s, 2s, 4s between attempts
- Raises on final failure (caller catches)

---

## Sleeper API

Base URL: `https://api.sleeper.app/v1`

No authentication. All endpoints return JSON.

### User & League Endpoints

| Function | Endpoint | Returns |
|----------|----------|---------|
| `sleeper_get_user(username)` | `GET /user/{username}` | `{user_id, ...}` |
| `sleeper_get_leagues(user_id, season)` | `GET /user/{user_id}/leagues/nfl/{season}` | list of league dicts |
| `sleeper_get_league(league_id)` | `GET /league/{league_id}` | league settings dict |

### Player & Stats Endpoints

| Function | Endpoint | Notes |
|----------|----------|-------|
| `sleeper_get_all_players()` | `GET /players/nfl` | ~5MB JSON; refresh weekly |
| `sleeper_get_projections(season, week)` | `GET /projections/nfl/{season}/{week}` | `week=0` = full season |
| `sleeper_get_player_stats(player_id)` | `GET /stats/nfl/player/{player_id}` | Historical actuals |
| `sleeper_get_trending(trend_type)` | `GET /players/nfl/trending/{trend_type}` | `trend_type="add"` for news |

### Draft Endpoints

| Function | Endpoint | Notes |
|----------|----------|-------|
| `sleeper_get_league_drafts(league_id)` | `GET /league/{league_id}/drafts` | Returns list of drafts |
| `sleeper_get_draft_picks(draft_id)` | `GET /draft/{draft_id}/picks` | Completed picks |

WebSocket for live sync (separate module `src/draft/websocket.py`):
`wss://live.sleeper.app/ws/nfl/draft/{draft_id}`

---

## ESPN API

Uses unofficial `espn-api` Python package.

### Credentials

Stored in `.env` — **never committed to git**:
```
ESPN_LEAGUE_ID=XXXXXX
ESPN_S2=AEB...  (long cookie string)
ESPN_SWID={xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}
```

Cookies expire periodically. Re-extract from:
`browser DevTools → Application → Cookies → espn.com`

### Functions

```python
espn_get_league(league_id, year, espn_s2, swid)
    → espn_api.football.League(league_id, year, espn_s2, swid)
    # raises ImportError if espn-api package not installed
    # raises Exception on auth failure (expired cookies)

espn_get_draft_picks(espn_league)
    → iterates espn_league.draft
    → returns list of pick dicts

espn_get_weekly_scores(espn_league, week=None)
    → iterates espn_league.box_scores(week)
    → returns {team_name: score} for every team that week (including the
      "Fake team" — callers exclude it, see src/weekly/payout.py)
```

`league.settings` provides scoring weights and roster slots for `build_league_config_from_espn()`.

### Weekly median override + payout report (`weekly_update.py`)

A separate, in-season automation — not part of the pre-draft app — that runs after
each week's games finish. See `src/weekly/` (`payout.py`, `commish_override.py`,
`notify.py`) and `weekly_update.py` at the repo root. Computes the median of all
real teams' scores (excluding the "Fake team", used to fill an odd-sized league),
overrides the Fake team's ESPN score to that median via Playwright browser
automation (ESPN has no write API for this), and emails a report with the median
and the week's high scorer (for a Venmo payout).

**Venmo pay link**: Venmo has no public API for personal payments, so the payout isn't
sent automatically — the email carries a prefilled pay link instead (recipient, amount,
"Week N high score" note; one tap + confirm in the app). `payout.py::payout_line()` builds
it from `VENMO_HANDLES` (manager label → handle) and `HIGH_SCORE_PAYOUT` (default 5).
Regular season only (`week <= league.settings.reg_season_count`); a tie is flagged with no
link; a winner with no configured handle (e.g. yourself) gets a plain "Venmo them".

The click-path (direct scoreboard URL + matchup lookup by `data-team`/`href` team id,
since the Fake team's opponent/position on the board changes weekly) was found by
inspecting the real live league's DOM and is baked into `src/weekly/commish_override.py`.

**Auth is the one non-obvious part**: cookie-only auth (`espn_s2`/`SWID`) works for
the read-only ESPN API above, but ESPN's website UI needs a fully-established login
session to reach commissioner tools — cookie injection alone gets redirected to a
login page. `weekly_update.py` reuses a saved session from `ESPN_PLAYWRIGHT_STATE_PATH`
(default `.espn_session.json`, gitignored), and if that's missing or has expired,
automatically logs back in via ESPN's Disney OneID iframe form using
`ESPN_USERNAME`/`ESPN_PASSWORD` from `.env` (plaintext — this is the tradeoff for a
cron job that never needs manual re-login) and saves the refreshed session for next
time. `save_espn_session.py` remains available for a one-time manual login if you'd
rather not store the password. If ESPN's page structure itself changes
(`NotConfiguredError`), the override step falls back to reporting the median by email
for a manual override — the payout-winner email still goes out either way.

---

## FantasyPros ADP

FantasyPros does not have a public API. Uses HTML scraping.

### `fantasypros_get_adp()`

```python
FANTASYPROS_ADP_URL = "https://www.fantasypros.com/nfl/adp/overall.php"

html = _get(url)  # gets raw HTML text
match = re.search(r'var ecrData\s*=\s*(\{.*?\});', html, re.DOTALL)
data = json.loads(match.group(1))
# extracts player list with consensus ADP from ecrData JSON blob
```

**Failure behavior:** Returns empty list `[]` on any exception (HTTP error, regex miss,
JSON parse fail). Caller (`fetch_adp()`) detects empty list and falls back to Sleeper proxy.

### Sleeper ADP Fallback

`normalize_sleeper_adp_from_projections()` — converts Sleeper projection ranking order
into a proxy ADP. Less accurate than FantasyPros but always available.

### Local CSV Fallback (manual)

When the live scrape above is blocked, download FantasyPros' "Draft ALL Rankings"
CSV export by hand and feed it to `prefetch.py --local-csv PATH [--local-bye-csv PATH]`
(see `import_fantasypros_local()` in `docs/data/pipeline.md`). Two CSV variants:

| Function | CSV columns | Used for |
|----------|-------------|----------|
| `fantasypros_parse_local_csv(path)` | RK, TIERS, PLAYER NAME, TEAM, FANTASYPTS, pass/rush/rec stat lines | Projections + ADP (rank order) |
| `fantasypros_parse_local_bye_weeks_csv(path)` | RK, TIERS, PLAYER NAME, TEAM, POS, BYE WEEK, UPSIDE, BUST, SOS SEASON, ECR VS. ADP | `players.bye_week` backfill |

---

## nfl_data_py

Python package. All functions wrap `nfl_data_py` directly.

### Functions to Use

| Function | Wraps | Returns |
|----------|-------|---------|
| `nfldata_import_ids()` | `nfl.import_ids()` | ID mapping table (gsis ↔ Sleeper ↔ ESPN) |
| `nfldata_import_seasonal(seasons)` | `nfl.import_seasonal_data(seasons)` | Per-player seasonal metrics |
| `nfldata_import_weekly(seasons)` | `nfl.import_weekly_data(seasons)` | Per-player weekly metrics |
| `nfldata_import_snap_counts(seasons)` | `nfl.import_snap_counts(seasons)` | Snap count per player/week |
| `nfldata_import_schedules(seasons)` | `nfl.import_schedules(seasons)` | Game schedule + opponents |

### ⚠️ DO NOT USE

```python
nfl.import_pbp_data(seasons)  # ~500MB per season — will fill disk
```

`import_seasonal_data` is the primary metrics source (~10MB total for 2 seasons).

### ID Mapping

`nfldata_import_ids()` returns a DataFrame with columns including `gsis_id` and
`sleeper_id`. Used by `build_id_map()` in `transformer.py` to join nfl_data_py
rows (keyed by gsis_id) to Sleeper player IDs (used as primary keys in SQLite).

Without a valid `gsis_id → sleeper_id` mapping, nfl_data_py metrics cannot be
stored in `advanced_metrics` and flags will not be computed.

---

## Common Failure Modes

| Symptom | Cause | Fix |
|---------|-------|-----|
| FantasyPros returns empty ADP | Scrape blocked or HTML structure changed | Falls back to Sleeper proxy automatically |
| ESPN `401 Unauthorized` | Cookies expired | Re-extract ESPN_S2 + SWID from browser |
| Sleeper `/players/nfl` slow | ~5MB payload | Expected; happens weekly only |
| nfl_data_py metrics all NULL | gsis_id mapping missing | Rerun `fetch_nfl_metrics()` after `fetch_players()` |
| `ImportError: espn-api` | Package not installed | `pip install espn-api` |
| `ImportError: nfl_data_py` | Package not installed | `pip install nfl-data-py` |
