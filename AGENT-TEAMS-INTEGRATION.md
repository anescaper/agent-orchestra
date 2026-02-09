# Agent Orchestra + Agent Teams Integration

**Date:** 2026-02-08 (initial), updated 2026-02-09
**Status:** Implemented + Hardened

## Overview

This document records the integration of Claude Code's native **Agent Teams** feature (Opus 4.6) into the existing Agent Orchestra system, plus subsequent hardening work (dependency updates, WebSocket heartbeat, GM pipeline, resource safety).

---

## What Was Built

### 1. Agent Teams Environment Enabled

**File:** `~/.claude/settings.json`

Added the experimental Agent Teams flag:
```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### 2. Team Templates in `config/orchestra.yml`

Added a `teams:` section with four pre-built team definitions:

| Team | Teammates | Use Case |
|------|-----------|----------|
| `feature-dev` | architect, implementer, reviewer | Full feature lifecycle |
| `code-review` | security-reviewer, style-reviewer | Thorough code review |
| `debug` | reproducer, analyzer, fixer | Systematic debugging |
| `research` | searcher, synthesizer | Research and summarize |

Each teammate has:
- A descriptive `name`
- A detailed `role` (used as system prompt)
- A configurable `timeout_seconds` (default 300s)

### 3. Rust Orchestrator: `AgentTeams` Client Mode

**Files changed:** `src/client.rs`, `src/config.rs`, `src/main.rs`

#### client.rs
- Added `AgentTeams` variant to `ClientMode` enum
- New `TeamsClient` struct that:
  - Spawns `claude` CLI with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` env var
  - Auto-detects CLI path: checks `CLAUDE_CLI_PATH` env, then `/usr/local/bin/claude`, `/home/claude/.local/bin/claude`, then bare `claude` on PATH
  - Prepends `[TEAM CONTEXT: ...]` prefix for system prompts
- `CliClient` also uses the same auto-detection logic (no more hardcoded paths)
- Updated factory functions `create_client()` and `create_agent_client()` to handle `agent-teams` mode
- Default model: `claude-sonnet-4-5-20250929`
- Added tests: `test_create_client_agent_teams`, `test_teams_client_creation`

#### config.rs
- New structs: `TeamsConfig`, `TeamDefinition`, `TeammateDefinition`
- `TeamsConfig` has `enabled`, `tasks_dir`, `output_prefix`, and `definitions` HashMap
- Added `teams` field to root `Config` struct with `#[serde(default)]`
- `Config` implements `Default` trait properly (not a shadowing inherent method)
- YAML parsing via `serde_yml` (migrated from deprecated `serde_yaml`)

#### main.rs
- `get_agent_tasks()` checks if the mode matches a team definition name
- When a team mode is detected, creates `AgentTask` for each teammate with `agent-teams` client mode
- `save_results()` uses the team output prefix (`teams-*.json`) for team mode runs
- `run_parallel()` records failed `AgentResult` on task panic instead of silently dropping
- Environment loading via `dotenvy` (migrated from deprecated `dotenv`)

### 4. Dashboard: 8-Tab Monitoring System

**Files changed:** `dashboard/db.py`, `dashboard/watcher.py`, `dashboard/server.py`, `dashboard/team_launcher.py`, `dashboard/worktree.py`, `dashboard/gm.py`, `dashboard/templates/index.html`, `dashboard/static/app.js`, `dashboard/static/style.css`

#### Teams Monitoring (Tab 7)
- `team_sessions` + `team_tasks` SQLite tables with full CRUD
- `team_launcher.py`: Session lifecycle management (validate, create worktree, run agents, auto-commit, cleanup)
- `worktree.py`: Git worktree operations (create, remove, list, cleanup stale)
- REST: `GET/POST /api/teams/*` — templates, launch, session details, diff, merge, discard, cancel
- WebSocket: `/ws/teams` for real-time team session updates

