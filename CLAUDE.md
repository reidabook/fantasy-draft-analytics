# Fantasy Draft Analytics — CLAUDE.md

AI context briefing for this codebase. Read this before modifying any file.

---

## What This Is

A personal, locally-run Streamlit app for fantasy football draft preparation.
Supports Sleeper and ESPN leagues. All data cached in SQLite. No server required.

**Five Streamlit pages:**
1. League Import — pull settings from Sleeper API or ESPN API
2. VBD Rankings — primary board sorted by Value-Based Drafting surplus
3. Player Research — metrics table, player comparison, radar chart
4. Draft Board — live pick tracker with scarcity alerts and recommendations
5. Sleeper Radar — sleeper/bust/handcuff detection with evidence rows

---

## Architecture

```
app.py (entrypoint + sidebar)
  └── st.session_state["active_league"] = LeagueConfig
        │
        ├── src/config/settings.py    LeagueConfig dataclass + load/save/import
        ├── src/data/
        │     ├── cache.py            SQLite schema + read/write (auto-init on import)
        │     ├── fetcher.py          Sleeper / ESPN / FantasyPros / nfl_data_py clients
        │     ├── transformer.py      Raw API → normalized DataFrames + ID mapping
        │     └── pipeline.py         Orchestrates fetch → transform → cache
        ├── src/analytics/
        │     ├── vbd.py              VBD surplus + tier auto-detection
        │     ├── scarcity.py         Positional scarcity alert engine
        │     ├── flags.py            Sleeper / bust / handcuff detection
        │     └── schedule.py         Playoff weeks 15-17 schedule grades
        └── src/draft/
              ├── board.py            DraftBoard class (stateless, reads SQLite per call)
              ├── recommender.py      Pick recommendation scoring
              └── websocket.py        Sleeper WebSocket live draft sync
```

---

## Critical Conventions

### Session State
`st.session_state["active_league"]` is the single source of truth for the active league.
Every page reads it with `config = st.session_state.get("active_league")` and stops
if it's None. It is a `LeagueConfig` object, not a dict.

### SQLite Database
All data lives in `data/cache/fantasy.db`. The file is auto-created on first import of
`src.data.cache` (the `init_db()` call runs at module level). 8 tables — see
`docs/data/cache-schema.md` for full schema.

**Never read/write the DB file directly.** Use the helper functions in `cache.py`.

### Per-League Data
Every analytics table uses `league_id` as a partition key so two leagues never
contaminate each other's VBD scores, draft picks, or player notes.

### Cache Freshness
`data/cache/.cache_manifest.json` stores last-fetch timestamps per data source.
TTLs: players = 24h, nfl_metrics = 168h, projections = 24h, ADP = 24h.
Players is 24h (not 168h like nfl_metrics) because it carries team/roster-status/
injury designation, which moves daily in-season — nfl_metrics is closed-season
historical data and doesn't need to be that fresh.
`is_stale(key, hours)` / `mark_fetched(key)` / `freshness_label(key)` in `cache.py`.

### The SEASON Constant
`SEASON = 2025` is defined once in `src/data/pipeline.py` and imported everywhere.
Change it here only when rolling to a new season.

### Config File Naming
Leagues are saved as JSON in `config/`:
- Sleeper: `config/sleeper_{league_id}.json`
- ESPN: `config/espn_{league_id}.json`

`list_saved_leagues()` returns all `.json` filenames in `config/`.
`load_config(filename)` deserializes to `LeagueConfig`.

---

## LeagueConfig Dataclass

```python
@dataclass
class LeagueConfig:
    league_id: str
    league_name: str
    platform: str            # "sleeper" | "espn"
    season: int
    teams: int
    scoring: ScoringConfig   # type, reception, passing_yard, ...
    roster_slots: RosterSlots  # QB, RB, WR, TE, FLEX, K, DST, BN
    draft: DraftConfig       # total_rounds, my_pick_position, draft_id

    # draft.my_pick_position / draft.draft_id are resolved from Sleeper's
    # /league/{id}/drafts draft_order on import (build_league_config_from_sleeper);
    # they fall back to the previously-saved value if Sleeper hasn't randomized
    # the draft slots yet (draft_order is null pre-randomization).

    @property
    def replacement_rank(self) -> dict[str, int]:
        # QB: teams × QB
        # RB: teams × (RB + FLEX × 0.5)
        # WR: teams × (WR + FLEX × 0.5)
        # TE: teams × TE
```

This property is the critical input to VBD calculation.

---

## VBD Core Formula

```
projected_pts  = per-player full-season projection (pts_ppr / pts_half_ppr / pts_std)
replacement_pt = projected_pts of the Nth player at position (N = replacement_rank[pos])
vbd_surplus    = max(0, projected_pts − replacement_pt)
adp_gap        = adp_overall_rank − overall_vbd_rank   (positive = undervalued vs consensus)
```

Tiers auto-detected in `vbd.py:_assign_tiers()`: gaps between consecutive VBD values
that exceed `std(vbd_surplus) × 0.5` become tier breaks. Default cap: 8 tiers.

Custom rank overrides: stored in `player_notes.custom_rank` (per-league). Sort key:
`custom_rank if set, else overall_rank + 1000` — custom ranks always sort before defaults.

---

## Draft Board Mechanics

### Snake Draft Math
```python
round_num    = (pick_number - 1) // n_teams + 1
pick_in_rnd  = (pick_number - 1) % n_teams + 1
# Odd rounds: normal order
team = pick_in_rnd
# Even rounds: reversed
team = n_teams - pick_in_rnd + 1
```
Works correctly for asymmetric team counts (e.g., 13-team bounce at pick 7).

