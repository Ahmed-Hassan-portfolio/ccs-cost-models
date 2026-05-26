"""SQLite scenario persistence -- save and query past scenario runs.

Stores every evaluate_scenario() result in a local SQLite database for:
- Comparison across sessions
- Regression detection
- Exact reproduction (full config + results stored as JSON)

The database is zero-config: auto-created on first use.
db_path parameter on all functions allows tests to use a temp database.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "scenario_history.db"


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Create/connect to scenario history database.

    Creates the scenarios table and indices if they don't exist.

    Args:
        db_path: Path to SQLite database. Defaults to data/scenario_history.db.

    Returns:
        sqlite3.Connection ready for use.
    """
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            region TEXT NOT NULL,
            formation_id TEXT NOT NULL,
            fybe REAL NOT NULL,
            fybe_current_year REAL,
            config_json TEXT NOT NULL,
            results_json TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_region ON scenarios(region)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_formation ON scenarios(formation_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_timestamp ON scenarios(timestamp)"
    )
    conn.commit()
    return conn


def save_scenario(config, results, db_path: Path | None = None) -> int:
    """Persist scenario run to SQLite.

    Args:
        config: ScenarioConfig Pydantic model.
        results: ScenarioResults Pydantic model.
        db_path: Path to SQLite database. Defaults to data/scenario_history.db.

    Returns:
        Row ID of the inserted record.
    """
    conn = init_db(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO scenarios (timestamp, region, formation_id, fybe,
                                   fybe_current_year, config_json, results_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                results.timestamp,
                config.region,
                config.formation_id,
                results.fybe,
                results.fybe_current_year,
                config.model_dump_json(),
                results.model_dump_json(),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def query_history(
    region: str | None = None,
    formation_id: str | None = None,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict]:
    """Query scenario history with optional filters.

    Args:
        region: Filter by region (exact match). None = no filter.
        formation_id: Filter by formation ID (exact match). None = no filter.
        limit: Maximum number of results to return. Default 20.
        db_path: Path to SQLite database. Defaults to data/scenario_history.db.

    Returns:
        List of dicts with: id, timestamp, region, formation_id, fybe,
        fybe_current_year. Most recent first.
    """
    conn = init_db(db_path)
    try:
        query = "SELECT id, timestamp, region, formation_id, fybe, fybe_current_year FROM scenarios"
        conditions = []
        params = []

        if region is not None:
            conditions.append("region = ?")
            params.append(region)
        if formation_id is not None:
            conditions.append("formation_id = ?")
            params.append(formation_id)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        columns = ["id", "timestamp", "region", "formation_id", "fybe", "fybe_current_year"]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        conn.close()
