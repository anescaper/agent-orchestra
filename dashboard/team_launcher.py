"""Team session lifecycle — launch, cancel, and track claude agent-teams sessions."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Awaitable

import yaml

from . import config, db
from .worktree import create_worktree, _run_git

log = logging.getLogger("dashboard.team_launcher")

CRITICAL_ERROR_PATTERNS = [
    "No space left on device",
    "ENOSPC",
    "disk quota exceeded",
    "cannot allocate memory",
    "OSError: [Errno 28]",
]
CRITICAL_ERROR_THRESHOLD = 2  # Kill after this many occurrences


def get_available_teams() -> list[dict]:
    """Read team definitions from orchestra.yml for the UI dropdown."""
    try:
        with open(config.CONFIG_FILE) as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        log.warning("Config file not found: %s", config.CONFIG_FILE)
        return []

    teams_cfg = cfg.get("teams", {})
    if not teams_cfg.get("enabled"):
        return []

    definitions = teams_cfg.get("definitions", {})
    result = []
    for name, defn in definitions.items():
        teammates = defn.get("teammates", [])
        result.append({
            "name": name,
            "description": defn.get("description", ""),
            "teammate_count": len(teammates),
            "teammates": [t.get("name", "") for t in teammates],
        })
    return result


ProgressCallback = Callable[[dict], Awaitable[None]]


class TeamLauncher:
    """Manage running team sessions as subprocesses (singleton)."""

    def __init__(self):
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._progress_callback: ProgressCallback | None = None
        self._log_callback: Callable | None = None

    def set_progress_callback(self, cb: ProgressCallback) -> None:
        self._progress_callback = cb

    def set_log_callback(self, cb: Callable) -> None:
        self._log_callback = cb

    async def _emit_progress(self, data: dict) -> None:
        if self._progress_callback:
            await self._progress_callback(data)

    async def _emit_log(self, level: str, message: str) -> None:
        if self._log_callback:
            await self._log_callback(level, message)

    @property
    def active_sessions(self) -> list[str]:
        return [sid for sid, proc in self._processes.items() if proc.returncode is None]

    async def launch(
        self,
        team_name: str,
        task_description: str,
        repo_path: str | None = None,
    ) -> dict:
        """Launch a new team session in an isolated worktree."""
        session_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        effective_repo = repo_path or str(config.BASE_DIR)

        # Create worktree
        wt_result = await create_worktree(effective_repo, session_id)
        if "error" in wt_result:
            return {"error": wt_result["error"]}

        branch_name = wt_result["branch_name"]
        worktree_path = wt_result["worktree_path"]

        # Insert DB record
        ts = datetime.now(timezone.utc).isoformat()
        db_id = await db.insert_team_session(
            session_id=session_id,
            team_name=team_name,
            task_description=task_description,
            status="running",
            started_at=ts,
            completed_at=None,
            filename=None,
            teammate_count=0,
            success_count=0,
            fail_count=0,
        )

        # Store worktree info
        await db.update_team_session_worktree(
            session_id, effective_repo, branch_name, worktree_path,
        )

        await self._emit_log("info", f"Launching team '{team_name}' session {session_id}")

        # Build the claude command
        prompt = f"Team: {team_name}\nTask: {task_description}"
        env = os.environ.copy()
        env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"

        cargo_toml = Path(effective_repo) / "Cargo.toml"
        if cargo_toml.exists():
            shared_target = str(Path(effective_repo) / ".shared-target")
            env["CARGO_TARGET_DIR"] = shared_target
            log.info("Set CARGO_TARGET_DIR=%s for session %s", shared_target, session_id)

        try:
            proc = await asyncio.create_subprocess_exec(
                "claude",
                "--allowedTools", "Edit,Write,Bash,Read,Glob,Grep",
                "-p", prompt,
                cwd=worktree_path,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            await db.update_team_session_status(session_id, "failed", datetime.now(timezone.utc).isoformat())
            return {"error": f"Failed to start claude: {e}"}

        self._processes[session_id] = proc

        # Stream output in background
        asyncio.create_task(self._stream_and_finish(session_id, proc, team_name, db_id))

        await self._emit_progress({
            "type": "team_progress",
            "session_id": session_id,
            "event": "started",
            "team_name": team_name,
            "db_id": db_id,
        })

        return {
            "ok": True,
            "session_id": session_id,
            "db_id": db_id,
            "branch_name": branch_name,
            "worktree_path": worktree_path,
        }

    async def _stream_and_finish(
        self,
        session_id: str,
        proc: asyncio.subprocess.Process,
        team_name: str,
        db_id: int,
    ) -> None:
        """Read stdout/stderr, broadcast progress, finalize on exit."""
        collected_stdout: list[str] = []
        error_counts: dict[str, int] = {}
        kill_triggered = False

        async def _read_stream(stream, stream_name: str):
            nonlocal kill_triggered
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    if stream_name == "stdout":
                        collected_stdout.append(text)

                    # Check stderr for critical resource errors
                    if stream_name == "stderr":
                        for pattern in CRITICAL_ERROR_PATTERNS:
                            if pattern in text:
                                error_counts[pattern] = error_counts.get(pattern, 0) + 1
                                if error_counts[pattern] >= CRITICAL_ERROR_THRESHOLD:
                                    kill_triggered = True
                                    log.error(
                                        "Session %s hit critical error %dx: %s",
                                        session_id, error_counts[pattern], pattern,
                                    )
                                    await self._emit_progress({
                                        "type": "team_progress",
                                        "session_id": session_id,
                                        "event": "resource_error",
                                        "data": f"Auto-killed: '{pattern}' occurred {error_counts[pattern]} times",
                                        "db_id": db_id,
                                    })
                                    proc.kill()
                                    return

                    await self._emit_progress({
                        "type": "team_progress",
                        "session_id": session_id,
                        "event": stream_name,
                        "data": text,
                        "db_id": db_id,
                    })

        await asyncio.gather(
            _read_stream(proc.stdout, "stdout"),
            _read_stream(proc.stderr, "stderr"),
        )

        await proc.wait()
        exit_code = proc.returncode
        completed_at = datetime.now(timezone.utc).isoformat()

        status = "completed" if exit_code == 0 and not kill_triggered else "failed"
        if kill_triggered:
            log.error("Session %s killed due to repeated resource errors", session_id)

        # Auto-commit worktree changes so the branch has actual commits
        session = await db.get_team_session_by_session_id(session_id)
        wt_path = session.get("worktree_path") if session else None
        if wt_path:
            rc, diff_out, _ = await _run_git("status", "--porcelain", cwd=wt_path)
            if rc == 0 and diff_out.strip():
                await _run_git("add", "-A", cwd=wt_path)
                commit_msg = f"feat: {team_name} session {session_id}"
                rc2, _, cerr = await _run_git("commit", "-m", commit_msg, cwd=wt_path)
                if rc2 == 0:
                    log.info("Auto-committed changes in worktree for session %s", session_id)
                else:
                    log.warning("Auto-commit failed for session %s: %s", session_id, cerr)

            # Clean worktree-local target/ to reclaim disk space
            wt_target = Path(wt_path) / "target"
            if wt_target.is_dir():
                try:
                    shutil.rmtree(wt_target)
                    log.info("Cleaned worktree target/ for session %s", session_id)
                except OSError as e:
                    log.warning("Failed to clean worktree target/ for session %s: %s", session_id, e)

        await db.update_team_session_status(session_id, status, completed_at)

        # Write result to outputs/
        output_filename = f"teams-{session_id}.json"
        output_path = config.OUTPUTS_DIR / output_filename
        try:
            config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
            result_data = {
                "session_id": session_id,
                "team_name": team_name,
                "status": status,
                "exit_code": exit_code,
                "output": "\n".join(collected_stdout),
                "completed_at": completed_at,
            }
            with open(output_path, "w") as f:
                json.dump(result_data, f, indent=2)
            await db.update_team_session_filename(session_id, output_filename)
        except OSError as e:
            log.error("Failed to write output file: %s", e)

        # Clean up process reference
        self._processes.pop(session_id, None)

        await self._emit_progress({
            "type": "team_progress",
            "session_id": session_id,
            "event": "completed",
            "status": status,
            "exit_code": exit_code,
            "db_id": db_id,
        })

        await self._emit_log(
            "info" if status == "completed" else "error",
            f"Team '{team_name}' session {session_id} {status} (exit={exit_code})",
        )

    async def cancel(self, session_id: str, timeout: float = 10.0) -> dict:
        """Cancel a running team session."""
        proc = self._processes.get(session_id)
        if not proc or proc.returncode is not None:
            return {"error": "Session not running"}

        try:
            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass

        completed_at = datetime.now(timezone.utc).isoformat()
        await db.update_team_session_status(session_id, "cancelled", completed_at)
        self._processes.pop(session_id, None)

        await self._emit_progress({
            "type": "team_progress",
            "session_id": session_id,
            "event": "cancelled",
        })

        return {"ok": True, "session_id": session_id}

    async def cancel_all(self) -> None:
        """Cancel all active sessions (for shutdown)."""
        for sid in list(self.active_sessions):
            await self.cancel(sid, timeout=5.0)
