# 🦀 Rust Agent Orchestra - Setup Guide

## 🎯 What This Is
A high-performance, self-running AI agent orchestration system built in Rust that:
- Runs blazingly fast with minimal memory footprint
- Automatically coordinates multiple AI agents on a schedule
- Deploys to DigitalOcean with GitHub Actions
- Produces reliable, production-ready results

## 📁 Project Structure

```
agent-orchestra/
├── .github/
│   └── workflows/
│       └── rust-workflow.yml        # CI/CD pipeline
├── src/
│   ├── main.rs                      # Main orchestrator
│   ├── client.rs                    # Claude API client
│   ├── agents.rs                    # Agent definitions
│   └── config.rs                    # Configuration
├── config/
│   └── orchestra.yml                # Runtime configuration
├── outputs/                         # Generated results
├── Cargo.toml                       # Dependencies
├── Cargo.lock                       # Lock file
├── Dockerfile                       # Container image
└── .env.example                     # Environment template
```

## 🚀 Quick Start

### 1. Install Rust

```bash
# Install Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Verify installation
rustc --version
cargo --version
```

### 2. Clone and Setup

```bash
# Clone your repository
git clone <your-repo-url>
cd agent-orchestra

# Create environment file
cp .env.example .env

# Edit .env and add your API key
nano .env
```

### 3. Local Development

```bash
# Build the project
cargo build

# Run tests
cargo test

# Run locally
cargo run

# Or with specific mode
ORCHESTRATOR_MODE=research cargo run

# Build optimized release
cargo build --release
```

### 4. Project File Structure

Create this directory structure:

```bash
mkdir -p src config outputs .github/workflows
```

Then place the files:
- `src/main.rs` ← main.rs content
- `src/client.rs` ← client.rs content
- `src/agents.rs` ← agents.rs content
- `src/config.rs` ← config.rs content
- `config/orchestra.yml` ← your config file
- `.github/workflows/rust-workflow.yml` ← CI/CD workflow
- `Cargo.toml` ← dependencies
- `Dockerfile` ← container config

### 5. GitHub Setup

Add these secrets to your GitHub repo (Settings → Secrets):

```
ANTHROPIC_API_KEY - Your Claude API key
DO_API_TOKEN - DigitalOcean API token
DO_APP_ID - DigitalOcean App ID (optional)
```

### 6. DigitalOcean Setup

```bash
# Install doctl
curl -sL https://github.com/digitalocean/doctl/releases/download/v1.104.0/doctl-1.104.0-linux-amd64.tar.gz | tar -xzv
sudo mv doctl /usr/local/bin

# Authenticate
doctl auth init

# Create container registry
doctl registry create agent-orchestra

# (Optional) Create app
doctl apps create --spec <(cat <<EOF
name: agent-orchestra
region: nyc
services:
- name: orchestrator
  github:
    repo: your-username/your-repo
    branch: main
  run_command: ./agent-orchestra
  envs:
  - key: ANTHROPIC_API_KEY
    scope: RUN_TIME
    type: SECRET
EOF
)
```

## 🎮 Usage

### Running Locally

```bash
# Default mode (auto)
cargo run

# Specific mode
ORCHESTRATOR_MODE=research cargo run

# With logging
RUST_LOG=debug cargo run

# Production build
cargo build --release
./target/release/agent-orchestra
```

### Running in Docker

```bash
# Build image
docker build -t agent-orchestra .

# Run container
docker run \
  -e ANTHROPIC_API_KEY=your_key \
  -e ORCHESTRATOR_MODE=auto \
  -v $(pwd)/outputs:/app/outputs \
  agent-orchestra
```

### GitHub Actions

**Automatic (Scheduled):**
- Runs every hour automatically
- Set in `.github/workflows/rust-workflow.yml`

**Manual Trigger:**
1. Go to Actions → Rust Agent Orchestra Pipeline
2. Click "Run workflow"
3. Select mode: auto, research, analysis, or monitoring

**On Push:**
- Automatically runs when you push to `main`
- Builds, tests, and deploys

## 🔧 Configuration

