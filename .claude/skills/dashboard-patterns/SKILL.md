# Dashboard Patterns

FastAPI dashboard architecture and async patterns.

## Module Map

| Module | Purpose |
|--------|---------|
| `server.py` (421L) | FastAPI app, 16 REST + 3 WS endpoints, lifespan |
| `db.py` (485L) | SQLite via aiosqlite, schema + CRUD |
| `config.py` (32L) | Constants (paths, ports, costs) |
| `models.py` (74L) | Pydantic response models |
| `orchestrator.py` (127L) | Rust binary subprocess control |
| `watcher.py` (197L) | File watcher for outputs/ directory |
| `team_launcher.py` (264L) | Team session management |
| `worktree.py` (184L) | Git worktree operations |

## Server Architecture

### Lifespan
```python
@asynccontextmanager
async def lifespan(app):
    await init_db()
    await backfill_existing_outputs()
    await backfill_team_outputs()
    asyncio.create_task(watch_outputs(...))
    yield
    await team_launcher.cancel_all()
```

### WebSocket Channels
```python
class ConnectionManager:
    # 3 channel pools:
    connections["status"]  # Execution updates
    connections["logs"]    # Live log stream
    connections["teams"]   # Team progress events
```

### REST Endpoints
Stats, executions (paginated), execution detail, agent summaries, cost breakdown, config, status, logs, teams CRUD, orchestrator start/stop.

## DB Schema (5 tables)

1. `executions` — orchestrator runs
2. `agent_results` — per-agent outputs (FK → executions)
3. `logs` — log stream entries
4. `team_sessions` — team runs (+ repo_path, branch_name, worktree_path)
5. `team_tasks` — per-teammate outputs (FK → team_sessions)

## Async Patterns

- All DB operations use `async with aiosqlite.connect()`
- `OrchestratorControl` uses `asyncio.create_subprocess_exec` + `_stream_output()` background task
- `TeamLauncher` spawns per-session background tasks via `asyncio.create_task`
- File watcher uses `watchfiles.awatch()` for non-blocking directory monitoring
- WebSocket broadcast: `manager.broadcast(channel, json_message)`

## Frontend

Single-page HTML at `templates/index.html` with:
- `static/app.js` — API calls, WS connections, tab management
- `static/style.css` — responsive dashboard layout
- 7 tabs: Overview, Agents, History, Logs, Control, Costs, Teams
