"""
SQLite cache layer: schema creation, read/write helpers, invalidation.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent.parent.parent / "data" / "cache" / "fantasy.db"
MANIFEST_PATH = Path(__file__).parent.parent.parent / "data" / "cache" / ".cache_manifest.json"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    position TEXT,
    team TEXT,
    age INTEGER,
    depth_chart_pos TEXT,
    injury_status TEXT,
    gsis_id TEXT,
    sleeper_id TEXT,
    espn_id TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS projections (
    player_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,          -- 0 = full season
    source TEXT,
    pts_ppr REAL,
    pts_half_ppr REAL,
    pts_std REAL,
    pass_yd REAL,
    pass_td REAL,
    rush_yd REAL,
    rush_td REAL,
    rec REAL,
    rec_yd REAL,
    rec_td REAL,
    updated_at TEXT,
    PRIMARY KEY (player_id, season, week, source)
);

CREATE TABLE IF NOT EXISTS advanced_metrics (
    player_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    snap_pct REAL,
    target_share REAL,
    air_yards_share REAL,
    wopr REAL,
    carry_share REAL,
    rz_target_share REAL,
    epa_per_play REAL,
    td_luck REAL,
    updated_at TEXT,
    PRIMARY KEY (player_id, season)
);

CREATE TABLE IF NOT EXISTS adp (
    player_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    source TEXT NOT NULL,
    adp_overall REAL,
    adp_ppr REAL,
    adp_half_ppr REAL,
    adp_std REAL,
    updated_at TEXT,
    PRIMARY KEY (player_id, season, source)
);

CREATE TABLE IF NOT EXISTS vbd_scores (
    player_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    scoring_type TEXT NOT NULL,
    projected_pts REAL,
    replacement_pts REAL,
    vbd_surplus REAL,
    position_rank INTEGER,
    overall_rank INTEGER,
    adp_gap REAL,
    tier INTEGER,
    updated_at TEXT,
    PRIMARY KEY (player_id, league_id, season, scoring_type)
);

CREATE TABLE IF NOT EXISTS draft_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    league_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    pick_number INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    pick_in_round INTEGER NOT NULL,
    player_id TEXT,
    team_number INTEGER,
    is_my_pick INTEGER DEFAULT 0,
    noted_at TEXT,
    UNIQUE(league_id, season, pick_number)
);

CREATE TABLE IF NOT EXISTS historical_stats (
    player_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    games INTEGER,
    pts_ppr_per_game REAL,
    targets INTEGER,
    carries INTEGER,
    receptions INTEGER,
    rush_yards INTEGER,
    rec_yards INTEGER,
    tds INTEGER,
    updated_at TEXT,
    PRIMARY KEY (player_id, season)
);

CREATE TABLE IF NOT EXISTS player_notes (
    player_id TEXT NOT NULL,
    league_id TEXT NOT NULL,
    notes TEXT,
    custom_rank INTEGER,
    updated_at TEXT,
    PRIMARY KEY (player_id, league_id)
);

CREATE TABLE IF NOT EXISTS schedule_grades (
    player_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    playoff_week_15_opp TEXT,
    playoff_week_16_opp TEXT,
    playoff_week_17_opp TEXT,
    schedule_grade TEXT,
    updated_at TEXT,
    PRIMARY KEY (player_id, season)
);
"""


@contextmanager
def get_conn():
    """Context manager yielding a SQLite connection with row_factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript(SCHEMA_SQL)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(players)").fetchall()}
        if "bye_week" not in cols:
            conn.execute("ALTER TABLE players ADD COLUMN bye_week INTEGER")


# ---------------------------------------------------------------------------
# Manifest helpers (cache freshness)
# ---------------------------------------------------------------------------

def _load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    return {}


def _save_manifest(manifest: dict) -> None:
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def mark_fetched(source_key: str) -> None:
    """Record that a data source was just fetched."""
    manifest = _load_manifest()
    manifest[source_key] = datetime.utcnow().isoformat()
    _save_manifest(manifest)


def get_last_fetched(source_key: str) -> Optional[datetime]:
    """Return when a source was last fetched, or None."""
    manifest = _load_manifest()
    ts = manifest.get(source_key)
    if ts:
        return datetime.fromisoformat(ts)
    return None


def is_stale(source_key: str, max_age_hours: int = 24) -> bool:
    """Return True if source hasn't been fetched within max_age_hours."""
    last = get_last_fetched(source_key)
    if last is None:
        return True
    return datetime.utcnow() - last > timedelta(hours=max_age_hours)


def freshness_label(source_key: str) -> str:
    """Return 'fresh' / 'stale' / 'old' label for UI display."""
    last = get_last_fetched(source_key)
    if last is None:
        return "never"
    age = datetime.utcnow() - last
    if age < timedelta(hours=24):
        return "fresh"
    elif age < timedelta(days=7):
        return "stale"
    return "old"


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

