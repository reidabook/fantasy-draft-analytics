# Feature: League Import (Page 1)

File: `pages/1_League_Import.py`

---

## Purpose

Pull league settings from Sleeper or ESPN, persist them as JSON config files, and
optionally recalculate VBD immediately after import. Also provides an inline editor
for any setting that auto-import gets wrong.

---

## Sleeper Import Flow

1. User enters Sleeper username in text input
2. On submit: `import_sleeper_league(username, log_cb=logs.append)` in `src/data/fetcher.py`
   - Calls `GET /user/{username}` → gets `user_id`
   - Calls `GET /user/{user_id}/leagues/nfl/{season}` → list of leagues
   - For each league: builds `LeagueConfig` via `build_league_config_from_sleeper()`
   - Saves each to `config/sleeper_{league_id}.json`
   - Returns `List[LeagueConfig]`
3. Success: logs show each league name + scoring type + team count
4. Error: shown inline; most common cause is wrong username

**No credentials required for Sleeper** — username only.

---

## ESPN Import Flow

1. User enters:
   - League ID (from URL: `fantasy.espn.com/football/league?leagueId=XXXXXX`)
   - ESPN_S2 cookie (long string starting with `AEB...`)
   - SWID cookie (format: `{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}`)
   - Inputs are `type="password"` to avoid accidental screen share exposure
2. On submit: sets `os.environ["ESPN_LEAGUE_ID"]`, `os.environ["ESPN_S2"]`, `os.environ["ESPN_SWID"]`
3. Calls `import_espn_league(log_cb=logs.append)` in `src/data/fetcher.py`
   - Uses `espn_api.football.League(league_id, year, espn_s2, swid)`
   - Extracts `league.settings` for scoring weights and roster slots
   - Builds `LeagueConfig` via `build_league_config_from_espn()`
   - Saves to `config/espn_{league_id}.json`
4. Credentials are NOT persisted to disk — user must re-enter each session (or set in `.env`)

**ESPN cookies expire.** Re-extract from DevTools → Application → Cookies → espn.com if import fails.

---

## Saved Leagues Section

Below the import forms, all saved configs appear in a selectbox.
Selecting one loads the full `LeagueConfig` for inline editing:
- League name (display only)
- Teams count
- Scoring type (ppr / half_ppr / standard)
- My draft pick position
- Roster slots (QB, RB, WR, TE, FLEX, K, DST, BN)

**Save Changes + Recalculate VBD** button:
1. Saves modified config back to `config/*.json` via `save_config(config)`
2. Loads players, projections, ADP from SQLite
3. Runs `compute_vbd(players, projs, adp, config, notes)` inline
4. Writes results via `upsert_vbd_scores(db_rows)`

This means you can tweak scoring weights and see VBD instantly without re-fetching data.

**Replacement Rank expander**: shows `config.replacement_rank` as JSON to confirm the
VBD threshold calculation (e.g., `{"QB": 10, "RB": 25, "WR": 25, "TE": 10}` for a
10-team PPR league with standard roster).

---

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `src/config/settings.py` | `LeagueConfig`, `list_saved_leagues`, `load_config`, `save_config` |
| `src/data/fetcher.py` | `import_sleeper_league`, `import_espn_league` |
| `src/data/cache.py` | `get_all_players`, `get_projections`, `get_adp`, `upsert_vbd_scores`, `get_all_player_notes` |
| `src/analytics/vbd.py` | `compute_vbd`, `vbd_to_db_rows` |
| `src/data/pipeline.py` | `SEASON` constant |

---

## Common Issues

| Symptom | Fix |
|---------|-----|
| Sleeper import: "user not found" | Check spelling — Sleeper username is case-sensitive |
| ESPN import: `401 Unauthorized` | ESPN_S2 / SWID cookies have expired; re-extract from browser |
| VBD recalc: "No player data" | Run `python prefetch.py --full` first |
| Roster slots look wrong after import | Edit inline and click Save Changes + Recalculate VBD |
