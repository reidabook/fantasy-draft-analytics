# Analytics: Scarcity Engine

File: `src/analytics/scarcity.py`

---

## Purpose

Real-time positional scarcity alerts for the draft board. Given the available player
pool and picks until my next turn, classifies each position as RED (critical), YELLOW
(thinning), or GREEN (fine). Drives the warning banner above the draft board.

---

## Main Function

### `compute_scarcity(available_df, my_next_pick_in, positions=("QB","RB","WR","TE")) → Dict[str, dict]`

| Argument | Type | Notes |
|----------|------|-------|
| `available_df` | DataFrame | Undrafted players only, with `vbd_surplus` column |
| `my_next_pick_in` | int | Number of picks until my next turn (0 = it's my pick now) |
| `positions` | tuple | Defaults to all four skill positions |

Returns a dict keyed by position abbreviation:

```python
{
    "RB": {
        "level": "red",    # or "yellow" or "green"
        "count": 4,        # number of quality players remaining
        "threshold": 18.5, # top_surplus * 0.70
        "top_surplus": 26.4,
    },
    "WR": { ... },
    ...
}
```

---

## Algorithm

### Step 1: Identify quality players per position

```python
pos_df = available_df[available_df["position"] == pos]
top_surplus = pos_df["vbd_surplus"].max()
threshold = top_surplus * 0.70
quality_count = (pos_df["vbd_surplus"] >= threshold).sum()
```

"Quality" = at least 70% of the best remaining player's VBD surplus. This dynamically
adjusts as elite players are drafted — the bar drops to maintain relevance.

### Step 2: Classify level

```python
if quality_count < max(1, my_next_pick_in / 2):
    level = "red"    # critical: barely enough quality players to survive the wait
elif quality_count < my_next_pick_in:
    level = "yellow" # thinning: may run out before my turn
else:
    level = "green"  # fine: plenty of quality options will remain
```

**Edge cases:**
- `my_next_pick_in = 0` (it's my pick now): `max(1, 0) = 1`, so RED if 0 quality, else GREEN
- `my_next_pick_in = 1`: RED if quality_count < 1, YELLOW if quality_count < 1 (same boundary, never YELLOW at 1 pick out)
- Empty position (no undrafted players): `top_surplus = NaN` → `threshold = NaN` → `quality_count = 0` → RED

---

## Message Function

### `scarcity_message(pos, info) → str`

```python
def scarcity_message(pos, info):
    level = info["level"]
    count = info["count"]
    if level == "red":
        return f"⚠️ {pos} SCARCE — only {count} quality players left"
    elif level == "yellow":
        return f"⚡ {pos} thinning — {count} quality players remaining"
    else:
        return ""  # GREEN: no message shown
```

Messages appear in the warning bar above the draft board when any position is RED or YELLOW.
GREEN positions produce no output (silence = no concern).

---

## Integration with Draft Board

Called in `pages/4_Draft_Board.py`:

```python
available_df = load_available_players()     # VBD-sorted undrafted players
picks_until = board.picks_until_my_next(current_pick)
scarcity = compute_scarcity(available_df, picks_until)

messages = [scarcity_message(pos, info) for pos, info in scarcity.items()]
messages = [m for m in messages if m]  # filter empty GREEN messages

if messages:
    st.warning(" | ".join(messages))
```

Also consumed by `get_recommendations()` in `recommender.py` to boost the recommendation
score for positions with RED or YELLOW scarcity:

```python
rec_score += 50  # if scarcity["red"] at this position
rec_score += 20  # if scarcity["yellow"] at this position
```

---

## Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| All positions show RED immediately | `my_next_pick_in` too high / wrong pick position | Verify `config.draft.my_pick_position` |
| Scarcity not updating after picks | `available_df` not refreshed (still includes drafted players) | Ensure `get_drafted_player_ids()` is called before filtering |
| YELLOW never appears | `my_next_pick_in` is 0 or 1; math collapses RED/GREEN | Expected behavior at boundary picks |
| Position shows GREEN with 0 players left | `available_df` is pre-filtered somehow | Check filter logic in Draft Board page |
