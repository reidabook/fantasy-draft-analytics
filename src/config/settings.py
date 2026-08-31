"""
League configuration: dataclass, load/save, and import helpers.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Optional

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ScoringConfig:
    type: str = "ppr"                # "ppr", "half_ppr", "standard"
    reception: float = 1.0
    passing_yard: float = 0.04
    rushing_yard: float = 0.1
    receiving_yard: float = 0.1
    pass_td: float = 4.0
    rush_td: float = 6.0
    rec_td: float = 6.0
    two_point_conversion: float = 2.0
    fumble_lost: float = -2.0
    interception: float = -2.0


@dataclass
class RosterSlots:
    QB: int = 1
    RB: int = 2
    WR: int = 2
    TE: int = 1
    FLEX: int = 1
    K: int = 1
    DST: int = 1
    BN: int = 6

    def starters_at(self, position: str) -> float:
        """Return number of starter slots for a position (FLEX counts 0.5 for RB/WR/TE)."""
        direct = getattr(self, position, 0)
        flex_share = 0.0
        if position in ("RB", "WR", "TE"):
            flex_share = self.FLEX * (1.0 / 3.0)  # distribute flex equally by default
        return direct + flex_share


@dataclass
class DraftConfig:
    type: str = "snake"
    total_rounds: int = 15
    my_pick_position: int = 6


@dataclass
class LeagueConfig:
    league_id: str = ""
    league_name: str = "My League 2025"
    platform: str = "sleeper"       # "sleeper" or "espn"
    season: int = 2025
    teams: int = 12
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    roster_slots: RosterSlots = field(default_factory=RosterSlots)
    draft: DraftConfig = field(default_factory=DraftConfig)

    # Replacement thresholds (auto-computed from teams + roster_slots)
    @property
    def replacement_rank(self) -> Dict[str, int]:
        """Return replacement player rank by position based on league settings."""
        n = self.teams
        rs = self.roster_slots
        return {
            "QB": int(n * rs.QB),
            "RB": int(n * (rs.RB + rs.FLEX * 0.5)),
            "WR": int(n * (rs.WR + rs.FLEX * 0.5)),
            "TE": int(n * (rs.TE + rs.FLEX * 0.0)),  # TE rarely fills FLEX
        }

    def to_dict(self) -> dict:
        return {
            "league_id": self.league_id,
            "league_name": self.league_name,
            "platform": self.platform,
            "season": self.season,
            "teams": self.teams,
            "scoring": asdict(self.scoring),
            "roster_slots": asdict(self.roster_slots),
            "draft": asdict(self.draft),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LeagueConfig":
        scoring = ScoringConfig(**data.get("scoring", {}))
        roster_slots_data = data.get("roster_slots", {})
        # Filter to only known fields
        known = {f for f in RosterSlots.__dataclass_fields__}
        roster_slots = RosterSlots(**{k: v for k, v in roster_slots_data.items() if k in known})
        draft = DraftConfig(**data.get("draft", {}))
        return cls(
            league_id=data.get("league_id", ""),
            league_name=data.get("league_name", "My League 2025"),
            platform=data.get("platform", "sleeper"),
            season=data.get("season", 2025),
            teams=data.get("teams", 12),
            scoring=scoring,
            roster_slots=roster_slots,
            draft=draft,
        )


def _config_path(filename: str) -> Path:
    return CONFIG_DIR / filename


def load_config(filename: str) -> Optional[LeagueConfig]:
    """Load a league config from JSON. Returns None if file doesn't exist."""
    path = _config_path(filename)
    if not path.exists():
        return None
    with open(path) as f:
        return LeagueConfig.from_dict(json.load(f))


def save_config(config: LeagueConfig, filename: str) -> None:
    """Save a league config to JSON."""
    path = _config_path(filename)
    with open(path, "w") as f:
        json.dump(config.to_dict(), f, indent=2)


def load_default_config() -> LeagueConfig:
    """Load the default config template."""
    path = _config_path("default_config.json")
    if path.exists():
        with open(path) as f:
            return LeagueConfig.from_dict(json.load(f))
    return LeagueConfig()


def list_saved_leagues() -> list[str]:
    """Return list of saved league config filenames (excluding default)."""
    return [
        f.name for f in CONFIG_DIR.glob("*.json")
        if f.name not in ("default_config.json",)
    ]