#### General Manager (Tab 8)
- `gm.py`: Automated pipeline — launch → wait → analyze → merge → build → test → done
- Merge strategy: Score branches by file overlap, sort ascending (least-conflicting first)
- Claude integration: Spawns `claude -p` subprocesses for conflict resolution, build/test fixes
- Approval gate: Pipeline pauses on merge conflicts, build failures, test failures
- Decision cards broadcast via `/ws/gm` WebSocket channel
- REST: `GET/POST /api/gm/*` — templates, launch, projects, cancel, retry, push, decisions
- `gm_decisions` table tracks decision_id, type, description, proposed_action, context, status

#### WebSocket Heartbeat
- Server pings all connected clients every 30s
- Clients respond with pong within 10s timeout
- Stale connections automatically cleaned up
- Applied across all 4 WebSocket channels (`/ws/status`, `/ws/logs`, `/ws/teams`, `/ws/gm`)
- `_all_connections` set tracks every WebSocket for unified heartbeat

#### Frontend
- 8 tabbed panels: Overview, Agents, History, Logs, Control, Costs, Teams, GM
- Teams tab: session table, detail modal with teammate outputs, status badges
- GM tab: project pipeline view, yellow-bordered pulsing decision cards with Approve/Reject buttons
- Ping/pong handlers in all WebSocket connections

### 5. Helper Scripts

| Script | Purpose |
|--------|---------|
| `scripts/launch-team.sh` | Quick team launcher — validates team name, runs via orchestrator or direct CLI |
| `scripts/team-status.sh` | Check active sessions — shows `~/.claude/tasks/` state, team outputs, process status |
| `scripts/dashboard.sh` | Start dashboard — auto-installs deps, configurable port |

### 6. Resource Safety

- **Shared `CARGO_TARGET_DIR`** — Rust projects share a single target directory across all worktrees
- **Critical error auto-kill** — Agents that hit `No space left on device`, `ENOSPC`, `cannot allocate memory` twice are automatically killed
- **Worktree `target/` cleanup** — After each agent completes, any worktree-local `target/` is removed

### 7. Dependency Updates (2026-02-09)

| Before | After | Reason |
|--------|-------|--------|
| `serde_yaml` 0.9 | `serde_yml` 0.0.12 | `serde_yaml` deprecated |
| `dotenv` 0.15 | `dotenvy` 0.15 | `dotenv` unmaintained |
| `reqwest` 0.11 | `reqwest` 0.12 | Major version update |
| `thiserror` 1.0 | (removed) | Unused dependency |
| — | `pydantic` | Missing from dashboard requirements |

### 8. Other Hardening (2026-02-09)

- `.gitignore`: `dashboard/dashboard.db` → `dashboard/dashboard.db*` (covers WAL/SHM files)
- `dashboard/config.py`: Default HOST `0.0.0.0` → `127.0.0.1` (security)
- `.github/workflows/rust-workflow.yml`: `actions/cache@v3` → `@v4`
- `.env.example`: Added `CLAUDE_CLI_PATH` and `DASHBOARD_HOST` entries

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│               Dashboard (FastAPI)                     │
│  Port 8080 — 8 tabs including Teams + GM monitoring   │
│  SQLite DB — executions, team_sessions, gm_decisions  │
│  WebSocket — /ws/status, /ws/logs, /ws/teams, /ws/gm │
│  Heartbeat — ping/pong every 30s, 10s timeout         │
└────────────────────┬─────────────────────────────────┘
                     │ watches outputs/ directory
                     │
┌────────────────────┴─────────────────────────────────┐
│            Rust Orchestrator (main.rs)                 │
│                                                       │
│  Modes: auto, research, analysis, monitoring          │
│         + feature-dev, code-review, debug,            │
│           research (Agent Teams)                      │
│                                                       │
│  Client Modes:                                        │
│    api → Anthropic HTTP API (claude-sonnet-4-5)       │
│    claude-code → claude CLI (free, auto-detected)     │
│    hybrid → API with CLI fallback                     │
│    agent-teams → claude CLI + Agent Teams env         │
│                                                       │
│  Outputs: results-*.json, teams-*.json                │
└────────────────────┬─────────────────────────────────┘
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
    ┌──────────┐ ┌────────┐ ┌──────────┐
    │ ApiClient│ │CliClient│ │TeamsClient│
    │ (HTTP)   │ │(claude) │ │(claude +  │
    │          │ │         │ │ teams env)│
    └──────────┘ └────────┘ └──────────┘
                     │
                     ▼
         ┌──────────────────────┐
         │   General Manager     │
         │  launch → wait →      │
         │  analyze → merge →    │
         │  build → test → done  │
         │                       │
         │  Approval gate on:    │
         │  conflicts, build/    │
         │  test failures        │
         └──────────────────────┘