def upsert_players(players: List[Dict[str, Any]]) -> None:
    # ON CONFLICT DO UPDATE (not INSERT OR REPLACE) so columns not passed here
    # — bye_week, set separately via upsert_bye_weeks() — aren't wiped back to
    # NULL on every refetch of the base player directory.
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO players
                (id, name, position, team, age, depth_chart_pos, injury_status,
                 gsis_id, sleeper_id, espn_id, updated_at)
            VALUES
                (:id, :name, :position, :team, :age, :depth_chart_pos, :injury_status,
                 :gsis_id, :sleeper_id, :espn_id, :updated_at)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, position=excluded.position, team=excluded.team,
                age=excluded.age, depth_chart_pos=excluded.depth_chart_pos,
                injury_status=excluded.injury_status, gsis_id=excluded.gsis_id,
                sleeper_id=excluded.sleeper_id, espn_id=excluded.espn_id,
                updated_at=excluded.updated_at
            """,
            [{**p, "updated_at": datetime.utcnow().isoformat()} for p in players],
        )


def upsert_bye_weeks(bye_weeks: Dict[str, int]) -> None:
    """bye_weeks: {player_id: bye_week}."""
    with get_conn() as conn:
        conn.executemany(
            "UPDATE players SET bye_week=? WHERE id=?",
            [(wk, pid) for pid, wk in bye_weeks.items()],
        )


def get_all_players(positions: Optional[List[str]] = None, platform: Optional[str] = None) -> List[dict]:
    """
    platform: when given, filters to one source's player directory. The
    `players` table is shared across all leagues regardless of platform, and
    Sleeper (numeric id) and ESPN (id="espn_{espn_id}") entries for the same
    real athlete are never cross-linked/deduped — including both in one
    league's VBD board shows every player twice. "sleeper" excludes espn_*
    ids; "espn" includes only espn_* ids.
    """
    clauses = []
    params: list = []
    if positions:
        placeholders = ",".join("?" * len(positions))
        clauses.append(f"position IN ({placeholders})")
        params.extend(positions)
    if platform == "sleeper":
        clauses.append("id NOT LIKE 'espn\\_%' ESCAPE '\\'")
    elif platform == "espn":
        clauses.append("id LIKE 'espn\\_%' ESCAPE '\\'")

    query = "SELECT * FROM players"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------

def upsert_projections(projections: List[Dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO projections
                (player_id, season, week, source, pts_ppr, pts_half_ppr, pts_std,
                 pass_yd, pass_td, rush_yd, rush_td, rec, rec_yd, rec_td, updated_at)
            VALUES
                (:player_id, :season, :week, :source, :pts_ppr, :pts_half_ppr, :pts_std,
                 :pass_yd, :pass_td, :rush_yd, :rush_td, :rec, :rec_yd, :rec_td, :updated_at)
            """,
            [{**p, "updated_at": datetime.utcnow().isoformat()} for p in projections],
        )


def get_projections(season: int, week: int = 0, source: Optional[str] = None) -> List[dict]:
    with get_conn() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM projections WHERE season=? AND week=? AND source=?",
                (season, week, source),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM projections WHERE season=? AND week=?",
                (season, week),
            ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Advanced metrics
# ---------------------------------------------------------------------------

