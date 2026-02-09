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
from .gm import GeneralManager, get_available_gm_projects
from .orchestrator import OrchestratorControl
from .team_launcher import TeamLauncher, get_available_teams
from .watcher import backfill_existing_outputs, backfill_team_outputs, watch_outputs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("dashboard.server")


# ── WebSocket Connection Manager ────────────────────────────────────────

class ConnectionManager:
    """Manage WebSocket connections for real-time updates."""

    HEARTBEAT_INTERVAL = 30  # seconds between pings
    HEARTBEAT_TIMEOUT = 10   # seconds to wait for pong

    def __init__(self):
        self._status_connections: list[WebSocket] = []
        self._log_connections: list[WebSocket] = []
        self._teams_connections: list[WebSocket] = []
        self._gm_connections: list[WebSocket] = []
        self._all_connections: set[WebSocket] = set()
        self._heartbeat_task: asyncio.Task | None = None

    async def connect_status(self, ws: WebSocket):
        await ws.accept()
        self._status_connections.append(ws)
        self._all_connections.add(ws)

    async def connect_logs(self, ws: WebSocket):
        await ws.accept()
        self._log_connections.append(ws)
        self._all_connections.add(ws)

    async def connect_teams(self, ws: WebSocket):
        await ws.accept()
        self._teams_connections.append(ws)
        self._all_connections.add(ws)

    def _remove_connection(self, ws: WebSocket):
        """Remove a connection from all tracking lists."""
        if ws in self._status_connections:
            self._status_connections.remove(ws)
        if ws in self._log_connections:
            self._log_connections.remove(ws)
        if ws in self._teams_connections:
            self._teams_connections.remove(ws)
        if ws in self._gm_connections:
            self._gm_connections.remove(ws)
        self._all_connections.discard(ws)

    async def connect_gm(self, ws: WebSocket):
        await ws.accept()
        self._gm_connections.append(ws)
        self._all_connections.add(ws)

    def disconnect_status(self, ws: WebSocket):
        if ws in self._status_connections:
            self._status_connections.remove(ws)
        self._all_connections.discard(ws)

    def disconnect_logs(self, ws: WebSocket):
        if ws in self._log_connections:
            self._log_connections.remove(ws)
        self._all_connections.discard(ws)

    def disconnect_teams(self, ws: WebSocket):
        if ws in self._teams_connections:
            self._teams_connections.remove(ws)
        self._all_connections.discard(ws)

    def disconnect_gm(self, ws: WebSocket):
        if ws in self._gm_connections:
            self._gm_connections.remove(ws)
        self._all_connections.discard(ws)

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

    async def broadcast_gm(self, data: dict):
        dead = []
        for ws in self._gm_connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_gm(ws)

    async def _ping_client(self, ws: WebSocket) -> bool:
        """Send a ping and wait for pong. Returns True if client responded."""
        try:
            await ws.send_json({"type": "ping"})
            msg = await asyncio.wait_for(ws.receive_text(), timeout=self.HEARTBEAT_TIMEOUT)
            data = json.loads(msg)
            return data.get("type") == "pong"
        except Exception:
            return False

    async def _heartbeat_loop(self):
        """Periodically ping all connected clients, disconnect unresponsive ones."""
        while True:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            if not self._all_connections:
                continue
            # Snapshot current connections to avoid mutation during iteration
            clients = list(self._all_connections)
            results = await asyncio.gather(
                *(self._ping_client(ws) for ws in clients),
                return_exceptions=True,
            )
            for ws, alive in zip(clients, results):
                if alive is not True:
                    log.info("Heartbeat timeout, disconnecting client")
                    self._remove_connection(ws)
                    try:
                        await ws.close()
                    except Exception:
                        pass

    def start_heartbeat(self):
        """Start the background heartbeat task."""
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop_heartbeat(self):
        """Stop the background heartbeat task."""
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None


