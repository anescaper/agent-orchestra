#!/usr/bin/env bash
# Launch an Agent Teams session with a predefined team template.
# Usage: ./scripts/launch-team.sh <team-name> "<task-description>"
#
# Team names: feature-dev, code-review, debug, research

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

if [ $# -lt 2 ]; then
    echo "Usage: $0 <team-name> <task-description>"
    echo ""
    echo "Available teams:"
    echo "  feature-dev   — architect + implementer + reviewer"
    echo "  code-review   — security-reviewer + style-reviewer"
    echo "  debug         — reproducer + analyzer + fixer"
    echo "  research      — searcher + synthesizer"
    echo ""
    echo "Example:"
    echo "  $0 feature-dev \"Add user authentication with JWT\""
    exit 1
fi

TEAM_NAME="$1"
TASK_DESC="$2"

# Validate team name
case "$TEAM_NAME" in
    feature-dev|code-review|debug|research)
        ;;
    *)
        echo "Error: Unknown team '$TEAM_NAME'"
        echo "Available teams: feature-dev, code-review, debug, research"
        exit 1
        ;;
esac

echo "=== Agent Orchestra — Team Launch ==="
echo "Team:  $TEAM_NAME"
echo "Task:  $TASK_DESC"
echo "Time:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "======================================"

# Option 1: Use the Rust orchestrator with teams mode
if [ -f "$PROJECT_DIR/target/release/agent-orchestra" ]; then
    echo "Launching via Rust orchestrator..."
    ORCHESTRATOR_MODE="$TEAM_NAME" \
    CLIENT_MODE="agent-teams" \
    RUST_LOG=info \
    "$PROJECT_DIR/target/release/agent-orchestra"
else
    # Option 2: Direct claude invocation with Agent Teams
    echo "Launching via claude CLI (direct)..."
    CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 \
    claude -p "[TEAM: $TEAM_NAME] $TASK_DESC"
fi

echo ""
echo "Team session complete. Check outputs/ for results."
