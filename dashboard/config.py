"""Dashboard configuration - paths, port, env var defaults."""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
CONFIG_FILE = BASE_DIR / "config" / "orchestra.yml"
DB_PATH = DASHBOARD_DIR / "dashboard.db"

# Server
HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
PORT = int(os.getenv("DASHBOARD_PORT", "8080"))

# Orchestrator binary
ORCHESTRATOR_BIN = os.getenv(
    "ORCHESTRATOR_BIN",
    str(BASE_DIR / "target" / "release" / "agent-orchestra"),
)
ORCHESTRATOR_CWD = str(BASE_DIR)

# Cost estimation (per 1M tokens)
COST_PER_1M_INPUT = float(os.getenv("COST_PER_1M_INPUT", "3.0"))
COST_PER_1M_OUTPUT = float(os.getenv("COST_PER_1M_OUTPUT", "15.0"))
CHARS_PER_TOKEN = 4  # rough heuristic

# Templates & static
TEMPLATES_DIR = DASHBOARD_DIR / "templates"
STATIC_DIR = DASHBOARD_DIR / "static"
