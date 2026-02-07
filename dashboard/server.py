"""FastAPI server - REST endpoints, WebSocket handlers, static/template serving."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from . import config, db, worktree
from .orchestrator import OrchestratorControl
from .team_launcher import TeamLauncher, get_available_teams
from .watcher import backfill_existing_outputs, backfill_team_outputs, watch_outputs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard.server")


# ── WebSocket Connection Manager ────────────────────────────────────────

class ConnectionManager:
    """Manage WebSocket connections for real-time updates."""

    def __init__(self):
        self._status_connections: list[WebSocket] = []
        self._log_connections: list[WebSocket] = []
        self._teams_connections: list[WebSocket] = []

    async def connect_status(self, ws: WebSocket):
        await ws.accept()
        self._status_connections.append(ws)

    async def connect_logs(self, ws: WebSocket):
        await ws.accept()
        self._log_connections.append(ws)

    async def connect_teams(self, ws: WebSocket):
        await ws.accept()
        self._teams_connections.append(ws)

    def disconnect_status(self, ws: WebSocket):
        if ws in self._status_connections:
            self._status_connections.remove(ws)

    def disconnect_logs(self, ws: WebSocket):
        if ws in self._log_connections:
            self._log_connections.remove(ws)

    def disconnect_teams(self, ws: WebSocket):
        if ws in self._teams_connections:
            self._teams_connections.remove(ws)

    async def broadcast_status(self, data: dict):
        dead = []
        for ws in self._status_connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_status(ws)

    async def broadcast_log(self, entry: dict):
        dead = []
        for ws in self._log_connections:
            try:
                await ws.send_json(entry)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_logs(ws)

    async def broadcast_teams(self, data: dict):
        dead = []
        for ws in self._teams_connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_teams(ws)


manager = ConnectionManager()
orchestrator = OrchestratorControl()
team_launcher = TeamLauncher()


# ── Orchestrator log callback ───────────────────────────────────────────

async def on_orchestrator_log(level: str, message: str):
    ts = datetime.now(timezone.utc).isoformat()
    await db.insert_log(ts, level, message, source="orchestrator")
    await manager.broadcast_log({
        "timestamp": ts,
        "level": level,
        "message": message,
        "source": "orchestrator",
    })

orchestrator.set_log_callback(on_orchestrator_log)


# ── Team launcher callbacks ────────────────────────────────────────────

async def on_team_progress(data: dict):
    await manager.broadcast_teams(data)

async def on_team_log(level: str, message: str):
    ts = datetime.now(timezone.utc).isoformat()
    await db.insert_log(ts, level, message, source="team-launcher")
    await manager.broadcast_log({
        "timestamp": ts,
        "level": level,
        "message": message,
        "source": "team-launcher",
    })

team_launcher.set_progress_callback(on_team_progress)
team_launcher.set_log_callback(on_team_log)


# ── New execution callback ──────────────────────────────────────────────

async def on_new_execution(execution_id: int):
    execution = await db.get_execution(execution_id)
    if execution:
        await manager.broadcast_status({"type": "new_execution", "data": execution})
        ts = datetime.now(timezone.utc).isoformat()
        await db.insert_log(ts, "info", f"New execution #{execution_id} ingested", source="watcher")
        await manager.broadcast_log({
            "timestamp": ts,
            "level": "info",
            "message": f"New execution #{execution_id} ingested",
            "source": "watcher",
        })


# ── New team session callback ─────────────────────────────────────────

async def on_new_team_session(session_db_id: int):
    session = await db.get_team_session(session_db_id)
    if session:
        await manager.broadcast_teams({"type": "new_team_session", "data": session})
        ts = datetime.now(timezone.utc).isoformat()
        await db.insert_log(ts, "info", f"New team session #{session_db_id} ingested", source="watcher")
        await manager.broadcast_log({
            "timestamp": ts,
            "level": "info",
            "message": f"New team session #{session_db_id} ingested",
            "source": "watcher",
        })


# ── Lifespan ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db.init_db()
    count = await backfill_existing_outputs()
    team_count = await backfill_team_outputs()
    log.info("Database initialized, backfilled %d files + %d team files", count, team_count)

    # Start file watcher in background
    watcher_task = asyncio.create_task(
        watch_outputs(
            on_new_execution=on_new_execution,
            on_new_team_session=on_new_team_session,
        )
    )

    ts = datetime.now(timezone.utc).isoformat()
    await db.insert_log(
        ts, "info",
        f"Dashboard started, backfilled {count} output files + {team_count} team files",
        source="dashboard",
    )

    yield

    # Shutdown
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass
    await team_launcher.cancel_all()
    if orchestrator.running:
        await orchestrator.stop()
    await db.close_db()


# ── App ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Agent Orchestra Dashboard", lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))


# ── Pages ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── REST API ────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats():
    return await db.get_stats()


@app.get("/api/executions")
async def api_executions(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    executions = await db.get_executions(limit=limit, offset=offset)
    total = await db.get_execution_count()
    return {"executions": executions, "total": total, "limit": limit, "offset": offset}


@app.get("/api/executions/{execution_id}")
async def api_execution_detail(execution_id: int):
    execution = await db.get_execution(execution_id)
    if not execution:
        return {"error": "Not found"}, 404
    results = await db.get_agent_results(execution_id)
    return {**execution, "results": results}


@app.get("/api/agents")
async def api_agents():
    return await db.get_agent_summaries()


@app.get("/api/costs")
async def api_costs():
    return await db.get_cost_breakdown()


@app.get("/api/config")
async def api_config():
    try:
        with open(config.CONFIG_FILE) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {"error": "Config file not found"}


@app.get("/api/status")
async def api_status():
    stats = await db.get_stats()
    return {
        "orchestrator": orchestrator.status(),
        "stats": stats,
        "outputs_dir": str(config.OUTPUTS_DIR),
        "db_path": str(config.DB_PATH),
    }


@app.get("/api/logs")
async def api_logs(limit: int = Query(100, ge=1, le=500), level: str | None = None):
    return await db.get_logs(limit=limit, level=level)


# ── Teams endpoints ───────────────────────────────────────────────────

@app.get("/api/teams")
async def api_teams(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    sessions = await db.get_team_sessions(limit=limit, offset=offset)
    total = await db.get_team_session_count()
    return {"sessions": sessions, "total": total, "limit": limit, "offset": offset}


@app.get("/api/teams/{session_id}")
async def api_team_detail(session_id: int):
    session = await db.get_team_session(session_id)
    if not session:
        return {"error": "Not found"}, 404
    tasks = await db.get_team_tasks(session_id)
    return {**session, "tasks": tasks}


@app.get("/api/teams/{session_id}/tasks")
async def api_team_tasks(session_id: int):
    tasks = await db.get_team_tasks(session_id)
    return tasks


# ── Team launcher endpoints ───────────────────────────────────────────

@app.get("/api/teams/templates")
async def api_team_templates():
    return get_available_teams()


@app.post("/api/teams/launch")
async def api_team_launch(request: Request):
    body = await request.json()
    team_name = body.get("team_name")
    task_description = body.get("task_description")
    repo_path = body.get("repo_path") or None

    if not team_name or not task_description:
        return {"error": "team_name and task_description are required"}

    result = await team_launcher.launch(team_name, task_description, repo_path)
    return result


@app.get("/api/teams/{session_id}/diff")
async def api_team_diff(session_id: str):
    session = await db.get_team_session_by_session_id(session_id)
    if not session:
        return {"error": "Session not found"}
    repo_path = session.get("repo_path") or str(config.BASE_DIR)
    result = await worktree.get_worktree_diff(repo_path, session_id)
    stat = await worktree.get_worktree_stat(repo_path, session_id)
    if "error" not in stat:
        result["stat"] = stat.get("stat", "")
    return result


@app.post("/api/teams/{session_id}/merge")
async def api_team_merge(session_id: str):
    session = await db.get_team_session_by_session_id(session_id)
    if not session:
        return {"error": "Session not found"}
    repo_path = session.get("repo_path") or str(config.BASE_DIR)
    result = await worktree.merge_worktree(repo_path, session_id)
    if "error" not in result:
        await db.update_team_session_status(
            session_id, "merged", datetime.now(timezone.utc).isoformat()
        )
    return result


@app.post("/api/teams/{session_id}/discard")
async def api_team_discard(session_id: str):
    session = await db.get_team_session_by_session_id(session_id)
    if not session:
        return {"error": "Session not found"}
    repo_path = session.get("repo_path") or str(config.BASE_DIR)
    result = await worktree.delete_worktree(repo_path, session_id)
    if "error" not in result:
        await db.update_team_session_status(
            session_id, "discarded", datetime.now(timezone.utc).isoformat()
        )
    return result


@app.post("/api/teams/{session_id}/cancel")
async def api_team_cancel(session_id: str):
    result = await team_launcher.cancel(session_id)
    return result


# ── Control endpoints ──────────────────────────────────────────────────

@app.post("/api/orchestrator/start")
async def api_start(mode: str = Query("auto"), client_mode: str = Query("hybrid")):
    result = await orchestrator.start(mode=mode, client_mode=client_mode)
    return result


@app.post("/api/orchestrator/stop")
async def api_stop():
    result = await orchestrator.stop()
    return result


# ── WebSocket endpoints ────────────────────────────────────────────────

@app.websocket("/ws/status")
async def ws_status(ws: WebSocket):
    await manager.connect_status(ws)
    try:
        while True:
            # Keep connection alive, listen for pings
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_status(ws)


@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket):
    await manager.connect_logs(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_logs(ws)


@app.websocket("/ws/teams")
async def ws_teams(ws: WebSocket):
    await manager.connect_teams(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_teams(ws)


# ── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
