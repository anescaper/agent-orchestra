# Agent Orchestra Dashboard - Implementation Progress

**Last updated:** 2026-02-09

## Architecture

- **Backend**: FastAPI + async SQLite (aiosqlite) + WebSocket (with heartbeat) + file watcher (watchfiles)
- **Frontend**: Single-page HTML/CSS/JS, dark theme, responsive, 8 tabbed panels
- **Integration**: Parse JSON output files from `outputs/`, subprocess control for Rust binary, git worktree isolation, GM pipeline

## Modules

| File | Purpose | Status |
|------|---------|--------|
| `dashboard/config.py` | Paths, port (default 127.0.0.1:8080), env var configuration | Done |
| `dashboard/models.py` | Pydantic models for API responses | Done |
| `dashboard/db.py` | SQLite schema + CRUD (executions, team_sessions, team_tasks, gm_decisions) | Done |
| `dashboard/requirements.txt` | aiosqlite, pyyaml, pydantic, watchfiles, etc. | Done |
| `dashboard/watcher.py` | File watcher for `outputs/`, backfill, cost estimation, team file ingestion | Done |
| `dashboard/orchestrator.py` | Subprocess control (start/stop Rust binary) | Done |
| `dashboard/server.py` | FastAPI app, REST endpoints, 4 WebSocket channels + heartbeat | Done |
| `dashboard/team_launcher.py` | Team session lifecycle (validate, worktree, run, auto-commit, cleanup) | Done |
| `dashboard/worktree.py` | Git worktree operations (create, remove, list, cleanup stale) | Done |
| `dashboard/gm.py` | General Manager pipeline (launch → merge → build → test → done) | Done |
| `dashboard/templates/index.html` | Single-page Jinja2 template with 8 panels | Done |
| `dashboard/static/style.css` | Dark theme, CSS grid, status colors, pulse animations, decision cards | Done |
| `dashboard/static/app.js` | WebSocket client (with ping/pong), API fetching, DOM manipulation | Done |

## Implementation Steps

### Step 1: Backend Foundation (Done)
- `config.py`: paths (BASE_DIR, OUTPUTS_DIR, DB_PATH), host 127.0.0.1, port 8080, cost heuristics
- `models.py`: Pydantic models matching JSON output format
- `db.py`: SQLite with WAL mode, tables (executions, agent_results, logs, team_sessions, team_tasks, gm_decisions)
- `requirements.txt`: aiosqlite, pyyaml, pydantic