### Schedule

Edit `.github/workflows/rust-workflow.yml`:

```yaml
schedule:
  - cron: '0 * * * *'     # Every hour (default)
  # - cron: '*/30 * * * *'  # Every 30 minutes
  # - cron: '0 */6 * * *'   # Every 6 hours
  # - cron: '0 9 * * *'     # Daily at 9 AM
```

### Agent Tasks

Edit `src/main.rs` in the `get_agent_tasks()` method:

```rust
"custom" => vec![
    AgentTask::new(
        "my_agent",
        "Custom task prompt here"
    ),
],
```

### Config File

Edit `config/orchestra.yml` for runtime settings:
- Enable/disable agents
- Set timeouts
- Configure outputs
- DigitalOcean settings

## 📊 Performance

**Rust vs Python:**
- 🚀 **Speed:** ~10-50x faster
- 💾 **Memory:** ~5-10x less
- ⚡ **Startup:** Milliseconds vs seconds
- 📦 **Binary:** ~5MB vs ~100MB+ with dependencies

**Production Benefits:**
- Minimal CPU usage on DigitalOcean
- Lower costs (smaller droplets work fine)
- Faster execution means quicker results
- More reliable for long-running operations

## 🛠️ Development Tips

### Code Quality

```bash
# Format code
cargo fmt

# Lint
cargo clippy

# Check without building
cargo check

# Watch mode (requires cargo-watch)
cargo install cargo-watch
cargo watch -x run
```

### Testing

```bash
# Run all tests
cargo test

# Run specific test
cargo test test_name

# With output
cargo test -- --nocapture
```

### Debugging

```rust
// Add to any file
use tracing::{debug, info, warn, error};

// In code
debug!("Debug message: {}", variable);
info!("Info message");
warn!("Warning!");
error!("Error occurred: {}", error);
```

## 🔍 Troubleshooting

**Build fails?**
```bash
cargo clean
cargo build
```

**API errors?**
- Check `ANTHROPIC_API_KEY` is set
- Verify API key is valid
- Check network connectivity

**Docker issues?**
```bash
# Rebuild without cache
docker build --no-cache -t agent-orchestra .

# Check logs
docker logs <container-id>
```

**GitHub Actions fails?**
- Verify secrets are set correctly
- Check workflow logs in Actions tab
- Ensure Rust toolchain matches (1.75+)

## 📈 Next Steps

1. **Add custom agents** in `src/agents/`
2. **Implement parallel execution** with `tokio::spawn`
3. **Add database** for persistent storage
4. **Set up monitoring** with Prometheus/Grafana
5. **Add web API** for external triggering
6. **Implement retries** for failed agents
7. **Add metrics** collection

## 🔗 Useful Commands

```bash
# Update dependencies
cargo update

# Add dependency
cargo add <crate-name>

# Check outdated deps
cargo install cargo-outdated
cargo outdated

# Benchmark
cargo bench

# Documentation
cargo doc --open

# Release build with all optimizations
cargo build --release --target x86_64-unknown-linux-musl
```

## 🎨 Customization Examples

### Add a New Agent

```rust
// In src/main.rs, add to get_agent_tasks():
"monitoring" => vec![
    AgentTask::new(
        "security_checker",
        "Scan for security vulnerabilities and potential threats."
    ),
],
```

### Parallel Execution

```rust
// In src/main.rs orchestrate():
use futures::future::join_all;

let futures = tasks.into_iter()
    .map(|task| self.run_agent(task));

let results = join_all(futures).await;
```

### Add Retry Logic

```rust
// In client.rs:
pub async fn send_message_with_retry(&self, prompt: &str) -> Result<String> {
    for attempt in 1..=3 {
        match self.send_message(prompt).await {
            Ok(response) => return Ok(response),
            Err(e) if attempt < 3 => {
                tokio::time::sleep(Duration::from_secs(attempt * 2)).await;
                continue;
            }
            Err(e) => return Err(e),
        }
    }
    unreachable!()
}
```

---

**Made with 🦀 Rust - Fast, Reliable, Productive**
