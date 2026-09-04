"""
Draft board state management.
Handles pick tracking, snake turn calculation, roster management.
All state persisted to SQLite — survives Streamlit reruns.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.data import cache
from src.config.settings import LeagueConfig


class DraftBoard:
    """
    Manages draft state for one league.
    All writes go immediately to SQLite.
    """

    def __init__(self, config: LeagueConfig):
        self.config = config
        self.league_id = config.league_id
        self.season = config.season
        self.n_teams = config.teams
        self.total_rounds = config.draft.total_rounds
        self.my_pick_position = config.draft.my_pick_position

    # -----------------------------------------------------------------------
    # Pick mechanics
    # -----------------------------------------------------------------------

    def pick_number_to_round_and_slot(self, pick_number: int) -> Tuple[int, int]:
        """Convert overall pick number to (round, pick_in_round)."""
        round_num = (pick_number - 1) // self.n_teams + 1
        pick_in_round = (pick_number - 1) % self.n_teams + 1
        return round_num, pick_in_round

    def round_and_slot_to_pick_number(self, round_num: int, pick_in_round: int) -> int:
        return (round_num - 1) * self.n_teams + pick_in_round

    def team_number_for_pick(self, pick_number: int) -> int:
        """
        Snake draft: even rounds reverse direction.
        Handles asymmetric bounce for odd team counts (13-team, 15-team, etc.).
        """
        round_num, pick_in_round = self.pick_number_to_round_and_slot(pick_number)
        if round_num % 2 == 1:  # odd round: normal order
            return pick_in_round
        else:  # even round: reversed
            return self.n_teams - pick_in_round + 1

    def is_my_pick(self, pick_number: int) -> bool:
        return self.team_number_for_pick(pick_number) == self.my_pick_position

    def all_my_picks(self) -> List[int]:
        """Return all pick numbers in the draft that belong to me."""
        total_picks = self.n_teams * self.total_rounds
        return [p for p in range(1, total_picks + 1) if self.is_my_pick(p)]

    def next_my_pick_after(self, current_pick: int) -> Optional[int]:
        """Return the next pick number that's mine, after current_pick."""
        for p in self.all_my_picks():
            if p > current_pick:
                return p
        return None

    def picks_until_my_next(self, current_pick: int) -> int:
        """How many picks until my next turn (0 = it's my pick now)."""
        next_pick = self.next_my_pick_after(current_pick - 1)
        if next_pick is None:
            return 999
        return max(0, next_pick - current_pick)

    # -----------------------------------------------------------------------
    # State from SQLite
    # -----------------------------------------------------------------------

    def get_all_picks(self) -> List[dict]:
        return cache.get_draft_picks(self.league_id, self.season)

    def get_current_pick_number(self) -> int:
        """Return the next pick number to be made."""
        picks = self.get_all_picks()
        if not picks:
            return 1
        return max(p["pick_number"] for p in picks) + 1

    def get_drafted_player_ids(self) -> set:
        return cache.get_drafted_player_ids(self.league_id, self.season)

    def get_my_roster(self) -> List[dict]:
        """Return picks that were made by my team."""
        return [p for p in self.get_all_picks() if p["is_my_pick"]]

    def my_roster_positions(self) -> Dict[str, int]:
        """Count of positions already drafted for my team."""
        counts = {}
        for pick in self.get_my_roster():
            pos = pick.get("position", "?")
            counts[pos] = counts.get(pos, 0) + 1
        return counts

    def positional_needs(self) -> Dict[str, str]:
        """
        Return urgency level per position: 'critical', 'needed', 'ok', 'full'.
        Based on roster slots vs already drafted.
        """
        rs = self.config.roster_slots
        have = self.my_roster_positions()
        needs = {}
        targets = {"QB": rs.QB, "RB": rs.RB + 1, "WR": rs.WR + 1, "TE": rs.TE, "K": rs.K, "DST": rs.DST}
        for pos, target in targets.items():
            drafted = have.get(pos, 0)
            remaining = target - drafted
            if remaining <= 0:
                needs[pos] = "full"
            elif remaining == 1 and pos in ("QB", "TE", "K", "DST"):
                needs[pos] = "critical"
            elif remaining >= 2:
                needs[pos] = "needed"
            else:
                needs[pos] = "ok"
        return needs

    # -----------------------------------------------------------------------
    # Write operations
    # -----------------------------------------------------------------------

    def mark_pick(self, player_id: str, team_number: Optional[int] = None) -> dict:
        """
        Mark a player as drafted. Auto-determines pick number, round, slot, and is_my_pick.
        Returns the pick dict.
        """
        current = self.get_current_pick_number()
        round_num, pick_in_round = self.pick_number_to_round_and_slot(current)
        if team_number is None:
            team_number = self.team_number_for_pick(current)
        is_mine = team_number == self.my_pick_position

        pick = {
            "league_id": self.league_id,
            "season": self.season,
            "pick_number": current,
            "round_number": round_num,
            "pick_in_round": pick_in_round,
            "player_id": player_id,
            "team_number": team_number,
            "is_my_pick": 1 if is_mine else 0,
        }
        cache.upsert_draft_pick(pick)
        return pick

    def undo(self) -> Optional[dict]:
        """Undo the last pick. Returns the undone pick dict, or None."""
        return cache.undo_last_pick(self.league_id, self.season)

    def remove_pick(self, pick_id: int) -> Optional[dict]:
        """Remove a specific pick (any position in the draft, not just the last one)."""
        return cache.delete_draft_pick(self.league_id, self.season, pick_id)

    def reset(self) -> None:
        """Clear all draft picks for this league/season."""
        with cache.get_conn() as conn:
            conn.execute(
                "DELETE FROM draft_picks WHERE league_id=? AND season=?",
                (self.league_id, self.season),
            )