```

---

## Test Results

```
running 15 tests
test client::tests::test_client_mode_from_str ... ok
test client::tests::test_client_mode_display ... ok
test client::tests::test_cli_client_creation ... ok
test client::tests::test_api_client_creation ... ok
test client::tests::test_api_client_with_model ... ok
test client::tests::test_create_client_api_requires_key ... ok
test client::tests::test_create_client_api_with_key ... ok
test client::tests::test_create_client_claude_code ... ok
test client::tests::test_create_client_hybrid_requires_key ... ok
test client::tests::test_create_client_hybrid_with_key ... ok
test client::tests::test_create_client_agent_teams ... ok
test client::tests::test_teams_client_creation ... ok
test client::tests::test_create_agent_client_override ... ok
test client::tests::test_create_agent_client_fallback ... ok
test client::tests::test_create_agent_client_invalid_override ... ok

test result: ok. 15 passed; 0 failed; 0 ignored
```

CI status: build, monitor, orchestrate jobs all passing. Docker job requires `DO_API_TOKEN` secret.

---

## Usage

### Launch a team
```bash
./scripts/launch-team.sh feature-dev "Add user authentication with JWT"
./scripts/launch-team.sh code-review "Review the payment processing module"
./scripts/launch-team.sh debug "Fix the timeout on /api/users endpoint"
./scripts/launch-team.sh research "Explore WebSocket scaling patterns"
```

### Launch a GM project
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
      {"team": "feature-dev", "task": "Add database migrations"}
    ]
  }'
```

### Check team status
```bash
./scripts/team-status.sh
```

### Start the dashboard
```bash
./scripts/dashboard.sh        # port 8080
./scripts/dashboard.sh 9090   # custom port
```

### Run via Rust orchestrator
```bash
# Traditional modes
ORCHESTRATOR_MODE=auto cargo run

# Agent Teams modes
ORCHESTRATOR_MODE=feature-dev CLIENT_MODE=agent-teams cargo run
ORCHESTRATOR_MODE=debug CLIENT_MODE=agent-teams cargo run
```

---

## Files Changed

### New Files
- `CLAUDE.md`
- `AGENT-TEAMS-INTEGRATION.md`
- `scripts/launch-team.sh`
- `scripts/team-status.sh`
- `scripts/dashboard.sh`
- `dashboard/team_launcher.py`
- `dashboard/worktree.py`
- `dashboard/gm.py`

### Modified Files
- `~/.claude/settings.json` — Agent Teams env flag
- `config/orchestra.yml` — Teams definitions + GM projects section
- `src/client.rs` — AgentTeams variant + TeamsClient + CLI auto-detection + model update
- `src/config.rs` — TeamsConfig structs + proper Default impl + serde_yml
- `src/main.rs` — Team mode + parallel error handling + dotenvy
- `Cargo.toml` — reqwest 0.12, serde_yml, dotenvy, removed thiserror
- `dashboard/db.py` — team_sessions + team_tasks + gm_decisions tables
- `dashboard/watcher.py` — Team file ingestion + backfill
- `dashboard/server.py` — Teams/GM REST + WebSocket + heartbeat
- `dashboard/config.py` — Default HOST 127.0.0.1
- `dashboard/requirements.txt` — Added pydantic
- `dashboard/templates/index.html` — 8 tabs (Teams + GM)
- `dashboard/static/app.js` — Teams/GM panels + ping/pong handlers
- `dashboard/static/style.css` — Pulse animations, decision cards
- `.env.example` — CLAUDE_CLI_PATH, DASHBOARD_HOST, Agent Teams vars
- `.gitignore` — dashboard.db* glob, scripts log/tmp
- `.github/workflows/rust-workflow.yml` — actions/cache@v4
