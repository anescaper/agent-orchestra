# Agent Orchestra

Multi-agent orchestration system that launches parallel Claude Code agents, each working in isolated git worktrees, then automatically merges their work back together. Includes a real-time dashboard, an automated General Manager pipeline, and an approval gate for human-in-the-loop decisions.

Built with Rust (orchestrator) + Python/FastAPI (dashboard).

## What It Does

1. **Define agents** in YAML — each gets a team name, role prompt, and task
2. **Launch them in parallel** — each agent runs `claude` CLI in its own git worktree/branch
3. **Watch progress live** — dashboard streams stdout/stderr via WebSocket
4. **Auto-merge results** — the General Manager scores branches by file overlap, merges least-conflicting first, and handles conflicts
5. **Human approval gate** — pipeline pauses on merge conflicts, build failures, or test failures; you approve or reject from the dashboard

## Quick Start

```bash
# Clone
git clone https://github.com/anescaper/agent-orchestra.git
cd agent-orchestra

# Install Python deps
pip install -r dashboard/requirements.txt

# Start dashboard (http://localhost:8080)
python3 -m dashboard.server

# Or use the helper script
./scripts/dashboard.sh 8080
```

The dashboard serves a web UI with 8 tabs: Overview, Agents, History, Logs, Control, Costs, Teams, and GM.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Dashboard (FastAPI)                   │
│  REST API + WebSocket  ·  SQLite  ·  Jinja2 UI          │
├──────────┬──────────┬──────────┬────────────────────────┤
│  Teams   │    GM    │ Worktree │   Team Launcher        │
│ launcher │ pipeline │ manager  │   (subprocess mgmt)    │
└────┬─────┴────┬─────┴────┬─────┴────────────┬──────────┘
     │          │          │                  │
     ▼          ▼          ▼                  ▼
  claude CLI  claude CLI  git worktree     claude CLI
  (agent 1)   (agent 2)   add/remove       (agent N)
     │          │          │                  │
     └──────────┴──────────┴──────────────────┘
                       │
              main repo (merged)
```

### Key Components

| Component | Path | Purpose |
|-----------|------|---------|
| Dashboard server | `dashboard/server.py` | REST + WebSocket endpoints, serves UI |
| General Manager | `dashboard/gm.py` | Automated launch → merge → build → test pipeline |
| Team Launcher | `dashboard/team_launcher.py` | Subprocess lifecycle, error detection, shared target dir |
| Worktree Manager | `dashboard/worktree.py` | Git worktree creation, diffing, merging, cleanup |
| Database | `dashboard/db.py` | SQLite with 8 tables (sessions, results, decisions, logs) |
| Rust Orchestrator | `src/` | Standalone orchestrator with 4 client modes |
| Config | `config/orchestra.yml` | Agent definitions, team templates, GM project templates |

## Configuration

All configuration lives in `config/orchestra.yml`:

```yaml
# Team definitions — each team is a group of collaborating agents
teams:
  enabled: true
  definitions:
    feature-dev:
      description: "Full feature development lifecycle"
      teammates:
        - name: architect
          role: "Design the architecture and create implementation plan"
          timeout_seconds: 600
        - name: implementer
          role: "Write the code following the architect's plan"
          timeout_seconds: 900
        - name: reviewer
          role: "Review code for bugs, security issues, and best practices"
          timeout_seconds: 300

    code-review:
      description: "Thorough code review"
      teammates:
        - name: security-reviewer
          role: "Focus on security vulnerabilities and OWASP top 10"
        - name: style-reviewer
          role: "Check code style, patterns, and maintainability"

# GM project templates — automated multi-agent pipelines
gm_projects:
  auto-rebalance:
    repo_path: /path/to/your/rust/project
    build_command: "cargo build"
    test_command: "cargo test"
    agents:
      - team: feature-dev
        task: "Implement signal processing module"
      - team: feature-dev
        task: "Implement AI agent framework"
      # ... more agents
```

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
CLIENT_MODE=claude-code        # claude-code | api | hybrid | agent-teams
ANTHROPIC_API_KEY=sk-...       # Required for api/hybrid modes
DASHBOARD_PORT=8080
```

## General Manager Pipeline

The GM automates the full lifecycle of a multi-agent project:

```
Launch agents → Wait for completion → Analyze branches
    → Merge (least-conflicting first) → Build → Test → Done
```

### Approval Gate

When the pipeline encounters a problem it can't auto-resolve, it pauses and asks you:

- **Merge conflict** — "Agent X conflicts with merged code. Approve to let Claude resolve, or reject to skip this agent."
- **Build failure** — "Build failed after merging. Approve to let Claude fix, or reject to fail the pipeline."
- **Test failure** — "Tests failed. Approve to let Claude fix, or reject to fail."

Decisions are broadcast via WebSocket (`/ws/gm`) and stored in the `gm_decisions` database table. Resolve them via the dashboard UI or the REST API:

```bash
# Approve a decision
curl -X POST http://localhost:8080/api/gm/decisions/{id}/resolve \
  -H "Content-Type: application/json" \
  -d '{"action": "approve"}'
```

### Launch a GM Project

```bash
curl -X POST http://localhost:8080/api/gm/launch \
  -H "Content-Type: application/json" \
  -d '{
    "project_name": "my-project",
    "repo_path": "/path/to/repo",
    "build_command": "cargo build",
    "test_command": "cargo test",
    "agents": [
      {"team": "feature-dev", "task": "Add user authentication"},
      {"team": "feature-dev", "task": "Add database migrations"},
      {"team": "feature-dev", "task": "Add API endpoints"}
    ]
  }'
```

## API Reference

### Teams

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/teams/templates` | List available team definitions |
| `POST` | `/api/teams/launch` | Launch a new team session |
| `GET` | `/api/teams/{session_id}` | Get session details + tasks |
| `GET` | `/api/teams/{session_id}/diff` | View unified diff vs base branch |
| `POST` | `/api/teams/{session_id}/merge` | Merge branch into main |
| `POST` | `/api/teams/{session_id}/discard` | Delete worktree without merging |
| `POST` | `/api/teams/{session_id}/cancel` | Kill running session |

### General Manager

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/gm/templates` | List GM project templates |
| `POST` | `/api/gm/launch` | Launch a GM pipeline |
| `GET` | `/api/gm/projects` | List all GM projects |
| `GET` | `/api/gm/projects/{id}` | Project details + agents + decisions |
| `POST` | `/api/gm/projects/{id}/cancel` | Cancel running pipeline |
| `POST` | `/api/gm/projects/{id}/retry` | Retry failed phase |
| `POST` | `/api/gm/projects/{id}/push` | Push merged main to remote |
| `POST` | `/api/gm/decisions/{id}/resolve` | Approve or reject a decision |

### WebSocket Channels

| Endpoint | Events |
|----------|--------|
| `/ws/status` | `new_execution` |
| `/ws/logs` | Log entries (timestamp, level, message) |
| `/ws/teams` | `new_team_session`, `team_progress`, `resource_error` |
| `/ws/gm` | `project_started`, `phase_change`, `merge_started`, `merge_conflict`, `decision_required`, `decision_resolved`, `project_completed` |

## Resource Safety

The team launcher includes protections against runaway agents:

- **Shared `CARGO_TARGET_DIR`** — Rust projects share a single target directory across all worktrees, preventing duplicate compilation artifacts from filling the disk
- **Critical error auto-kill** — Agents that hit `No space left on device`, `ENOSPC`, `cannot allocate memory`, or similar errors twice are automatically killed
- **Worktree `target/` cleanup** — After each agent completes, any worktree-local `target/` directory is removed

## Project Structure

```
agent-orchestra/
├── src/                        # Rust orchestrator
│   ├── main.rs                 #   Sequential/parallel execution
│   ├── config.rs               #   YAML config parsing
│   ├── client.rs               #   AgentClient trait (CLI, API, hybrid, teams)
│   └── agents.rs               #   AgentTask + AgentResult types
├── dashboard/                  # Python FastAPI dashboard
│   ├── server.py               #   REST + WebSocket endpoints
│   ├── gm.py                   #   General Manager pipeline
│   ├── team_launcher.py        #   Team session lifecycle
│   ├── worktree.py             #   Git worktree operations
│   ├── db.py                   #   SQLite schema + queries
│   ├── config.py               #   Dashboard configuration
│   ├── orchestrator.py         #   Rust orchestrator control
│   ├── watcher.py              #   File monitoring
│   ├── requirements.txt        #   Python dependencies
│   ├── static/                 #   Frontend JS + CSS
│   └── templates/              #   Jinja2 HTML
├── config/
│   └── orchestra.yml           # Master configuration
├── scripts/
│   ├── dashboard.sh            # Start dashboard
│   ├── launch-team.sh          # Launch team session
│   └── team-status.sh          # Check team status
├── Dockerfile                  # Multi-stage build
├── Cargo.toml                  # Rust dependencies
└── .env.example                # Environment variables template
```

## Docker

```bash
docker build -t agent-orchestra .
docker run -p 8080:8080 \
  -e CLIENT_MODE=claude-code \
  -e ANTHROPIC_API_KEY=sk-... \
  agent-orchestra
```

## Lessons from Production Use

This system was used to build [auto-rebalance-project](https://github.com/anescaper/auto-rebalance-project) with 6 parallel Claude agents working on a Rust monorepo:

- **Merge order matters** — when multiple agents modify the same `Cargo.toml`, merge the least-overlapping branches first
- **Lock file conflicts are safe to auto-resolve** — `Cargo.lock` is regenerated on build
- **Worktrees need auto-commit** — agents may exit without committing; the launcher handles this automatically
- **New crates need `.gitignore` entries** — each crate's `target/` must be excluded

## License

MIT