### Step 2: File Watcher & Data Ingestion (Done)
- `watcher.py` with `backfill_existing_outputs()` and `watch_outputs()`
- Parse `results-*.json` and `teams-*.json` files into SQLite
- Cost estimation: ~4 chars/token heuristic, $0 for claude-code mode
- Handle missing fields (some files have `global_client_mode`, some don't)

### Step 3: Orchestrator Control (Done)
- `orchestrator.py` with `OrchestratorControl` class
- Start: `asyncio.create_subprocess_exec()` with MODE/CLIENT_MODE env vars
- Stop: SIGTERM then SIGKILL after timeout
- Stream stdout/stderr to WebSocket log channel

### Step 4: FastAPI Server (Done)
- `server.py` with lifespan handler (init DB, start watcher, start heartbeat, setup WebSocket manager)
- REST endpoints: `/api/executions`, `/api/stats`, `/api/agents`, `/api/costs`, `/api/config`, `/api/status`
- Control endpoints: `POST /api/orchestrator/start`, `POST /api/orchestrator/stop`
- Teams endpoints: `/api/teams/templates`, `/api/teams/launch`, `/api/teams/{session_id}/*`
- GM endpoints: `/api/gm/templates`, `/api/gm/launch`, `/api/gm/projects/*`, `/api/gm/decisions/*`
- WebSocket channels: `/ws/status`, `/ws/logs`, `/ws/teams`, `/ws/gm`
- Heartbeat: ping all connections every 30s, 10s pong timeout, auto-cleanup stale

### Step 5: Team Session Management (Done)
- `team_launcher.py`: Validate team name, create git worktree + branch, run agents in isolation
- `worktree.py`: Create/remove worktrees, list active, cleanup stale (force-remove if needed)
- Resource safety: shared CARGO_TARGET_DIR, critical error auto-kill, worktree target/ cleanup
- Auto-commit agent work before cleanup

### Step 6: General Manager Pipeline (Done)
- `gm.py`: Full lifecycle automation
- Pipeline phases: launching → waiting → analyzing → merging → building → testing → completed/failed
- Merge strategy: Score branches by file overlap, sort ascending (least-conflicting first)
- Claude integration: `claude -p` subprocesses for conflict resolution, build/test fixes
- Approval gate: Pause on merge conflicts, build failures, test failures
- Decision broadcast via `/ws/gm`, stored in `gm_decisions` table
- REST resolve: `POST /api/gm/decisions/{id}/resolve` with approve/reject

### Step 7: Frontend (Done)
- `index.html`: 8 tabbed panels (Overview, Agents, History, Logs, Control, Costs, Teams, GM)
- `style.css`: dark theme (#1a1a2e background), CSS grid, color-coded status, pulse animations
- `app.js`: WebSocket auto-reconnect + ping/pong, API helpers, panel navigation, live log scrolling
- Teams panel: session table, detail modal with teammate outputs, status badges
- GM panel: project pipeline view, yellow-bordered pulsing decision cards with Approve/Reject

## REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Dashboard HTML |
| `GET` | `/api/stats` | Execution stats |
| `GET` | `/api/executions` | Paginated execution list |
| `GET` | `/api/agents` | Agent performance summaries |
| `GET` | `/api/costs` | Cost breakdown by mode, agent, date |
| `GET` | `/api/status` | Orchestrator status + system stats |
| `GET` | `/api/logs` | Dashboard log entries |
| `GET` | `/api/config` | Current configuration |
| `POST` | `/api/orchestrator/start` | Start Rust binary |
| `POST` | `/api/orchestrator/stop` | Stop Rust binary |
| `GET` | `/api/teams/templates` | List team definitions |
| `POST` | `/api/teams/launch` | Launch team session |
| `GET` | `/api/teams/{id}` | Session details + tasks |
| `GET` | `/api/teams/{id}/diff` | Unified diff vs base branch |
| `POST` | `/api/teams/{id}/merge` | Merge branch into main |
| `POST` | `/api/teams/{id}/discard` | Delete worktree |
| `POST` | `/api/teams/{id}/cancel` | Kill running session |
| `GET` | `/api/gm/templates` | List GM project templates |
| `POST` | `/api/gm/launch` | Launch GM pipeline |
| `GET` | `/api/gm/projects` | List all GM projects |
| `GET` | `/api/gm/projects/{id}` | Project details |
| `POST` | `/api/gm/projects/{id}/cancel` | Cancel pipeline |
| `POST` | `/api/gm/projects/{id}/retry` | Retry failed phase |
| `POST` | `/api/gm/projects/{id}/push` | Push merged main to remote |
| `POST` | `/api/gm/decisions/{id}/resolve` | Approve or reject decision |

## WebSocket Channels

| Endpoint | Events |
|----------|--------|
| `/ws/status` | `new_execution` |
| `/ws/logs` | Log entries (timestamp, level, message) |
| `/ws/teams` | `new_team_session`, `team_progress`, `resource_error` |
| `/ws/gm` | `project_started`, `phase_change`, `merge_started`, `merge_conflict`, `decision_required`, `decision_resolved`, `project_completed` |

All channels support server-initiated ping/pong heartbeat (30s interval, 10s timeout).

## How to Run

```bash
cd agent-orchestra
python3 -m dashboard.server
# Dashboard available at http://localhost:8080
```
