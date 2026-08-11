# Feature: Draft Board (Page 4)

File: `pages/4_Draft_Board.py`

---

## Purpose

Live draft assistant. Tracks all picks (auto-sync for Sleeper via WebSocket, manual
one-click for ESPN), shows real-time scarcity alerts and recommendations, maintains
my roster panel. All state persisted to SQLite — survives page refresh.

---

## Header Metrics

Five columns across the top:

| Metric | Source |
|--------|--------|
| Current Pick # | `board.get_current_pick_number()` |
| Round (X of Y) | `board.pick_number_to_round_and_slot()` |
| Pick in Round (X of N) | same |
| Until My Pick | `board.picks_until_my_next(current_pick)` — shows "MY PICK NOW" if 0 |
| Snake Direction | → odd rounds (normal), ← even rounds (reversed) |

"🎯 IT'S YOUR PICK!" success banner when `board.is_my_pick(current_pick)` is True.

---

## Scarcity Alerts

Computed by `compute_scarcity(available_df, picks_until_mine)` from `src/analytics/scarcity.py`.

Shown as a warning bar above the board when any position is RED or YELLOW:
- 🔴 = position is critically scarce (quality count < half of picks until my turn)
- 🟡 = position thinning (quality count < picks until my turn)

---

## Top 3 Recommendations

Visible only when `is_my_pick` is True. Three cards with colored borders by position.

Each card shows:
- Player name + position + team
- VBD surplus and ADP gap
- One-line reasoning from `_build_reasoning(row, needs, scarcity)`

**Recommendation scoring** (from `get_recommendations()`):
```
rec_score = vbd_surplus
          + 50 (if RED scarcity at this position)
          + 20 (if YELLOW scarcity)
          + 30 (if positional need = critical)
          + 15 (if needed) / +5 (if ok) / −10 (if full)
```

**Reasoning strings** (examples):
- "🚨 {pos} SCARCE — draft now or miss tier"
- "Value pick — ADP +{N} picks above VBD rank"
- "Slight value vs consensus ADP"
- "Reaching — {N} picks below VBD value"
- "Tier {N} player, top of their range"
- "🟢 Flagged as sleeper"

---

## Available Players Table

Left column (3/5 width). Sorted by VBD surplus descending. Shows top 60 players.

**Columns:** Rank | Name | Pos | Team | VBD | ADP | Gap | Action

- Name colored by position; sleeper 🟢 or bust 🔴 flag icon appended
- ADP Gap: green if ≥+5, red if ≤−5, gray otherwise
- **Mine** button: `board.mark_pick(pid, team_number=config.draft.my_pick_position)`
- **Other** button: `board.mark_pick(pid)` — auto-assigns to current team from snake math

Both buttons call `load_vbd_df.clear()` + `st.rerun()` immediately.

**Filters:**
- Position multiselect (default: all four)
- Name search text input

---

## My Team Panel

Right column (2/5 width). Shows picks from `board.get_my_roster()`.

Each entry: `POS | Player Name ... Rd X`

**Positional Needs** grid (4 columns):

Targets: `QB=rs.QB`, `RB=rs.RB+1`, `WR=rs.WR+1`, `TE=rs.TE`, `K=rs.K`, `DST=rs.DST`

Urgency labels:
- **CRITICAL** (red) — 0 at position, 3+ rounds left
- **NEED** (yellow) — below target, rounds remaining
- **OK** (green) — at target
- **FULL** (gray) — above target

---

## Controls

- **↩ Undo Last Pick**: `board.undo()` → deletes highest pick_number row for this league/season
- **🔄 Reset Draft**: two-click confirm (`st.session_state.confirm_reset`) → `board.reset()`

---

## Sleeper WebSocket Sync

Only shown when `config.platform == "sleeper"`.

1. Enter Draft ID (from Sleeper app or URL)
2. Click **Connect WebSocket**
3. `SleeperDraftSync(draft_id, on_pick, on_error)` starts daemon thread
4. `_on_pick(payload)` → `parse_sleeper_pick(payload)` → `board.mark_pick(player_id, team_number)`
5. Status: 🟢 connected / reconnecting automatically with backoff
6. **Disconnect** button stops the thread and clears `st.session_state.ws_sync`

WebSocket URL: `wss://live.sleeper.app/ws/nfl/draft/{draft_id}`

Requires `websockets` package. If missing: `st.error("Install websockets: pip install websockets")`.

---

## Pick History Expander

Bottom of page. Full pick log with all columns:
`Pick# | Round | Slot | Player | Pos | NFL Team | Draft Team | Mine`

Loaded via `board.get_all_picks()` → DataFrame displayed with `st.dataframe`.

---

## DraftBoard Class Internals

`src/draft/board.py` — stateless by design. Every method reads from SQLite fresh.

### Snake Math
```python
round_num   = (pick_number - 1) // n_teams + 1
pick_in_rnd = (pick_number - 1) % n_teams + 1
# Odd round:
team = pick_in_rnd
# Even round:
team = n_teams - pick_in_rnd + 1
```

Handles asymmetric bounce correctly (e.g., 13-team: round 2 pick 1 = team 13).

### Current Pick Number
`max(pick_number) + 1` from `draft_picks` table. Returns 1 if no picks yet.

### My Roster
`SELECT ... FROM draft_picks WHERE league_id=? AND season=? AND is_my_pick=1 ORDER BY pick_number`
then JOINed with `players` for name/position/team.

---

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `src/draft/board.py` | `DraftBoard` class |
| `src/draft/recommender.py` | `get_recommendations` |
| `src/draft/websocket.py` | `SleeperDraftSync`, `parse_sleeper_pick` |
| `src/analytics/scarcity.py` | `compute_scarcity`, `scarcity_message` |
| `src/data/cache.py` | `get_vbd_scores`, `get_draft_picks`, `upsert_vbd_scores` |
| `src/analytics/vbd.py` | `compute_vbd`, `vbd_to_db_rows` (for inline recalc) |

---

## Common Issues

| Symptom | Fix |
|---------|-----|
| WebSocket drops mid-draft | Click Disconnect → reconnect; or mark picks manually |
| Picks disappeared after refresh | Should NOT happen — all picks in SQLite; check `draft_picks` table |
| "MY PICK NOW" not showing | Verify `config.draft.my_pick_position` matches your actual draft slot |
| Recommendations not appearing | Only shown on your turn; check pick position is set correctly |
| Undo removed wrong pick | Undo always removes highest pick_number (most recent) |
