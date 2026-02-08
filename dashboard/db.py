"""SQLite schema and CRUD operations using aiosqlite."""

from __future__ import annotations

import aiosqlite

from . import config

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(str(config.DB_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def init_db() -> None:
    db = await get_db()
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            mode TEXT NOT NULL,
            global_client_mode TEXT,
            filename TEXT UNIQUE,
            agent_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            estimated_cost REAL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS agent_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id INTEGER NOT NULL,
            agent TEXT NOT NULL,
            status TEXT NOT NULL,
            output TEXT,
            error TEXT,
            client_mode TEXT,
            timestamp TEXT,
            estimated_cost REAL DEFAULT 0.0,
            FOREIGN KEY (execution_id) REFERENCES executions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS team_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT UNIQUE,
            team_name TEXT NOT NULL,
            task_description TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            filename TEXT,
            teammate_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS team_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            teammate TEXT NOT NULL,
            role TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            output TEXT,
            error TEXT,
            started_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (session_id) REFERENCES team_sessions(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_executions_timestamp ON executions(timestamp);
        CREATE INDEX IF NOT EXISTS idx_agent_results_execution ON agent_results(execution_id);
        CREATE INDEX IF NOT EXISTS idx_agent_results_agent ON agent_results(agent);
        CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
        CREATE INDEX IF NOT EXISTS idx_team_sessions_started ON team_sessions(started_at);
        CREATE INDEX IF NOT EXISTS idx_team_tasks_session ON team_tasks(session_id);
        """
    )
    await db.commit()

    # GM tables
    await _ensure_gm_tables()

    # Idempotent schema migration: add worktree columns to team_sessions
    for col, coldef in [
        ("repo_path", "TEXT"),
        ("branch_name", "TEXT"),
        ("worktree_path", "TEXT"),
    ]:
        try:
            await db.execute(f"ALTER TABLE team_sessions ADD COLUMN {col} {coldef}")
            await db.commit()
        except Exception:
            pass  # Column already exists


# ── Execution CRUD ──────────────────────────────────────────────────────

async def execution_exists(filename: str) -> bool:
    db = await get_db()
    cursor = await db.execute(
        "SELECT 1 FROM executions WHERE filename = ?", (filename,)
    )
    return await cursor.fetchone() is not None


async def insert_execution(
    timestamp: str,
    mode: str,
    global_client_mode: str | None,
    filename: str | None,
    agent_count: int,
    success_count: int,
    fail_count: int,
    estimated_cost: float,
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO executions
           (timestamp, mode, global_client_mode, filename,
            agent_count, success_count, fail_count, estimated_cost)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (timestamp, mode, global_client_mode, filename,
         agent_count, success_count, fail_count, estimated_cost),
    )
    await db.commit()
    return cursor.lastrowid


async def insert_agent_result(
    execution_id: int,
    agent: str,
    status: str,
    output: str | None,
    error: str | None,
    client_mode: str | None,
    timestamp: str | None,
    estimated_cost: float,
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO agent_results
           (execution_id, agent, status, output, error,
            client_mode, timestamp, estimated_cost)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (execution_id, agent, status, output, error,
         client_mode, timestamp, estimated_cost),
    )
    await db.commit()
    return cursor.lastrowid


async def get_executions(limit: int = 50, offset: int = 0) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT * FROM executions ORDER BY timestamp DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_execution(execution_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM executions WHERE id = ?", (execution_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_agent_results(execution_id: int) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM agent_results WHERE execution_id = ? ORDER BY timestamp",
        (execution_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_execution_count() -> int:
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    return row[0]


# ── Stats ───────────────────────────────────────────────────────────────

async def get_stats() -> dict:
    db = await get_db()

    cursor = await db.execute("SELECT COUNT(*) FROM executions")
    total_exec = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT COUNT(*) FROM agent_results")
    total_agents = (await cursor.fetchone())[0]

    cursor = await db.execute(
        "SELECT COUNT(*) FROM agent_results WHERE status = 'success'"
    )
    total_success = (await cursor.fetchone())[0]

    cursor = await db.execute("SELECT SUM(estimated_cost) FROM executions")
    row = await cursor.fetchone()
    total_cost = row[0] or 0.0

    cursor = await db.execute(
        "SELECT timestamp FROM executions ORDER BY timestamp DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    last_exec = row[0] if row else None

    success_rate = (total_success / total_agents * 100) if total_agents > 0 else 0.0

    return {
        "total_executions": total_exec,
        "total_agents_run": total_agents,
        "success_rate": round(success_rate, 1),
        "total_cost": round(total_cost, 6),
        "last_execution": last_exec,
    }


async def get_agent_summaries() -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        """SELECT
             agent,
             COUNT(*) as total_runs,
             SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successes,
             SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failures,
             MAX(timestamp) as last_run
           FROM agent_results
           GROUP BY agent
           ORDER BY agent"""
    )
    rows = await cursor.fetchall()
    results = []
    for r in rows:
        d = dict(r)
        # get last status
        cursor2 = await db.execute(
            """SELECT status FROM agent_results
               WHERE agent = ? ORDER BY timestamp DESC LIMIT 1""",
            (d["agent"],),
        )
        last = await cursor2.fetchone()
        d["last_status"] = last["status"] if last else None
        # avg output length
        cursor3 = await db.execute(
            """SELECT AVG(LENGTH(COALESCE(output, ''))) as avg_len
               FROM agent_results WHERE agent = ?""",
            (d["agent"],),
        )
        avg_row = await cursor3.fetchone()
        d["avg_output_len"] = round(avg_row["avg_len"] or 0, 0)
        results.append(d)
    return results


async def get_cost_breakdown() -> dict:
    db = await get_db()

    cursor = await db.execute("SELECT SUM(estimated_cost) FROM executions")
    total = (await cursor.fetchone())[0] or 0.0

    cursor = await db.execute(
        """SELECT mode, SUM(estimated_cost) as cost
           FROM executions GROUP BY mode"""
    )
    by_mode = {r["mode"]: round(r["cost"] or 0, 6) for r in await cursor.fetchall()}

    cursor = await db.execute(
        """SELECT agent, SUM(estimated_cost) as cost
           FROM agent_results GROUP BY agent"""
    )
    by_agent = {r["agent"]: round(r["cost"] or 0, 6) for r in await cursor.fetchall()}

    cursor = await db.execute(
        """SELECT DATE(timestamp) as day, SUM(estimated_cost) as cost
           FROM executions GROUP BY DATE(timestamp) ORDER BY day"""
    )
    by_date = {r["day"]: round(r["cost"] or 0, 6) for r in await cursor.fetchall()}

    return {
        "total_cost": round(total, 6),
        "by_mode": by_mode,
        "by_agent": by_agent,
        "by_date": by_date,
    }


# ── Team Sessions ──────────────────────────────────────────────────────

async def team_session_exists(session_id: str) -> bool:
    db = await get_db()
    cursor = await db.execute(
        "SELECT 1 FROM team_sessions WHERE session_id = ?", (session_id,)
    )
    return await cursor.fetchone() is not None


async def insert_team_session(
    session_id: str,
    team_name: str,
    task_description: str | None,
    status: str,
    started_at: str,
    completed_at: str | None,
    filename: str | None,
    teammate_count: int,
    success_count: int,
    fail_count: int,
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO team_sessions
           (session_id, team_name, task_description, status, started_at,
            completed_at, filename, teammate_count, success_count, fail_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, team_name, task_description, status, started_at,
         completed_at, filename, teammate_count, success_count, fail_count),
    )
    await db.commit()
    return cursor.lastrowid


async def insert_team_task(
    session_id: int,
    teammate: str,
    role: str | None,
    status: str,
    output: str | None,
    error: str | None,
    started_at: str | None,
    completed_at: str | None,
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO team_tasks
           (session_id, teammate, role, status, output, error, started_at, completed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, teammate, role, status, output, error, started_at, completed_at),
    )
    await db.commit()
    return cursor.lastrowid


async def get_team_sessions(limit: int = 50, offset: int = 0) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM team_sessions ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_team_session(session_id: int) -> dict | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM team_sessions WHERE id = ?", (session_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_team_tasks(session_id: int) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM team_tasks WHERE session_id = ? ORDER BY id",
        (session_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_team_session_count() -> int:
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM team_sessions")
    row = await cursor.fetchone()
    return row[0]


async def get_team_session_by_session_id(session_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM team_sessions WHERE session_id = ?", (session_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_team_session_worktree(
    session_id: str,
    repo_path: str,
    branch_name: str,
    worktree_path: str,
) -> None:
    db = await get_db()
    await db.execute(
        """UPDATE team_sessions
           SET repo_path = ?, branch_name = ?, worktree_path = ?
           WHERE session_id = ?""",
        (repo_path, branch_name, worktree_path, session_id),
    )
    await db.commit()


async def update_team_session_status(
    session_id: str,
    status: str,
    completed_at: str | None = None,
) -> None:
    db = await get_db()
    if completed_at:
        await db.execute(
            "UPDATE team_sessions SET status = ?, completed_at = ? WHERE session_id = ?",
            (status, completed_at, session_id),
        )
    else:
        await db.execute(
            "UPDATE team_sessions SET status = ? WHERE session_id = ?",
            (status, session_id),
        )
    await db.commit()


async def update_team_session_filename(session_id: str, filename: str) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE team_sessions SET filename = ? WHERE session_id = ?",
        (filename, session_id),
    )
    await db.commit()


# ── Logs ────────────────────────────────────────────────────────────────

async def insert_log(timestamp: str, level: str, message: str, source: str | None = None) -> int:
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO logs (timestamp, level, message, source) VALUES (?, ?, ?, ?)",
        (timestamp, level, message, source),
    )
    await db.commit()
    return cursor.lastrowid


async def get_logs(limit: int = 100, offset: int = 0, level: str | None = None) -> list[dict]:
    db = await get_db()
    if level:
        cursor = await db.execute(
            "SELECT * FROM logs WHERE level = ? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (level, limit, offset),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM logs ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


# ── GM Projects ────────────────────────────────────────────────────────

async def _ensure_gm_tables() -> None:
    """Create GM tables if they don't exist (idempotent)."""
    db = await get_db()
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS gm_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT UNIQUE NOT NULL,
            project_name TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            build_command TEXT,
            test_command TEXT,
            phase TEXT NOT NULL DEFAULT 'created',
            agent_count INTEGER DEFAULT 0,
            completed_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            merged_count INTEGER DEFAULT 0,
            merge_order TEXT,
            current_merge TEXT,
            build_attempts INTEGER DEFAULT 0,
            test_attempts INTEGER DEFAULT 0,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS gm_agent_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            team_name TEXT NOT NULL,
            task_description TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            files_changed TEXT,
            merge_order_index INTEGER,
            merge_result TEXT,
            merged_at TEXT,
            FOREIGN KEY (project_id) REFERENCES gm_projects(project_id)
        );

        CREATE INDEX IF NOT EXISTS idx_gm_projects_phase ON gm_projects(phase);
        CREATE INDEX IF NOT EXISTS idx_gm_agent_sessions_project ON gm_agent_sessions(project_id);
        """
    )
    await db.commit()


async def insert_gm_project(
    project_id: str,
    project_name: str,
    repo_path: str,
    build_command: str | None,
    test_command: str | None,
    agent_count: int,
    started_at: str,
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO gm_projects
           (project_id, project_name, repo_path, build_command, test_command,
            agent_count, started_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (project_id, project_name, repo_path, build_command, test_command,
         agent_count, started_at),
    )
    await db.commit()
    return cursor.lastrowid


async def update_gm_project_phase(
    project_id: str,
    phase: str,
    error_message: str | None = None,
    completed_at: str | None = None,
) -> None:
    db = await get_db()
    if completed_at:
        await db.execute(
            "UPDATE gm_projects SET phase = ?, error_message = ?, completed_at = ? WHERE project_id = ?",
            (phase, error_message, completed_at, project_id),
        )
    else:
        await db.execute(
            "UPDATE gm_projects SET phase = ?, error_message = ? WHERE project_id = ?",
            (phase, error_message, project_id),
        )
    await db.commit()


async def update_gm_project_merge_progress(
    project_id: str,
    *,
    completed_count: int | None = None,
    failed_count: int | None = None,
    merged_count: int | None = None,
    merge_order: str | None = None,
    current_merge: str | None = None,
    build_attempts: int | None = None,
    test_attempts: int | None = None,
) -> None:
    db = await get_db()
    updates: list[str] = []
    params: list = []
    for col, val in [
        ("completed_count", completed_count),
        ("failed_count", failed_count),
        ("merged_count", merged_count),
        ("merge_order", merge_order),
        ("current_merge", current_merge),
        ("build_attempts", build_attempts),
        ("test_attempts", test_attempts),
    ]:
        if val is not None:
            updates.append(f"{col} = ?")
            params.append(val)
    if not updates:
        return
    params.append(project_id)
    await db.execute(
        f"UPDATE gm_projects SET {', '.join(updates)} WHERE project_id = ?",
        params,
    )
    await db.commit()


async def get_gm_project(project_id: str) -> dict | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM gm_projects WHERE project_id = ?", (project_id,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_gm_projects(limit: int = 50, offset: int = 0) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM gm_projects ORDER BY started_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_gm_project_count() -> int:
    db = await get_db()
    cursor = await db.execute("SELECT COUNT(*) FROM gm_projects")
    row = await cursor.fetchone()
    return row[0]


async def insert_gm_agent_session(
    project_id: str,
    session_id: str,
    team_name: str,
    task_description: str | None,
) -> int:
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO gm_agent_sessions
           (project_id, session_id, team_name, task_description)
           VALUES (?, ?, ?, ?)""",
        (project_id, session_id, team_name, task_description),
    )
    await db.commit()
    return cursor.lastrowid


async def update_gm_agent_session_status(
    project_id: str,
    session_id: str,
    status: str,
) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE gm_agent_sessions SET status = ? WHERE project_id = ? AND session_id = ?",
        (status, project_id, session_id),
    )
    await db.commit()


async def update_gm_agent_session_files(
    project_id: str,
    session_id: str,
    files_changed: str,
) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE gm_agent_sessions SET files_changed = ? WHERE project_id = ? AND session_id = ?",
        (files_changed, project_id, session_id),
    )
    await db.commit()


async def update_gm_agent_session_merge(
    project_id: str,
    session_id: str,
    merge_order_index: int,
    merge_result: str,
    merged_at: str | None = None,
) -> None:
    db = await get_db()
    await db.execute(
        """UPDATE gm_agent_sessions
           SET merge_order_index = ?, merge_result = ?, merged_at = ?
           WHERE project_id = ? AND session_id = ?""",
        (merge_order_index, merge_result, merged_at, project_id, session_id),
    )
    await db.commit()


async def get_gm_agent_sessions(project_id: str) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM gm_agent_sessions WHERE project_id = ? ORDER BY id",
        (project_id,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