def upsert_advanced_metrics(metrics: List[Dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO advanced_metrics
                (player_id, season, snap_pct, target_share, air_yards_share, wopr,
                 carry_share, rz_target_share, epa_per_play, td_luck, updated_at)
            VALUES
                (:player_id, :season, :snap_pct, :target_share, :air_yards_share, :wopr,
                 :carry_share, :rz_target_share, :epa_per_play, :td_luck, :updated_at)
            """,
            [{**m, "updated_at": datetime.utcnow().isoformat()} for m in metrics],
        )


def get_latest_metrics_season() -> Optional[int]:
    """
    Return the most recent season with cached advanced_metrics, or None.
    Historical metrics (nfl_data_py) lag the upcoming draft season by a year
    or more, so callers computing YoY trends should anchor to this instead of
    the league's own (future) season.
    """
    with get_conn() as conn:
        row = conn.execute("SELECT MAX(season) AS s FROM advanced_metrics").fetchone()
    return row["s"] if row and row["s"] is not None else None


def get_advanced_metrics(season: int) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM advanced_metrics WHERE season=?", (season,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# ADP
# ---------------------------------------------------------------------------

def upsert_adp(adp_rows: List[Dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO adp
                (player_id, season, source, adp_overall, adp_ppr, adp_half_ppr, adp_std, updated_at)
            VALUES
                (:player_id, :season, :source, :adp_overall, :adp_ppr, :adp_half_ppr, :adp_std, :updated_at)
            """,
            [{**a, "updated_at": datetime.utcnow().isoformat()} for a in adp_rows],
        )


def get_adp(season: int, source: Optional[str] = None) -> List[dict]:
    with get_conn() as conn:
        if source:
            rows = conn.execute(
                "SELECT * FROM adp WHERE season=? AND source=?", (season, source)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM adp WHERE season=?", (season,)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# VBD scores
# ---------------------------------------------------------------------------

def upsert_vbd_scores(vbd_rows: List[Dict[str, Any]]) -> None:
    """
    Each call recomputes the FULL board for one (league_id, season,
    scoring_type) from the current player pool — never incremental — so
    stale rows for that key are deleted first. Without this, a player_id
    dropped from a later recompute (e.g. after the Sleeper/ESPN platform
    filter fix) would linger forever as a duplicate row alongside the
    player's current, correctly-filtered entry.
    """
    keys = {(v["league_id"], v["season"], v["scoring_type"]) for v in vbd_rows}
    with get_conn() as conn:
        conn.executemany(
            "DELETE FROM vbd_scores WHERE league_id=? AND season=? AND scoring_type=?",
            list(keys),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO vbd_scores
                (player_id, league_id, season, scoring_type, projected_pts, replacement_pts,
                 vbd_surplus, position_rank, overall_rank, adp_gap, tier, updated_at)
            VALUES
                (:player_id, :league_id, :season, :scoring_type, :projected_pts, :replacement_pts,
                 :vbd_surplus, :position_rank, :overall_rank, :adp_gap, :tier, :updated_at)
            """,
            [{**v, "updated_at": datetime.utcnow().isoformat()} for v in vbd_rows],
        )


def get_vbd_scores(league_id: str, season: int, scoring_type: str) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT v.*, p.name, p.position, p.team, p.age, p.injury_status, p.depth_chart_pos,
                   p.bye_week, a.adp_overall
            FROM vbd_scores v
            JOIN players p ON v.player_id = p.id
            LEFT JOIN (
                SELECT player_id, MIN(adp_overall) AS adp_overall
                FROM adp WHERE season=?
                GROUP BY player_id
            ) a ON a.player_id = v.player_id
            WHERE v.league_id=? AND v.season=? AND v.scoring_type=?
            ORDER BY v.overall_rank ASC
            """,
            (season, league_id, season, scoring_type),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Draft picks
# ---------------------------------------------------------------------------

def upsert_draft_pick(pick: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO draft_picks
                (league_id, season, pick_number, round_number, pick_in_round,
                 player_id, team_number, is_my_pick, noted_at)
            VALUES
                (:league_id, :season, :pick_number, :round_number, :pick_in_round,
                 :player_id, :team_number, :is_my_pick, :noted_at)
            """,
            {**pick, "noted_at": datetime.utcnow().isoformat()},
        )


def get_draft_picks(league_id: str, season: int) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT dp.*, p.name, p.position, p.team, p.bye_week
            FROM draft_picks dp
            LEFT JOIN players p ON dp.player_id = p.id
            WHERE dp.league_id=? AND dp.season=?
            ORDER BY dp.pick_number ASC
            """,
            (league_id, season),
        ).fetchall()
    return [dict(r) for r in rows]


def undo_last_pick(league_id: str, season: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM draft_picks WHERE league_id=? AND season=?
            ORDER BY pick_number DESC LIMIT 1
            """,
            (league_id, season),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM draft_picks WHERE id=?", (row["id"],)
            )
            return dict(row)
    return None


def delete_draft_pick(league_id: str, season: int, pick_id: int) -> Optional[dict]:
    """Remove a single pick by its row id, regardless of when it was made."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM draft_picks WHERE id=? AND league_id=? AND season=?",
            (pick_id, league_id, season),
        ).fetchone()
        if row:
            conn.execute("DELETE FROM draft_picks WHERE id=?", (pick_id,))
            return dict(row)
    return None


def get_drafted_player_ids(league_id: str, season: int) -> set:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT player_id FROM draft_picks WHERE league_id=? AND season=? AND player_id IS NOT NULL",
            (league_id, season),
        ).fetchall()
    return {r["player_id"] for r in rows}


# ---------------------------------------------------------------------------
# Player notes
# ---------------------------------------------------------------------------

def get_player_note(player_id: str, league_id: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM player_notes WHERE player_id=? AND league_id=?",
            (player_id, league_id),
        ).fetchone()
    return dict(row) if row else {"player_id": player_id, "league_id": league_id, "notes": "", "custom_rank": None}


def upsert_player_note(player_id: str, league_id: str, notes: str = "", custom_rank: Optional[int] = None) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO player_notes (player_id, league_id, notes, custom_rank, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (player_id, league_id, notes, custom_rank, datetime.utcnow().isoformat()),
        )


def get_all_player_notes(league_id: str) -> Dict[str, dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM player_notes WHERE league_id=?", (league_id,)
        ).fetchall()
    return {r["player_id"]: dict(r) for r in rows}


# ---------------------------------------------------------------------------
# Schedule grades
# ---------------------------------------------------------------------------

def upsert_schedule_grades(grades: List[Dict[str, Any]]) -> None:
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO schedule_grades
                (player_id, season, playoff_week_15_opp, playoff_week_16_opp,
                 playoff_week_17_opp, schedule_grade, updated_at)
            VALUES
                (:player_id, :season, :playoff_week_15_opp, :playoff_week_16_opp,
                 :playoff_week_17_opp, :schedule_grade, :updated_at)
            """,
            [{**g, "updated_at": datetime.utcnow().isoformat()} for g in grades],
        )


# Ensure DB is initialized when module is imported
init_db()
