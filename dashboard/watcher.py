"""File watcher for outputs/ directory - backfill and live monitoring."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from watchfiles import awatch, Change

from . import config, db

log = logging.getLogger("dashboard.watcher")


def estimate_cost(text: str | None, client_mode: str | None) -> float:
    """Estimate API cost for a single agent result.

    claude-code mode is free (local CLI), so cost is $0.
    For api/hybrid, use ~4 chars per token heuristic.
    """
    if not text or client_mode == "claude-code":
        return 0.0

    tokens = len(text) / config.CHARS_PER_TOKEN
    # Assume output tokens (conservative - we only see the response)
    cost = (tokens / 1_000_000) * config.COST_PER_1M_OUTPUT
    return round(cost, 6)


async def ingest_result_file(filepath: Path) -> int | None:
    """Parse a results-*.json file and insert into DB. Returns execution id or None."""
    filename = filepath.name

    if await db.execution_exists(filename):
        return None

    try:
        raw = filepath.read_text()
        data = json.loads(raw)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to parse %s: %s", filename, e)
        return None

    results = data.get("results", [])
    success_count = sum(1 for r in results if r.get("status") == "success")
    fail_count = sum(1 for r in results if r.get("status") == "failed")

    total_cost = 0.0
    for r in results:
        total_cost += estimate_cost(r.get("output"), r.get("client_mode"))

    execution_id = await db.insert_execution(
        timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        mode=data.get("mode", "unknown"),
        global_client_mode=data.get("global_client_mode"),
        filename=filename,
        agent_count=len(results),
        success_count=success_count,
        fail_count=fail_count,
        estimated_cost=total_cost,
    )

    for r in results:
        agent_cost = estimate_cost(r.get("output"), r.get("client_mode"))
        await db.insert_agent_result(
            execution_id=execution_id,
            agent=r.get("agent", "unknown"),
            status=r.get("status", "unknown"),
            output=r.get("output"),
            error=r.get("error"),
            client_mode=r.get("client_mode"),
            timestamp=r.get("timestamp"),
            estimated_cost=agent_cost,
        )

    log.info("Ingested %s -> execution #%d (%d agents)", filename, execution_id, len(results))
    return execution_id


async def backfill_existing_outputs() -> int:
    """Scan outputs/ directory and ingest any files not yet in the DB."""
    outputs_dir = config.OUTPUTS_DIR
    if not outputs_dir.is_dir():
        log.warning("Outputs directory does not exist: %s", outputs_dir)
        return 0

    count = 0
    for fp in sorted(outputs_dir.glob("results-*.json")):
        result = await ingest_result_file(fp)
        if result is not None:
            count += 1

    if count:
        log.info("Backfilled %d existing output files", count)
    return count


async def watch_outputs(on_new_execution=None) -> None:
    """Watch the outputs/ directory for new result files.

    Args:
        on_new_execution: optional async callback(execution_id) for notifications
    """
    outputs_dir = config.OUTPUTS_DIR
    outputs_dir.mkdir(parents=True, exist_ok=True)

    log.info("Watching %s for new result files...", outputs_dir)

    async for changes in awatch(str(outputs_dir)):
        for change_type, path_str in changes:
            path = Path(path_str)
            if change_type in (Change.added, Change.modified) and path.name.startswith("results-") and path.suffix == ".json":
                # Small delay to let file finish writing
                await asyncio.sleep(0.5)
                exec_id = await ingest_result_file(path)
                if exec_id is not None and on_new_execution:
                    await on_new_execution(exec_id)
