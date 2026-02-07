#!/usr/bin/env bash
# Check the status of active Agent Teams sessions.
# Reads from ~/.claude/tasks/ directory.

set -euo pipefail

TASKS_DIR="${HOME}/.claude/tasks"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUTS_DIR="$PROJECT_DIR/outputs"

echo "=== Agent Orchestra — Team Status ==="
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# Check claude tasks directory
echo "--- Claude Tasks Directory ---"
if [ -d "$TASKS_DIR" ]; then
    TASK_COUNT=$(find "$TASKS_DIR" -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
    echo "Location: $TASKS_DIR"
    echo "Task files: $TASK_COUNT"
    if [ "$TASK_COUNT" -gt 0 ]; then
        echo ""
        find "$TASKS_DIR" -name "*.json" -exec echo "  {}" \; 2>/dev/null
    fi
else
    echo "No tasks directory found at $TASKS_DIR"
fi

echo ""

# Check team output files
echo "--- Team Output Files ---"
if [ -d "$OUTPUTS_DIR" ]; then
    TEAM_COUNT=$(find "$OUTPUTS_DIR" -name "teams-*.json" 2>/dev/null | wc -l | tr -d ' ')
    echo "Location: $OUTPUTS_DIR"
    echo "Team result files: $TEAM_COUNT"
    if [ "$TEAM_COUNT" -gt 0 ]; then
        echo ""
        echo "Recent team results:"
        ls -lt "$OUTPUTS_DIR"/teams-*.json 2>/dev/null | head -5
    fi
else
    echo "No outputs directory found"
fi

echo ""

# Check if orchestrator is running
echo "--- Orchestrator Process ---"
if pgrep -f "agent-orchestra" > /dev/null 2>&1; then
    echo "Status: Running"
    pgrep -af "agent-orchestra" 2>/dev/null
else
    echo "Status: Not running"
fi

echo ""
echo "======================================"
