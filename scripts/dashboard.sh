#!/usr/bin/env bash
# Start the Agent Orchestra dashboard.
# Usage: ./scripts/dashboard.sh [port]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DASHBOARD_DIR="$PROJECT_DIR/dashboard"

PORT="${1:-8080}"

echo "=== Agent Orchestra Dashboard ==="
echo "Port:    $PORT"
echo "URL:     http://localhost:$PORT"
echo "Project: $PROJECT_DIR"
echo "================================="
echo ""

cd "$PROJECT_DIR"

# Check Python dependencies
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "Installing dashboard dependencies..."
    pip3 install -r "$DASHBOARD_DIR/requirements.txt"
fi

DASHBOARD_PORT="$PORT" python3 -m dashboard.server
