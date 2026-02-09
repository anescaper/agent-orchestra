# Rust Agent Orchestra - Setup Guide

## What This Is

A multi-agent orchestration system built in Rust that:
- Coordinates multiple AI agents (Claude) running in parallel or sequentially
- Supports 4 client modes: CLI (free), HTTP API (paid), hybrid, and Agent Teams
- Includes a FastAPI dashboard with 8 monitoring tabs and real-time WebSocket updates
- Features an automated General Manager pipeline for multi-agent branch merging
- Deploys to DigitalOcean with GitHub Actions

## Project Structure

```
agent-orchestra/
├── src/
│   ├── main.rs                      # Orchestrator + parallel/sequential execution
│   ├── client.rs                    # AgentClient trait + 4 implementations
│   ├── agents.rs                    # AgentTask + AgentResult types
│   └── config.rs                    # YAML config parsing (serde_yml)
├── dashboard/
│   ├── server.py                    # FastAPI REST + WebSocket + heartbeat
│   ├── gm.py                       # General Manager pipeline
│   ├── team_launcher.py            # Team session lifecycle
│   ├── worktree.py                 # Git worktree operations
│   ├── db.py                       # SQLite schema + queries
│   ├── config.py                   # Dashboard configuration
│   ├── orchestrator.py             # Rust binary subprocess control
│   ├── watcher.py                  # File system monitoring
│   ├── models.py                   # Pydantic API models
│   ├── requirements.txt            # Python dependencies
│   ├── static/                     # Frontend JS + CSS
│   └── templates/                  # Jinja2 HTML
├── config/
│   └── orchestra.yml               # Master configuration
├── scripts/
│   ├── dashboard.sh                # Start dashboard
│   ├── launch-team.sh              # Launch team session
│   └── team-status.sh              # Check team status
├── .github/workflows/
│   └── rust-workflow.yml           # CI: fmt, clippy, test, build, deploy
├── Dockerfile                      # Multi-stage build (Rust + Node.js runtime)
├── Cargo.toml                      # Rust dependencies
└── .env.example                    # Environment variables template
```

## Quick Start

### 1. Install Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustc --version
cargo --version
```

### 2. Clone and Setup

```bash
git clone https://github.com/anescaper/agent-orchestra.git
cd agent-orchestra
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY if using api/hybrid mode
```

### 3. Build and Run

```bash
# Build
cargo build --release

# Run tests (15 tests)
cargo test

# Run orchestrator
ORCHESTRATOR_MODE=auto CLIENT_MODE=claude-code cargo run

# Install Python deps and start dashboard
pip install -r dashboard/requirements.txt
python3 -m dashboard.server
# Dashboard at http://localhost:8080
```

### 4. GitHub Secrets (for CI/CD)

Add these to your GitHub repo (Settings > Secrets):

| Secret | Required For |
|--------|-------------|
| `ANTHROPIC_API_KEY` | API/hybrid client modes |
| `DO_API_TOKEN` | Docker build + push to DigitalOcean registry |
| `DO_APP_ID` | DigitalOcean App Platform deployment |

## Dependencies

### Rust (Cargo.toml)

| Crate | Version | Purpose |
|-------|---------|---------|
| `tokio` | 1.35 | Async runtime (full features) |
| `reqwest` | 0.12 | HTTP client for API calls (rustls-tls) |
| `serde` / `serde_json` | 1.0 | Serialization |
| `serde_yml` | 0.0.12 | YAML config parsing |
| `anyhow` | 1.0 | Error handling |
| `tracing` / `tracing-subscriber` | 0.1 / 0.3 | Structured logging |
| `chrono` | 0.4 | Timestamps (serde support) |
| `dotenvy` | 0.15 | Environment variable loading |
| `async-trait` | 0.1 | Async trait support |

### Python (dashboard/requirements.txt)

FastAPI, uvicorn, aiosqlite, pydantic, pyyaml, watchfiles, Jinja2

## Client Modes

| Mode | Implementation | Cost | Best For |
|------|---------------|------|----------|
| `claude-code` | `CliClient` — spawns `claude -p` subprocess | Free (subscription) | Simple monitoring tasks |
| `api` | `ApiClient` — HTTP POST to Anthropic API | Paid per token | Analysis with system prompts |
| `hybrid` | `HybridClient` — tries API, falls back to CLI | Flexible | Production reliability |
| `agent-teams` | `TeamsClient` — CLI with Agent Teams enabled | Per session | Multi-agent collaboration |

The CLI path is auto-detected: checks `CLAUDE_CLI_PATH` env, then `/usr/local/bin/claude`, `/home/claude/.local/bin/claude`, then falls back to `claude` on PATH.

## Environment Variables

```bash
CLIENT_MODE=claude-code          # claude-code | api | hybrid | agent-teams
ANTHROPIC_API_KEY=sk-ant-...     # Required for api/hybrid modes
CLAUDE_CLI_PATH=/usr/local/bin/claude  # Optional: override CLI auto-detection
ORCHESTRATOR_MODE=auto           # auto | research | analysis | monitoring | <team-name>
DASHBOARD_HOST=127.0.0.1        # Dashboard bind address
DASHBOARD_PORT=8080              # Dashboard port
RUST_LOG=info                    # Log level
```

## Usage

### Running Locally

```bash
# Default mode (auto)
cargo run

# Specific mode
ORCHESTRATOR_MODE=research cargo run

# Agent Teams mode
ORCHESTRATOR_MODE=feature-dev CLIENT_MODE=agent-teams cargo run

# With debug logging
RUST_LOG=debug cargo run

# Production build
cargo build --release
./target/release/agent-orchestra
```

### Running in Docker

```bash
docker build -t agent-orchestra .
docker run -p 8080:8080 \
  -e CLIENT_MODE=claude-code \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  agent-orchestra
```

### Launch a Team Session

```bash
./scripts/launch-team.sh feature-dev "Add user authentication with JWT"
./scripts/launch-team.sh code-review "Review the payment processing module"
./scripts/launch-team.sh debug "Fix the timeout on /api/users endpoint"
```

### Launch a GM Project (via API)

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

### GitHub Actions

The CI pipeline runs on:
- Push to `main` (for `src/`, `Cargo.toml`, `config/` changes)
- Hourly schedule
- Manual dispatch

Jobs: `cargo fmt --check` → `cargo clippy -D warnings` → `cargo test` → `cargo build --release` → Docker build/push → DigitalOcean deploy

## Development

### Code Quality

```bash
cargo fmt          # Format code
cargo clippy       # Lint
cargo check        # Type check without building
cargo test         # Run all 15 tests
cargo test -- --nocapture  # Tests with output
```

### Debugging

```rust
use tracing::{debug, info, warn, error};

debug!("Debug message: {}", variable);
info!("Info message");
warn!("Warning!");
error!("Error occurred: {}", error);
```

Set `RUST_LOG=debug` for verbose output.

## Troubleshooting

**Build fails?**
```bash
cargo clean && cargo build
```

**API errors?**
- Check `ANTHROPIC_API_KEY` is set and valid
- Verify network connectivity

**Docker issues?**
```bash
docker build --no-cache -t agent-orchestra .
docker logs <container-id>
```

**GitHub Actions fails?**
- Verify secrets are set correctly
- Check workflow logs in Actions tab
- Ensure Rust toolchain version is compatible (edition 2021)

**Stale worktrees?**
```bash
git worktree list
git worktree remove --force <path>
git branch -D <orphaned-branch>
```
