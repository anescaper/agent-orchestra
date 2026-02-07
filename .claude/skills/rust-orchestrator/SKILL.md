# Rust Orchestrator

Core orchestration engine in `src/`.

## File Map

| File | Lines | Purpose |
|------|-------|---------|
| `main.rs` | 420 | Entry point, `Orchestrator` struct, sequential/parallel execution |
| `config.rs` | 245 | YAML config parsing, `Config` + nested structs, defaults |
| `client.rs` | 465 | `AgentClient` trait, 4 client implementations |
| `agents.rs` | 72 | `AgentTask` + `AgentResult` data structures |

## Architecture

```
Config (YAML) → AgentTask → AgentClient → AgentResult → OrchestrationResult → JSON
```

### Client Mode System

```rust
enum ClientMode { Api, ClaudeCode, Hybrid, AgentTeams }

trait AgentClient: Send + Sync {
    async fn send_message(&self, prompt: &str, system_prompt: Option<&str>) -> Result<String>;
}
```

| Mode | Struct | How |
|------|--------|-----|
| Api | `ApiClient` | POST to `api.anthropic.com/v1/messages` |
| ClaudeCode | `CliClient` | Subprocess `claude -p "prompt"` |
| Hybrid | `HybridClient` | Try API, fallback CLI |
| AgentTeams | `TeamsClient` | CLI with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` |

Factory: `create_client(mode)` / `create_agent_client(mode, agent_config)` — agent override > global.

### Execution Modes

`Orchestrator::get_agent_tasks(mode)`:
- `auto` → monitor + analyzer
- `research` → researcher + synthesizer
- `analysis` → data_analyst + reporter
- `monitoring` → health_checker + alert_manager
- `{team_name}` → teammates from config with client_mode=agent-teams

### Build

```bash
cargo build --release    # opt-level=3, lto=true, strip=true
cargo test
cargo fmt && cargo clippy
```

## Key Dependencies

tokio 1.35, reqwest 0.11, serde/serde_json/serde_yaml, anyhow, thiserror, chrono, tracing, async-trait