def build_league_config_from_sleeper(league_data: dict, user_settings: dict) -> LeagueConfig:
    """
    Convert raw Sleeper API league response into a LeagueConfig.
    league_data: full league object from /league/{league_id}
    user_settings: dict with optional overrides (my_pick_position, etc.)
    """
    settings = league_data.get("settings", {})
    scoring_settings = league_data.get("scoring_settings", {})
    roster_positions = league_data.get("roster_positions", [])

    # Count roster slots
    slot_counts: Dict[str, int] = {}
    for pos in roster_positions:
        slot_counts[pos] = slot_counts.get(pos, 0) + 1

    # Map Sleeper position names to our schema
    roster_slots = RosterSlots(
        QB=slot_counts.get("QB", 1),
        RB=slot_counts.get("RB", 2),
        WR=slot_counts.get("WR", 2),
        TE=slot_counts.get("TE", 1),
        FLEX=slot_counts.get("FLEX", 1) + slot_counts.get("REC_FLEX", 0),
        K=slot_counts.get("K", 1),
        DST=slot_counts.get("DEF", 1),
        BN=slot_counts.get("BN", 6),
    )

    # Determine scoring type
    rec_pts = scoring_settings.get("rec", 0.0)
    if rec_pts >= 1.0:
        scoring_type = "ppr"
    elif rec_pts >= 0.5:
        scoring_type = "half_ppr"
    else:
        scoring_type = "standard"

    scoring = ScoringConfig(
        type=scoring_type,
        reception=rec_pts,
        passing_yard=scoring_settings.get("pass_yd", 0.04),
        rushing_yard=scoring_settings.get("rush_yd", 0.1),
        receiving_yard=scoring_settings.get("rec_yd", 0.1),
        pass_td=scoring_settings.get("pass_td", 4.0),
        rush_td=scoring_settings.get("rush_td", 6.0),
        rec_td=scoring_settings.get("rec_td", 6.0),
        two_point_conversion=scoring_settings.get("2pt", 2.0),
        fumble_lost=scoring_settings.get("fum_lost", -2.0),
        interception=scoring_settings.get("int", -2.0),
    )

    total_rosters = settings.get("num_teams", 12)
    total_rounds = sum(slot_counts.values())

    return LeagueConfig(
        league_id=league_data.get("league_id", ""),
        league_name=league_data.get("name", "Sleeper League"),
        platform="sleeper",
        season=int(league_data.get("season", 2025)),
        teams=total_rosters,
        scoring=scoring,
        roster_slots=roster_slots,
        draft=DraftConfig(
            type="snake",
            total_rounds=total_rounds,
            my_pick_position=user_settings.get("my_pick_position", 6),
        ),
    )


def build_league_config_from_espn(espn_league, user_settings: dict) -> LeagueConfig:
    """
    Convert espn_api League object into a LeagueConfig.
    espn_league: espn_api.football.League instance
    """
    settings = espn_league.settings
    scoring_settings = getattr(settings, "scoring_type", "")

    # espn-api scoring type is a string: "PPR", "HALF_PPR", "STANDARD"
    scoring_type_map = {"PPR": "ppr", "HALF_PPR": "half_ppr", "STANDARD": "standard"}
    scoring_type = scoring_type_map.get(scoring_settings.upper(), "half_ppr")
    rec_pts = {"ppr": 1.0, "half_ppr": 0.5, "standard": 0.0}[scoring_type]

    roster_map = getattr(settings, "position_slot_counts", {})

    roster_slots = RosterSlots(
        QB=roster_map.get("QB", 1),
        RB=roster_map.get("RB", 2),
        WR=roster_map.get("WR", 2),
        TE=roster_map.get("TE", 1),
        FLEX=roster_map.get("RB/WR/TE", 1),
        K=roster_map.get("K", 1),
        DST=roster_map.get("D/ST", 1),
        BN=roster_map.get("BE", 6),
    )

    scoring = ScoringConfig(
        type=scoring_type,
        reception=rec_pts,
        passing_yard=0.04,
        rushing_yard=0.1,
        receiving_yard=0.1,
        pass_td=4.0,
        rush_td=6.0,
        rec_td=6.0,
        two_point_conversion=2.0,
        fumble_lost=-2.0,
        interception=-2.0,
    )

    total_rounds = sum([
        roster_slots.QB, roster_slots.RB, roster_slots.WR, roster_slots.TE,
        roster_slots.FLEX, roster_slots.K, roster_slots.DST, roster_slots.BN
    ])

    return LeagueConfig(
        league_id=str(espn_league.league_id),
        league_name=getattr(settings, "name", "ESPN League"),
        platform="espn",
        season=espn_league.year,
        teams=len(espn_league.teams),
        scoring=scoring,
        roster_slots=roster_slots,
        draft=DraftConfig(
            type="snake",
            total_rounds=total_rounds,
            my_pick_position=user_settings.get("my_pick_position", 7),
        ),
    )
