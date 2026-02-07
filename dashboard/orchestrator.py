"""Subprocess control for the Rust agent-orchestra binary."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import datetime, timezone

from . import config

log = logging.getLogger("dashboard.orchestrator")


class OrchestratorControl:
    """Manage the agent-orchestra Rust binary as a subprocess."""

    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None
        self._mode: str | None = None
        self._client_mode: str | None = None
        self._started_at: str | None = None
        self._log_callback = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self.running else None

    def status(self) -> dict:
        return {
            "running": self.running,
            "pid": self.pid,
            "mode": self._mode if self.running else None,
            "client_mode": self._client_mode if self.running else None,
            "started_at": self._started_at if self.running else None,
        }

    def set_log_callback(self, callback):
        """Set async callback for log lines: callback(level, message)."""
        self._log_callback = callback

    async def _emit_log(self, level: str, message: str):
        if self._log_callback:
            await self._log_callback(level, message)

    async def start(self, mode: str = "auto", client_mode: str = "hybrid") -> dict:
        if self.running:
            return {"error": "Orchestrator is already running", **self.status()}

        binary = config.ORCHESTRATOR_BIN
        if not os.path.isfile(binary):
            return {"error": f"Binary not found: {binary}"}

        env = os.environ.copy()
        env["ORCHESTRATOR_MODE"] = mode
        env["CLIENT_MODE"] = client_mode

        self._mode = mode
        self._client_mode = client_mode
        self._started_at = datetime.now(timezone.utc).isoformat()

        try:
            self._process = await asyncio.create_subprocess_exec(
                binary,
                cwd=config.ORCHESTRATOR_CWD,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as e:
            self._process = None
            return {"error": f"Failed to start: {e}"}

        await self._emit_log("info", f"Orchestrator started (pid={self._process.pid}, mode={mode}, client={client_mode})")

        # Stream output in background
        asyncio.create_task(self._stream_output())

        return {"ok": True, **self.status()}

    async def stop(self, timeout: float = 10.0) -> dict:
        if not self.running:
            return {"error": "Orchestrator is not running"}

        pid = self._process.pid
        await self._emit_log("info", f"Stopping orchestrator (pid={pid})...")

        try:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                await self._emit_log("warn", f"SIGTERM timeout, sending SIGKILL to pid={pid}")
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            pass

        code = self._process.returncode
        await self._emit_log("info", f"Orchestrator stopped (exit code={code})")
        self._process = None
        return {"ok": True, "exit_code": code}

    async def _stream_output(self):
        """Read stdout/stderr and forward to log callback."""
        if not self._process:
            return

        async def _read_stream(stream, level):
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    await self._emit_log(level, text)

        await asyncio.gather(
            _read_stream(self._process.stdout, "info"),
            _read_stream(self._process.stderr, "error"),
        )
