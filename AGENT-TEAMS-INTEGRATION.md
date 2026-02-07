# Agent Orchestra + Agent Teams Integration

**Date:** 2026-02-08
**Status:** Implemented

## Overview

This document records the integration of Claude Code's native **Agent Teams** feature (Opus 4.6) into the existing Agent Orchestra system. The goal: use Agent Teams as a new execution engine while keeping the Rust orchestrator for coordination and the FastAPI dashboard for monitoring/scheduling.

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
  - Resolves CLI path from `CLAUDE_CLI_PATH` env, `/usr/local/bin/claude`, or bare `claude`
  - Prepends `[TEAM CONTEXT: ...]` prefix for system prompts
- Updated factory function `create_client()` to handle `agent-teams` mode
- Added tests: `test_create_client_agent_teams`, `test_teams_client_creation`

#### config.rs
- New structs: `TeamsConfig`, `TeamDefinition`, `TeammateDefinition`
- `TeamsConfig` has `enabled`, `tasks_dir`, `output_prefix`, and `definitions` HashMap
- Added `teams` field to root `Config` struct with `#[serde(default)]`

#### main.rs
- `get_agent_tasks()` now checks if the mode matches a team definition name
- When a team mode is detected, creates `AgentTask` for each teammate with `agent-teams` client mode
- `save_results()` uses the team output prefix (`teams-*.json`) for team mode runs

### 4. Dashboard: Teams Monitoring Tab

**Files changed:** `dashboard/db.py`, `dashboard/watcher.py`, `dashboard/server.py`, `dashboard/templates/index.html`, `dashboard/static/app.js`, `dashboard/static/style.css`

#### db.py — New Tables
- `team_sessions`: id, session_id, team_name, task_description, status, started_at, completed_at, filename, teammate_count, success_count, fail_count
- `team_tasks`: id, session_id (FK), teammate, role, status, output, error, started_at, completed_at
- New CRUD functions: `insert_team_session()`, `insert_team_task()`, `get_team_sessions()`, `get_team_session()`, `get_team_tasks()`, `get_team_session_count()`, `team_session_exists()`

#### watcher.py — Team File Ingestion
- `ingest_team_result_file()`: Parses `teams-*.json` files into DB
- `backfill_team_outputs()`: Scans for existing team results on startup
- `watch_outputs()` now accepts `on_new_team_session` callback and watches for `teams-*.json` files

#### server.py — New REST + WebSocket Endpoints
- `GET /api/teams` — List team sessions (paginated)
- `GET /api/teams/{id}` — Team session detail with tasks
- `GET /api/teams/{id}/tasks` — Tasks for a specific session
- `WS /ws/teams` — Real-time team session updates
- `ConnectionManager` extended with `_teams_connections` list

#### Frontend — 7th "Teams" Tab
- New tab button and panel in `index.html`
- Stats cards: total sessions, active count
- Clickable session table with detail modal
- Detail modal shows teammate outputs with status badges
- Teams WebSocket auto-refreshes on new session events
- Pulse animation CSS for running sessions

### 5. Helper Scripts

| Script | Purpose |
|--------|---------|
| `scripts/launch-team.sh` | Quick team launcher — validates team name, runs via orchestrator or direct CLI |
| `scripts/team-status.sh` | Check active sessions — shows `~/.claude/tasks/` state, team outputs, process status |
| `scripts/dashboard.sh` | Start dashboard — auto-installs deps, configurable port |

### 6. Project Files

- **CLAUDE.md**: Project conventions, quick commands, team templates, architecture table
- **.env.example**: Added `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, `TEAM_DEFAULT`, `TEAM_MAX_AGENTS`, `TEAM_TIMEOUT`, `DASHBOARD_PORT`
- **.gitignore**: Added `scripts/*.log` and `scripts/*.tmp` (scripts themselves are tracked)

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 Dashboard (FastAPI)              │
│  Port 8080 — 7 tabs including Teams monitoring   │
│  SQLite DB — executions + team_sessions tables   │
│  WebSocket — /ws/status, /ws/logs, /ws/teams     │
└────────────────────┬────────────────────────────┘
                     │ watches outputs/ directory
                     │
┌────────────────────┴────────────────────────────┐
│            Rust Orchestrator (main.rs)           │
│                                                  │
│  Modes: auto, research, analysis, monitoring     │
│         + feature-dev, code-review, debug,       │
│           research (Agent Teams)                 │
│                                                  │
│  Client Modes:                                   │
│    api → Anthropic HTTP API                      │
│    claude-code → claude CLI (free)               │
│    hybrid → API with CLI fallback                │
│    agent-teams → claude CLI + Agent Teams env    │
│                                                  │
│  Outputs: results-*.json, teams-*.json           │
└────────────────────┬────────────────────────────┘
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
    ┌──────────┐ ┌────────┐ ┌──────────┐
    │ ApiClient│ │CliClient│ │TeamsClient│
    │ (HTTP)   │ │(claude) │ │(claude +  │
    │          │ │         │ │ teams env)│
    └──────────┘ └────────┘ └──────────┘
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

---

## Usage

### Launch a team
```bash
./scripts/launch-team.sh feature-dev "Add user authentication with JWT"
./scripts/launch-team.sh code-review "Review the payment processing module"
./scripts/launch-team.sh debug "Fix the timeout on /api/users endpoint"
./scripts/launch-team.sh research "Explore WebSocket scaling patterns"
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

### Modified Files
- `~/.claude/settings.json` — Agent Teams env flag
- `config/orchestra.yml` — Teams definitions section
- `src/client.rs` — AgentTeams variant + TeamsClient
- `src/config.rs` — TeamsConfig, TeamDefinition, TeammateDefinition structs
- `src/main.rs` — Team mode in get_agent_tasks(), teams output prefix
- `dashboard/db.py` — team_sessions + team_tasks tables and CRUD
- `dashboard/watcher.py` — Team file ingestion + backfill
- `dashboard/server.py` — Teams REST endpoints + WebSocket
- `dashboard/templates/index.html` — Teams tab
- `dashboard/static/app.js` — Teams panel logic + WebSocket
- `dashboard/static/style.css` — Pulse animation for running sessions
- `.env.example` — Agent Teams env vars
- `.gitignore` — Scripts log/tmp ignore rules
