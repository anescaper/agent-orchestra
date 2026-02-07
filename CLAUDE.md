# Agent Orchestra

Multi-agent AI orchestration system with Rust backend, FastAPI dashboard, and Claude Agent Teams integration.

## Project Structure

```
src/           → Rust orchestrator (client modes: api, claude-code, hybrid, agent-teams)
dashboard/     → Python FastAPI monitoring dashboard (port 8080)
config/        → orchestra.yml runtime configuration
scripts/       → Helper scripts (launch-team, team-status, dashboard)
outputs/       → Generated results (JSON + TXT)
```

## Quick Commands

```bash
# Build & test Rust
cargo build --release
cargo test

# Run orchestrator
ORCHESTRATOR_MODE=auto CLIENT_MODE=claude-code cargo run

# Start dashboard
python3 -m dashboard.server

# Launch a team
./scripts/launch-team.sh feature-dev "Build user auth"
./scripts/launch-team.sh code-review "Review PR #42"
./scripts/launch-team.sh debug "Fix login timeout"
./scripts/launch-team.sh research "Explore agent patterns"

# Check team status
./scripts/team-status.sh
```

## Team Templates

Defined in `config/orchestra.yml` under the `teams:` section:

- **feature-dev**: architect + implementer + reviewer — full feature lifecycle
- **code-review**: security-reviewer + style-reviewer — thorough code review
- **debug**: reproducer + analyzer + fixer — systematic debugging
- **research**: searcher + synthesizer — research and summarize topics

## Architecture

### Client Modes
| Mode | Description | Cost |
|------|-------------|------|
| `claude-code` | CLI (`claude -p`) | Free |
| `api` | Anthropic HTTP API | Paid |
| `hybrid` | API with CLI fallback | Flexible |
| `agent-teams` | Claude Agent Teams (Opus 4.6) | Per-session |

### Dashboard Tabs
1. **Overview** — Stats, recent executions, orchestrator status
2. **Agents** — Per-agent performance metrics
3. **History** — Paginated execution history with detail modal
4. **Logs** — Live log stream via WebSocket
5. **Control** — Start/stop orchestrator, view config
6. **Costs** — Cost breakdown by mode, agent, date
7. **Teams** — Live Agent Teams session monitoring

## Conventions

- Rust: `cargo fmt` + `cargo clippy` before committing
- Python: standard library style, async everywhere
- Config: YAML in `config/`, env vars in `.env`
- Output files: `outputs/results-*.json` (orchestrator), `outputs/teams-*.json` (teams)
- All timestamps in UTC ISO-8601
