# Agent Orchestra

Multi-agent AI orchestration system with Rust backend, FastAPI dashboard, and Claude Agent Teams integration.

## Project Structure

```
src/           → Rust orchestrator (main.rs, config.rs, client.rs, agents.rs)
dashboard/     → Python FastAPI dashboard (port 8080)
config/        → orchestra.yml runtime configuration
scripts/       → Helper scripts (launch-team, team-status, dashboard)
outputs/       → Generated results (JSON + TXT)
.claude/       → Claude Code config (agents, skills, commands)
```

## Quick Commands

```bash
# Build & test Rust
cargo build --release && cargo test

# Run orchestrator
ORCHESTRATOR_MODE=auto CLIENT_MODE=claude-code cargo run

# Start dashboard
python3 -m dashboard.server

# Launch a team
./scripts/launch-team.sh feature-dev "Build user auth"
./scripts/launch-team.sh code-review "Review PR #42"

# Check team status
./scripts/team-status.sh
```

## Team Templates (config/orchestra.yml)

- **feature-dev**: architect + implementer + reviewer — full feature lifecycle
- **code-review**: security-reviewer + style-reviewer — thorough code review
- **debug**: reproducer + analyzer + fixer — systematic debugging
- **research**: searcher + synthesizer — research and summarize topics

## Client Modes

| Mode | Implementation | Cost |
|------|----------------|------|
| `claude-code` | CliClient (subprocess) | Free |
| `api` | ApiClient (HTTP) | Paid |
| `hybrid` | API with CLI fallback | Flexible |
| `agent-teams` | TeamsClient (Opus 4.6) | Per-session |

Per-agent overrides via `client_mode` in orchestra.yml.

## Dashboard (FastAPI)

8 tabs: Overview, Agents, History, Logs, Control, Costs, Teams, GM

Key modules: `server.py` (REST + WS endpoints), `db.py` (SQLite via aiosqlite), `orchestrator.py` (subprocess control), `watcher.py` (file monitoring), `team_launcher.py` (session management), `worktree.py` (git worktree isolation), `gm.py` (General Manager pipeline).

## General Manager (GM)

Automated multi-agent lifecycle: launch → wait → analyze → merge → build → test → done.

- **Pipeline phases**: launching → waiting → analyzing → merging → building → testing → completed/failed
- **Merge strategy**: Score branches by file overlap, sort ascending (least-conflicting first), merge sequentially
- **Claude integration**: Spawns `claude -p` subprocesses for conflict resolution, build fixes, test fixes
- **Approval gate**: Pipeline pauses on merge conflicts, build failures, and test failures — broadcasts a decision card to the dashboard and waits for user to Approve (proceed with Claude fix) or Reject (skip/fail). Uses `asyncio.Event` per decision for zero-cost blocking.
- **Decisions DB**: `gm_decisions` table tracks decision_id, type, description, proposed_action, context, status (pending/approved/rejected)
- **Config**: `gm_projects:` section in `config/orchestra.yml` defines project templates with agents, build/test commands
- **Endpoints**: `/api/gm/templates`, `/api/gm/launch`, `/api/gm/projects`, `/api/gm/projects/{id}/cancel|retry|push`, `/api/gm/projects/{id}/decisions`, `/api/gm/decisions/{id}/resolve`
- **WebSocket**: `/ws/gm` broadcasts `gm_progress` events including `decision_required` and `decision_resolved` for real-time UI updates
- **Dashboard UI**: Yellow-bordered pulsing decision cards with problem description, proposed action, error context preview, and Approve/Reject buttons

## Key Patterns

- **Data flow**: Config → AgentTask → AgentClient → AgentResult → JSON output
- **AgentClient trait**: `async send_message(prompt, system_prompt) → Result<String>`
- **Team isolation**: Each team session gets its own git worktree + branch (`team/{session_id}`)
- **Real-time updates**: WebSocket channels for status, logs, team progress

## Claude Code Workflows

- `/launch` — Launch a team session (validate, create worktree, run)
- `/status` — Check teams, worktrees, dashboard, recent outputs
- `/review` — Review team diff, invoke reviewer, merge/discard

## Conventions

- Rust: `cargo fmt` + `cargo clippy` before committing
- Python: standard library style, async everywhere
- Config: YAML in `config/`, env vars in `.env`
- Output files: `outputs/results-*.json`, `outputs/teams-*.json`
- All timestamps in UTC ISO-8601