### Pick Persistence
`board.mark_pick()` writes to SQLite immediately. `DraftBoard` is stateless — every
method call reads from DB fresh. Survives Streamlit reruns and browser refreshes.

### Recommendation Score
```
rec_score = vbd_surplus
          + scarcity_boost (RED position: +50, YELLOW: +20)
          + need_boost (critical: +30, needed: +15, ok: +5, full: −10)
```

---

## Scarcity Alert Logic

For each position, `quality_count` = players available with `vbd_surplus >= top_surplus × 0.70`.
- RED: `quality_count < max(1, picks_until_my_turn / 2)`
- YELLOW: `quality_count < picks_until_my_turn`
- GREEN: otherwise

---

## Flag Detection Thresholds

**SLEEPER triggers** (any one):
- `target_share` grew YoY > 3% (WR/TE)
- `wopr > 0.4` (WR/TE)
- `snap_pct > 0.75` AND `adp_overall > adp_cutoff_rank` (default 100)
- `carry_share` grew YoY > 5% (RB)

**BUST? triggers** (any one):
- `td_luck > 0.05` — where `td_luck = actual_td_rate − rz_target_share × 0.25`
- `target_share` declining AND `adp_overall < 100`
- `snap_pct < 0.60` AND `adp_overall < 100`
- `depth_chart_pos` contains "backup" AND `adp_overall < 100`

**HC (handcuff) trigger:**
- Position == RB AND `depth_chart_pos` contains "backup"

`flag_summary` column: comma-joined from {"SLEEPER", "BUST?", "HC"}.

---

## Sleeper WebSocket

URL: `wss://live.sleeper.app/ws/nfl/draft/{draft_id}`

`SleeperDraftSync` runs as a daemon thread. Reconnects with exponential backoff
(1s → max 30s). Listens for `data["type"] == "picked"` events. Calls `on_pick(payload)`.

`parse_sleeper_pick(payload)` maps:
- `player_id` → player_id
- `pick_no` → pick_number
- `round` → round_number
- `draft_slot` → pick_in_round
- `roster_id` → team_number

Requires `websockets` package. Raises ImportError with helpful message if missing.

---

## Data Fetch Pipeline

```
prefetch.py --quick                              →  run_quick()   projections (24h TTL) + ADP (24h TTL)
prefetch.py --full                               →  run_full()    players (24h) + projections + ADP + nfl_metrics (168h)
prefetch.py --vbd                                →  recompute_all_vbd()   no fetch, reruns analytics only
prefetch.py --local-csv PATH [--local-bye-csv PATH] →  import_fantasypros_local()   ingest a manually-downloaded
                                                     FantasyPros "Draft ALL Rankings" CSV as PPR projections + ADP
                                                     (source="fantasypros_local"), for when the live scrape in
                                                     fetch_adp() is blocked. Requires players already cached
                                                     (run --full first). Matches by name against the player
                                                     directory; unmatched rows (team DST entries, etc.) are logged
                                                     and skipped. --local-bye-csv backfills players.bye_week from
                                                     the cheat-sheet CSV variant.
```

ADP source priority: FantasyPros → Sleeper projection ordering (if FantasyPros blocked).

`nfl_data_py` uses:
- `nfl.import_ids()` for Sleeper ↔ gsis_id mapping
- `nfl.import_seasonal_data([2023, 2024])` for target_share, snap_pct, WOPR, carry_share
- `nfl.import_weekly_data()` for per-week stats
- **NOT** `import_pbp_data` — it's 500MB and unnecessary

---

## Schedule Grades

Playoff weeks 15-17. Grades: A (easiest matchups) → D (hardest).

`DEFENSE_TIERS` maps NFL team abbreviations to tier letters (A=elite defense = bad matchup,
D=weak defense = good matchup). `grade_from_opponents` averages `{A:4, B:3, C:2, D:1}`:
- avg ≥ 3.5 → D (tough schedule)
- avg ≥ 2.5 → C
- avg ≥ 1.5 → B
- avg < 1.5 → A (easy schedule)

Falls back to "C" for all players if `schedules_df` is None or empty.

---

## File Locations Quick Reference

| What | Where |
|------|-------|
| Entrypoint | `app.py` |
| CLI refresh tool | `prefetch.py` |
| League configs | `config/*.json` |
| SQLite DB | `data/cache/fantasy.db` |
| Cache manifest | `data/cache/.cache_manifest.json` |
| CSV exports | `data/exports/` |
| Credentials template | `.env.template` → copy to `.env` |
| Dependencies | `requirements.txt` |

---

## Docs Index

- `docs/features/league-import.md` — League import UI, Sleeper vs ESPN flows
- `docs/features/vbd-rankings.md` — VBD board, tiers, notes, custom rank, export
- `docs/features/player-research.md` — Search, metrics, comparison, radar
- `docs/features/draft-board.md` — Pick tracker, recommendations, WebSocket sync
- `docs/features/sleeper-radar.md` — Flag tabs, evidence rows, fallback logic
- `docs/data/pipeline.md` — Fetch pipeline, TTLs, FantasyPros fallback
- `docs/data/cache-schema.md` — All 8 SQLite tables with columns and PKs
- `docs/data/fetchers.md` — API clients: Sleeper, ESPN, FantasyPros, nfl_data_py
- `docs/analytics/vbd-engine.md` — VBD formula, replacement math, tier algorithm
- `docs/analytics/flags.md` — Sleeper/bust/handcuff thresholds, td_luck formula
- `docs/analytics/scarcity.md` — Scarcity alert algorithm
- `docs/analytics/schedule.md` — DEFENSE_TIERS, grade computation