manager = ConnectionManager()
orchestrator = OrchestratorControl()
team_launcher = TeamLauncher()
gm_manager = GeneralManager(team_launcher)


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


# ── GM callbacks ──────────────────────────────────────────────────────

async def on_gm_progress(data: dict):
    await manager.broadcast_gm(data)

async def on_gm_log(level: str, message: str):
    ts = datetime.now(timezone.utc).isoformat()
    await db.insert_log(ts, level, message, source="gm")
    await manager.broadcast_log({
        "timestamp": ts,
        "level": level,
        "message": message,
        "source": "gm",
    })

gm_manager.set_progress_callback(on_gm_progress)
gm_manager.set_log_callback(on_gm_log)


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

    # Start WebSocket heartbeat
    manager.start_heartbeat()

    ts = datetime.now(timezone.utc).isoformat()
    await db.insert_log(
        ts, "info",
        f"Dashboard started, backfilled {count} output files + {team_count} team files",
        source="dashboard",
    )

    yield

    # Shutdown
    await manager.stop_heartbeat()
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass
    await gm_manager.cancel_all()
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


# Static team paths MUST come before {session_id} to avoid route conflicts
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


# ── GM endpoints ──────────────────────────────────────────────────────

@app.get("/api/gm/templates")
async def api_gm_templates():
    return get_available_gm_projects()


@app.post("/api/gm/launch")
async def api_gm_launch(request: Request):
    body = await request.json()
    project_name = body.get("project_name")
    agents = body.get("agents", [])
    repo_path = body.get("repo_path")
    build_command = body.get("build_command") or None
    test_command = body.get("test_command") or None

    if not project_name or not agents or not repo_path:
        return {"error": "project_name, agents, and repo_path are required"}

    result = await gm_manager.launch_project(
        project_name=project_name,
        agents=agents,
        repo_path=repo_path,
        build_command=build_command,
        test_command=test_command,
    )
    return result


@app.get("/api/gm/projects")
async def api_gm_projects(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    projects = await db.get_gm_projects(limit=limit, offset=offset)
    total = await db.get_gm_project_count()
    return {"projects": projects, "total": total, "limit": limit, "offset": offset}


@app.get("/api/gm/projects/{project_id}")
async def api_gm_project_detail(project_id: str):
    project = await db.get_gm_project(project_id)
    if not project:
        return {"error": "Not found"}
    sessions = await db.get_gm_agent_sessions(project_id)
    # Enrich with timing from team_sessions
    for s in sessions:
        ts = await db.get_team_session_by_session_id(s["session_id"])
        if ts:
            s["started_at"] = ts.get("started_at")
            s["completed_at"] = ts.get("completed_at")
    decisions = await db.get_gm_decisions_for_project(project_id)
    return {**project, "sessions": sessions, "decisions": decisions}


@app.post("/api/gm/projects/{project_id}/cancel")
async def api_gm_cancel(project_id: str):
    return await gm_manager.cancel_project(project_id)


@app.post("/api/gm/projects/{project_id}/retry")
async def api_gm_retry(project_id: str):
    return await gm_manager.retry_project(project_id)


@app.post("/api/gm/projects/{project_id}/push")
async def api_gm_push(project_id: str):
    return await gm_manager.push_project(project_id)


@app.get("/api/gm/projects/{project_id}/decisions")
async def api_gm_decisions(project_id: str, status: str | None = None):
    return await db.get_gm_decisions_for_project(project_id, status=status)


@app.post("/api/gm/decisions/{decision_id}/resolve")
async def api_gm_resolve_decision(decision_id: str, request: Request):
    body = await request.json()
    action = body.get("action")
    if action not in ("approve", "reject"):
        return {"error": "action must be 'approve' or 'reject'"}
    return await gm_manager.resolve_decision(decision_id, action)


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


@app.websocket("/ws/gm")
async def ws_gm(ws: WebSocket):
    await manager.connect_gm(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_gm(ws)


# ── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
