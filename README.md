# Agent Orchestra

Multi-agent orchestration system that launches parallel Claude Code agents, each working in isolated git worktrees, then automatically merges their work back together. Includes a real-time dashboard, an automated General Manager pipeline, and an approval gate for human-in-the-loop decisions.

Built with **Rust** (orchestrator) + **Python/FastAPI** (dashboard).

## How It Works

```
                        ┌─────────────────────────────────┐
                        │      config/orchestra.yml        │
                        │  agents, teams, modes, features  │
                        └───────────────┬─────────────────┘
                                        │
               ┌────────────────────────┼────────────────────────┐
               ▼                        ▼                        ▼
        ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
        │  ApiClient   │         │  CliClient   │         │ TeamsClient  │
        │  (HTTP API)  │         │ (claude -p)  │         │ (Opus teams) │
        │    paid      │         │    free      │         │  per-session │
        └──────┬──────┘         └──────┬──────┘         └──────┬──────┘
               │                       │                       │
               └───────────────────────┼───────────────────────┘
                                       ▼
                              ┌─────────────────┐
                              │   Claude AI      │
                              │  (Anthropic)     │
                              └────────┬────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │  outputs/*.json  │
                              │  outputs/*.txt   │
                              └─────────────────┘

        ┌──────────────────────────────────────────────────────┐
        │              Dashboard (FastAPI + WebSocket)          │
        │                                                      │
        │  Overview · Agents · History · Logs · Control         │
        │  Costs · Teams · General Manager                     │
        │                                                      │
        │  Real-time updates via WebSocket with heartbeat      │
        │  SQLite storage · Subprocess control                 │
        └──────────────────────────────────────────────────────┘
```

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

# Copy environment template
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY if using api/hybrid mode

# Build the Rust orchestrator
cargo build --release

# Install Python deps
pip install -r dashboard/requirements.txt

# Start dashboard (http://localhost:8080)
python3 -m dashboard.server

# Or run the orchestrator directly
ORCHESTRATOR_MODE=auto CLIENT_MODE=claude-code cargo run
```

## Client Modes

The orchestrator supports 4 ways to talk to Claude, configurable globally or per-agent:

| Mode | Implementation | Cost | Best For |
|------|---------------|------|----------|
| `claude-code` | `CliClient` — spawns `claude -p` subprocess | Free (subscription) | Simple monitoring tasks |
| `api` | `ApiClient` — HTTP POST to Anthropic API | Paid per token | Analysis with system prompts |
| `hybrid` | `HybridClient` — tries API, falls back to CLI | Flexible | Production reliability |
| `agent-teams` | `TeamsClient` — CLI with Agent Teams enabled | Per session | Multi-agent collaboration |

The CLI path is auto-detected: checks `CLAUDE_CLI_PATH` env, then common system paths, then falls back to `claude` on PATH.

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

# Per-agent client mode overrides
agents:
  monitor:
    enabled: true
    timeout_seconds: 120
    client_mode: "claude-code"    # free CLI for simple tasks
    system_prompt: "You are a system health monitor..."
  analyzer:
    enabled: true
    timeout_seconds: 180
    client_mode: "api"            # paid API for complex analysis
    system_prompt: "You are a data analyst..."

# GM project templates — automated multi-agent pipelines
gm_projects:
  my-project:
    repo_path: /path/to/repo
    build_command: "cargo build"
    test_command: "cargo test"
    agents:
      - team: feature-dev
        task: "Implement signal processing module"
      - team: feature-dev
        task: "Implement AI agent framework"
```

### Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
CLIENT_MODE=claude-code          # claude-code | api | hybrid | agent-teams
ANTHROPIC_API_KEY=sk-ant-...     # Required for api/hybrid modes
CLAUDE_CLI_PATH=/usr/local/bin/claude  # Optional: override CLI auto-detection
ORCHESTRATOR_MODE=auto           # auto | research | analysis | monitoring | <team-name>
DASHBOARD_HOST=127.0.0.1        # Dashboard bind address
DASHBOARD_PORT=8080              # Dashboard port
RUST_LOG=info                    # Log level
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

All WebSocket connections include automatic heartbeat (ping/pong every 30s) to detect and clean up stale connections.

## Resource Safety

The team launcher includes protections against runaway agents:

- **Shared `CARGO_TARGET_DIR`** — Rust projects share a single target directory across all worktrees, preventing duplicate compilation artifacts from filling the disk
- **Critical error auto-kill** — Agents that hit `No space left on device`, `ENOSPC`, `cannot allocate memory`, or similar errors twice are automatically killed
- **Worktree `target/` cleanup** — After each agent completes, any worktree-local `target/` directory is removed

## Project Structure

```
agent-orchestra/
├── src/                        # Rust orchestrator
│   ├── main.rs                 #   Orchestrator + sequential/parallel execution
│   ├── config.rs               #   YAML config parsing (serde_yml)
│   ├── client.rs               #   AgentClient trait + 4 implementations
│   └── agents.rs               #   AgentTask + AgentResult types
├── dashboard/                  # Python FastAPI dashboard
│   ├── server.py               #   REST + WebSocket endpoints + heartbeat
│   ├── gm.py                   #   General Manager pipeline
│   ├── team_launcher.py        #   Team session lifecycle
│   ├── worktree.py             #   Git worktree operations
│   ├── db.py                   #   SQLite schema + queries
│   ├── config.py               #   Dashboard configuration
│   ├── orchestrator.py         #   Rust binary subprocess control
│   ├── watcher.py              #   File system monitoring
│   ├── models.py               #   Pydantic API models
│   ├── requirements.txt        #   Python dependencies
│   ├── static/                 #   Frontend JS + CSS
│   └── templates/              #   Jinja2 HTML
├── config/
│   └── orchestra.yml           # Master configuration
├── scripts/
│   ├── dashboard.sh            # Start dashboard
│   ├── launch-team.sh          # Launch team session
│   └── team-status.sh          # Check team status
├── .github/workflows/
│   └── rust-workflow.yml       # CI: fmt, clippy, test, build, deploy
├── Dockerfile                  # Multi-stage build (Rust + Node.js runtime)
├── Cargo.toml                  # Rust dependencies
└── .env.example                # Environment variables template
```

## Docker

```bash
docker build -t agent-orchestra .
docker run -p 8080:8080 \
  -e CLIENT_MODE=claude-code \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  agent-orchestra
```

## CI/CD

The GitHub Actions pipeline runs on every push to `main` (for `src/`, `Cargo.toml`, `config/` changes), hourly on schedule, and on manual dispatch:

1. **Build** — `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, `cargo build --release`
2. **Monitor** — Reports build status
3. **Orchestrate** — Downloads binary artifact and runs a real orchestration
4. **Docker** — Builds and pushes to DigitalOcean Container Registry (requires `DO_API_TOKEN` secret)
5. **Deploy** — Triggers DigitalOcean App Platform deployment (requires `DO_APP_ID` secret)

## Lessons from Production Use

This system was used to build [auto-rebalance-project](https://github.com/anescaper/auto-rebalance-project) with 6 parallel Claude agents working on a Rust monorepo:

- **Merge order matters** — when multiple agents modify the same `Cargo.toml`, merge the least-overlapping branches first
- **Lock file conflicts are safe to auto-resolve** — `Cargo.lock` is regenerated on build
- **Worktrees need auto-commit** — agents may exit without committing; the launcher handles this automatically
- **New crates need `.gitignore` entries** — each crate's `target/` must be excluded

## License

MIT
