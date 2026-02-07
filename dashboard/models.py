"""Pydantic models for API responses."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AgentResultModel(BaseModel):
    agent: str
    status: str  # "success" | "failed"
    output: Optional[str] = None
    error: Optional[str] = None
    client_mode: Optional[str] = None
    timestamp: Optional[str] = None


class ExecutionModel(BaseModel):
    id: Optional[int] = None
    timestamp: str
    mode: str
    global_client_mode: Optional[str] = None
    filename: Optional[str] = None
    agent_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    estimated_cost: float = 0.0


class ExecutionDetailModel(ExecutionModel):
    results: list[AgentResultModel] = []


class AgentSummary(BaseModel):
    agent: str
    total_runs: int = 0
    successes: int = 0
    failures: int = 0
    last_status: Optional[str] = None
    last_run: Optional[str] = None
    avg_output_len: float = 0.0


class StatsModel(BaseModel):
    total_executions: int = 0
    total_agents_run: int = 0
    success_rate: float = 0.0
    total_cost: float = 0.0
    last_execution: Optional[str] = None


class CostBreakdown(BaseModel):
    total_cost: float = 0.0
    by_mode: dict[str, float] = {}
    by_agent: dict[str, float] = {}
    by_date: dict[str, float] = {}


class OrchestratorStatus(BaseModel):
    running: bool = False
    pid: Optional[int] = None
    mode: Optional[str] = None
    client_mode: Optional[str] = None
    started_at: Optional[str] = None


class LogEntry(BaseModel):
    timestamp: str
    level: str  # "info" | "error" | "warn"
    message: str
    source: Optional[str] = None
