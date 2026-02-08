"""General Manager — automated launch → monitor → merge → build → test pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, Awaitable

import yaml

from . import config, db
from .team_launcher import TeamLauncher
from .worktree import (
    _run_git,
    get_files_changed,
    merge_worktree,
    delete_worktree,
    BRANCH_PREFIX,
)

log = logging.getLogger("dashboard.gm")

PHASES = ["launching", "waiting", "analyzing", "merging", "building", "testing", "completed"]
MAX_BUILD_FIX_ATTEMPTS = 3
MAX_TEST_FIX_ATTEMPTS = 3
POLL_INTERVAL = 5  # seconds


ProgressCallback = Callable[[dict], Awaitable[None]]


def get_available_gm_projects() -> list[dict]:
    """Read GM project templates from orchestra.yml."""
    try:
        with open(config.CONFIG_FILE) as f:
            cfg = yaml.safe_load(f)
    except FileNotFoundError:
        return []

    gm_cfg = cfg.get("gm_projects", {})
    result = []
    for name, defn in gm_cfg.items():
        agents = defn.get("agents", [])
        result.append({
            "name": name,
            "description": defn.get("description", ""),
            "repo_path": defn.get("repo_path", ""),
            "build_command": defn.get("build_command", ""),
            "test_command": defn.get("test_command", ""),
            "agent_count": len(agents),
            "agents": agents,
        })
    return result


class GeneralManager:
    """Automated multi-agent lifecycle: launch → wait → analyze → merge → build → test → done."""

    def __init__(self, team_launcher: TeamLauncher):
        self._team_launcher = team_launcher
        self._active_projects: dict[str, asyncio.Task] = {}
        self._progress_callback: ProgressCallback | None = None
        self._log_callback: Callable | None = None

    def set_progress_callback(self, cb: ProgressCallback) -> None:
        self._progress_callback = cb

    def set_log_callback(self, cb: Callable) -> None:
        self._log_callback = cb

    async def _emit(self, project_id: str, event: str, **kwargs) -> None:
        data = {"type": "gm_progress", "project_id": project_id, "event": event, **kwargs}
        if self._progress_callback:
            await self._progress_callback(data)

    async def _log(self, level: str, message: str) -> None:
        if self._log_callback:
            await self._log_callback(level, message)

    # ── Launch ─────────────────────────────────────────────────────────

    async def launch_project(
        self,
        project_name: str,
        agents: list[dict],
        repo_path: str,
        build_command: str | None = None,
        test_command: str | None = None,
    ) -> dict:
        """Start a GM project: launch all agents, then orchestrate the pipeline."""
        project_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        ts = datetime.now(timezone.utc).isoformat()

        await db.insert_gm_project(
            project_id=project_id,
            project_name=project_name,
            repo_path=repo_path,
            build_command=build_command,
            test_command=test_command,
            agent_count=len(agents),
            started_at=ts,
        )

        await self._set_phase(project_id, "launching")
        await self._emit(project_id, "project_started", project_name=project_name)
        await self._log("info", f"GM project '{project_name}' ({project_id}) started with {len(agents)} agents")

        # Launch each agent via TeamLauncher
        session_ids = []
        for agent_def in agents:
            team_name = agent_def.get("team", "unnamed")
            task = agent_def.get("task", "")

            result = await self._team_launcher.launch(team_name, task, repo_path)
            if "error" in result:
                await self._log("error", f"Failed to launch agent '{team_name}': {result['error']}")
                await db.insert_gm_agent_session(project_id, f"failed-{team_name}", team_name, task)
                await db.update_gm_agent_session_status(project_id, f"failed-{team_name}", "failed")
                continue

            sid = result["session_id"]
            session_ids.append(sid)

            await db.insert_gm_agent_session(project_id, sid, team_name, task)
            await db.update_gm_agent_session_status(project_id, sid, "running")
            await self._emit(project_id, "agent_launched", session_id=sid, team_name=team_name)

        if not session_ids:
            await self._set_phase(project_id, "failed", error_message="No agents launched successfully")
            return {"error": "No agents could be launched", "project_id": project_id}

        # Start orchestration in background
        task = asyncio.create_task(self._orchestrate(project_id, session_ids, repo_path, build_command, test_command))
        self._active_projects[project_id] = task

        return {
            "ok": True,
            "project_id": project_id,
            "agent_count": len(session_ids),
            "session_ids": session_ids,
        }

    # ── Orchestration Pipeline ─────────────────────────────────────────

    async def _orchestrate(
        self,
        project_id: str,
        session_ids: list[str],
        repo_path: str,
        build_command: str | None,
        test_command: str | None,
    ) -> None:
        """Background task: full lifecycle after agents are launched."""
        try:
            # Phase: Waiting
            await self._wait_for_completion(project_id, session_ids)

            # Phase: Analyzing
            merge_order = await self._analyze_merge_order(project_id, session_ids, repo_path)
            if not merge_order:
                await self._set_phase(project_id, "failed", error_message="No successful agents to merge")
                await self._emit(project_id, "project_failed", reason="No successful agents")
                return

            # Phase: Merging
            await self._set_phase(project_id, "merging")
            await self._emit(project_id, "phase_change", phase="merging")

            merged_count = 0
            for idx, sid in enumerate(merge_order):
                result = await self._merge_branch(project_id, sid, repo_path, idx)
                if result.get("ok"):
                    merged_count += 1
                    await db.update_gm_project_merge_progress(project_id, merged_count=merged_count)

                    # Build check after each merge
                    if build_command:
                        build_ok = await self._run_build(project_id, repo_path, build_command)
                        if not build_ok:
                            fix_ok = await self._fix_build_with_claude(project_id, repo_path, build_command)
                            if not fix_ok:
                                await self._log("warn", f"Build broken after merging {sid}, continuing...")

            if merged_count == 0:
                await self._set_phase(project_id, "failed", error_message="No branches merged successfully")
                await self._emit(project_id, "project_failed", reason="All merges failed")
                return

            # Phase: Building (final)
            if build_command:
                await self._set_phase(project_id, "building")
                await self._emit(project_id, "phase_change", phase="building")
                build_ok = await self._run_build(project_id, repo_path, build_command)
                if not build_ok:
                    build_ok = await self._fix_build_with_claude(project_id, repo_path, build_command)
                    if not build_ok:
                        await self._set_phase(project_id, "failed", error_message="Build failed after all fix attempts")
                        await self._emit(project_id, "project_failed", reason="Build failed")
                        return

            # Phase: Testing
            if test_command:
                await self._set_phase(project_id, "testing")
                await self._emit(project_id, "phase_change", phase="testing")
                test_ok = await self._run_tests(project_id, repo_path, test_command)
                if not test_ok:
                    test_ok = await self._fix_tests_with_claude(project_id, repo_path, test_command)
                    if not test_ok:
                        await self._set_phase(project_id, "failed", error_message="Tests failed after all fix attempts")
                        await self._emit(project_id, "project_failed", reason="Tests failed")
                        return

            # Phase: Completed
            await self._finalize(project_id)

        except asyncio.CancelledError:
            await self._set_phase(project_id, "failed", error_message="Cancelled")
            await self._emit(project_id, "project_failed", reason="Cancelled")
        except Exception as e:
            log.exception("GM orchestration error for %s", project_id)
            await self._set_phase(project_id, "failed", error_message=str(e))
            await self._emit(project_id, "project_failed", reason=str(e))
        finally:
            self._active_projects.pop(project_id, None)

    # ── Wait for Agents ────────────────────────────────────────────────

    async def _wait_for_completion(self, project_id: str, session_ids: list[str]) -> None:
        """Poll DB every POLL_INTERVAL seconds until all agents finish."""
        await self._set_phase(project_id, "waiting")
        await self._emit(project_id, "phase_change", phase="waiting")

        completed = set()
        while len(completed) < len(session_ids):
            await asyncio.sleep(POLL_INTERVAL)

            for sid in session_ids:
                if sid in completed:
                    continue
                session = await db.get_team_session_by_session_id(sid)
                if not session:
                    continue
                status = session.get("status", "running")
                if status in ("completed", "failed", "cancelled"):
                    completed.add(sid)
                    agent_status = "completed" if status == "completed" else "failed"
                    await db.update_gm_agent_session_status(project_id, sid, agent_status)
                    await self._emit(
                        project_id, "agent_completed",
                        session_id=sid, status=agent_status,
                    )
                    await self._log("info", f"Agent {sid} finished: {status}")

            c = len(completed)
            f = 0
            for sid in completed:
                s = await db.get_team_session_by_session_id(sid)
                if s and s.get("status") == "failed":
                    f += 1
            await db.update_gm_project_merge_progress(
                project_id, completed_count=c, failed_count=f,
            )

    # ── Analyze Merge Order ────────────────────────────────────────────

    async def _analyze_merge_order(
        self, project_id: str, session_ids: list[str], repo_path: str,
    ) -> list[str]:
        """Score branches by file overlap, sort ascending (least-conflicting first)."""
        await self._set_phase(project_id, "analyzing")
        await self._emit(project_id, "phase_change", phase="analyzing")

        # Filter to only completed agents
        successful = []
        for sid in session_ids:
            session = await db.get_team_session_by_session_id(sid)
            if session and session.get("status") == "completed":
                successful.append(sid)

        if not successful:
            return []

        # Gather files changed per branch
        files_by_branch: dict[str, set[str]] = {}
        for sid in successful:
            files = await get_files_changed(repo_path, sid)
            files_by_branch[sid] = set(files)
            await db.update_gm_agent_session_files(
                project_id, sid, json.dumps(files),
            )

        # Score: count of files that overlap with ANY other branch
        overlap_scores: dict[str, int] = {}
        all_sids = list(files_by_branch.keys())
        for sid in all_sids:
            score = 0
            for other_sid in all_sids:
                if other_sid == sid:
                    continue
                score += len(files_by_branch[sid] & files_by_branch[other_sid])
            overlap_scores[sid] = score

        # Sort ascending (least overlap first)
        merge_order = sorted(all_sids, key=lambda s: overlap_scores[s])

        await db.update_gm_project_merge_progress(
            project_id, merge_order=json.dumps(merge_order),
        )
        await self._emit(
            project_id, "merge_order_determined",
            merge_order=merge_order,
            scores={s: overlap_scores[s] for s in merge_order},
        )
        await self._log("info", f"Merge order: {merge_order} (scores: {overlap_scores})")

        return merge_order

    # ── Merge ──────────────────────────────────────────────────────────

    async def _merge_branch(
        self, project_id: str, session_id: str, repo_path: str, index: int,
    ) -> dict:
        """Merge a single branch. Handle conflicts with Claude if needed."""
        await db.update_gm_project_merge_progress(project_id, current_merge=session_id)
        await self._emit(project_id, "merge_started", session_id=session_id, index=index)

        branch = f"{BRANCH_PREFIX}/{session_id}"
        ts = datetime.now(timezone.utc).isoformat()

        # Try merge
        result = await merge_worktree(repo_path, session_id)
        if "error" not in result:
            await db.update_gm_agent_session_merge(project_id, session_id, index, "merged", ts)
            await self._emit(project_id, "merge_completed", session_id=session_id)
            await self._log("info", f"Merged {session_id} successfully")
            return {"ok": True}

        # Merge conflict — try resolving with Claude
        await self._emit(project_id, "merge_conflict", session_id=session_id, error=result.get("error", ""))
        await self._log("warn", f"Merge conflict for {session_id}: {result.get('error', '')}")

        resolve_result = await self._resolve_conflicts_with_claude(project_id, session_id, repo_path)
        if resolve_result.get("ok"):
            await db.update_gm_agent_session_merge(project_id, session_id, index, "merged_resolved", ts)
            await self._emit(project_id, "conflict_resolved", session_id=session_id)
            return {"ok": True}

        # Failed to resolve — abort and skip
        await _run_git("merge", "--abort", cwd=repo_path)
        # Clean up the branch/worktree
        await delete_worktree(repo_path, session_id)
        await db.update_gm_agent_session_merge(project_id, session_id, index, "skipped", ts)
        await self._emit(project_id, "merge_completed", session_id=session_id, skipped=True)
        await self._log("warn", f"Skipped {session_id} (could not resolve conflicts)")
        return {"error": "Conflict resolution failed", "skipped": True}

    async def _resolve_conflicts_with_claude(
        self, project_id: str, session_id: str, repo_path: str,
    ) -> dict:
        """Spawn claude -p to resolve merge conflicts."""
        # Get list of conflicted files
        rc, out, _ = await _run_git("diff", "--name-only", "--diff-filter=U", cwd=repo_path)
        if rc != 0 or not out.strip():
            return {"error": "Could not determine conflicted files"}

        conflict_files = out.strip()
        prompt = (
            f"There are merge conflicts in the following files:\n{conflict_files}\n\n"
            "Please resolve all merge conflicts in these files. Keep the best version of each "
            "conflicting section, combining changes from both sides where appropriate. "
            "Remove all conflict markers (<<<<<<<, =======, >>>>>>>). "
            "After resolving, stage the files with git add."
        )

        ok = await self._run_claude(repo_path, prompt, f"conflict-resolution-{session_id}")
        if not ok:
            return {"error": "Claude failed to resolve conflicts"}

        # Check if conflicts are resolved
        rc, remaining, _ = await _run_git("diff", "--name-only", "--diff-filter=U", cwd=repo_path)
        if rc == 0 and remaining.strip():
            return {"error": "Conflicts still remain after Claude resolution"}

        # Commit the resolution
        rc, _, err = await _run_git("commit", "--no-edit", cwd=repo_path)
        if rc != 0:
            # Try adding and committing
            await _run_git("add", "-A", cwd=repo_path)
            rc, _, err = await _run_git(
                "commit", "-m", f"Resolve merge conflicts for {session_id}", cwd=repo_path,
            )
            if rc != 0:
                return {"error": f"Failed to commit resolution: {err}"}

        return {"ok": True}

    # ── Build ──────────────────────────────────────────────────────────

    async def _run_build(self, project_id: str, repo_path: str, build_command: str) -> bool:
        """Run build command. Returns True if successful."""
        await self._emit(project_id, "build_started")

        rc, stdout, stderr = await self._run_shell(build_command, repo_path)
        ok = rc == 0

        await self._emit(project_id, "build_result", success=ok, output=stderr[-4096:] if not ok else "")
        return ok

    async def _fix_build_with_claude(self, project_id: str, repo_path: str, build_command: str) -> bool:
        """Try to fix build errors with Claude, up to MAX_BUILD_FIX_ATTEMPTS."""
        for attempt in range(1, MAX_BUILD_FIX_ATTEMPTS + 1):
            await db.update_gm_project_merge_progress(project_id, build_attempts=attempt)
            await self._emit(project_id, "build_fix_attempt", attempt=attempt)
            await self._log("info", f"Build fix attempt {attempt}/{MAX_BUILD_FIX_ATTEMPTS}")

            # Get the build error
            rc, stdout, stderr = await self._run_shell(build_command, repo_path)
            error_output = (stderr or stdout)[-4096:]

            prompt = (
                f"The build command `{build_command}` failed with the following errors:\n\n"
                f"```\n{error_output}\n```\n\n"
                "Fix the compilation errors. Only fix build/compilation issues — do not change "
                "test expectations or add new features. Make minimal changes to get the build passing."
            )

            ok = await self._run_claude(repo_path, prompt, f"build-fix-{attempt}")
            if not ok:
                continue

            # Commit fixes
            await _run_git("add", "-A", cwd=repo_path)
            await _run_git(
                "commit", "-m", f"fix: build fix attempt {attempt}", cwd=repo_path,
            )

            # Re-run build
            rc, _, _ = await self._run_shell(build_command, repo_path)
            if rc == 0:
                await self._emit(project_id, "build_result", success=True)
                return True

        return False

    # ── Tests ──────────────────────────────────────────────────────────

    async def _run_tests(self, project_id: str, repo_path: str, test_command: str) -> bool:
        """Run test command. Returns True if successful."""
        await self._emit(project_id, "test_started")

        rc, stdout, stderr = await self._run_shell(test_command, repo_path)
        ok = rc == 0

        await self._emit(project_id, "test_result", success=ok, output=stderr[-4096:] if not ok else "")
        return ok

    async def _fix_tests_with_claude(self, project_id: str, repo_path: str, test_command: str) -> bool:
        """Try to fix test failures with Claude, up to MAX_TEST_FIX_ATTEMPTS."""
        for attempt in range(1, MAX_TEST_FIX_ATTEMPTS + 1):
            await db.update_gm_project_merge_progress(project_id, test_attempts=attempt)
            await self._emit(project_id, "test_fix_attempt", attempt=attempt)
            await self._log("info", f"Test fix attempt {attempt}/{MAX_TEST_FIX_ATTEMPTS}")

            # Get the test error
            rc, stdout, stderr = await self._run_shell(test_command, repo_path)
            error_output = (stderr or stdout)[-4096:]

            prompt = (
                f"The test command `{test_command}` failed with the following output:\n\n"
                f"```\n{error_output}\n```\n\n"
                "Fix the implementation so the tests pass. Do NOT modify test expectations — "
                "fix the actual implementation code. Make minimal changes."
            )

            ok = await self._run_claude(repo_path, prompt, f"test-fix-{attempt}")
            if not ok:
                continue

            # Commit fixes
            await _run_git("add", "-A", cwd=repo_path)
            await _run_git(
                "commit", "-m", f"fix: test fix attempt {attempt}", cwd=repo_path,
            )

            # Re-run tests
            rc, _, _ = await self._run_shell(test_command, repo_path)
            if rc == 0:
                await self._emit(project_id, "test_result", success=True)
                return True

        return False

    # ── Finalize ───────────────────────────────────────────────────────

    async def _finalize(self, project_id: str) -> None:
        """Mark project as completed."""
        ts = datetime.now(timezone.utc).isoformat()
        await db.update_gm_project_phase(project_id, "completed", completed_at=ts)
        await self._emit(project_id, "project_completed")
        await self._log("info", f"GM project {project_id} completed successfully")

    # ── Cancel ─────────────────────────────────────────────────────────

    async def cancel_project(self, project_id: str) -> dict:
        """Cancel a running GM project."""
        task = self._active_projects.get(project_id)
        if not task:
            return {"error": "Project not active"}

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Cancel any running agent sessions
        agent_sessions = await db.get_gm_agent_sessions(project_id)
        for agent in agent_sessions:
            if agent["status"] == "running":
                await self._team_launcher.cancel(agent["session_id"])

        ts = datetime.now(timezone.utc).isoformat()
        await db.update_gm_project_phase(project_id, "failed", error_message="Cancelled by user", completed_at=ts)
        self._active_projects.pop(project_id, None)
        return {"ok": True, "project_id": project_id}

    async def cancel_all(self) -> None:
        """Cancel all active GM projects (for shutdown)."""
        for pid in list(self._active_projects.keys()):
            await self.cancel_project(pid)

    # ── Push ───────────────────────────────────────────────────────────

    async def push_project(self, project_id: str) -> dict:
        """Push the merged result to remote."""
        project = await db.get_gm_project(project_id)
        if not project:
            return {"error": "Project not found"}
        repo_path = project["repo_path"]

        rc, out, err = await _run_git("push", cwd=repo_path)
        if rc != 0:
            return {"error": f"Push failed: {err}"}
        return {"ok": True, "output": out}

    # ── Retry ──────────────────────────────────────────────────────────

    async def retry_project(self, project_id: str) -> dict:
        """Retry failed merges/builds for a project."""
        project = await db.get_gm_project(project_id)
        if not project:
            return {"error": "Project not found"}
        if project["phase"] != "failed":
            return {"error": "Can only retry failed projects"}

        repo_path = project["repo_path"]
        build_command = project.get("build_command")
        test_command = project.get("test_command")

        # Get skipped sessions
        sessions = await db.get_gm_agent_sessions(project_id)
        skipped = [s for s in sessions if s.get("merge_result") == "skipped"]

        if skipped:
            # Re-attempt merges for skipped branches
            await self._set_phase(project_id, "merging")
            merged_count = project.get("merged_count", 0)
            for s in skipped:
                result = await self._merge_branch(
                    project_id, s["session_id"], repo_path, s.get("merge_order_index", 0),
                )
                if result.get("ok"):
                    merged_count += 1
                    await db.update_gm_project_merge_progress(project_id, merged_count=merged_count)

        # Re-attempt build/test
        if build_command:
            await self._set_phase(project_id, "building")
            build_ok = await self._run_build(project_id, repo_path, build_command)
            if not build_ok:
                build_ok = await self._fix_build_with_claude(project_id, repo_path, build_command)
                if not build_ok:
                    await self._set_phase(project_id, "failed", error_message="Build still failing on retry")
                    return {"error": "Build failed on retry"}

        if test_command:
            await self._set_phase(project_id, "testing")
            test_ok = await self._run_tests(project_id, repo_path, test_command)
            if not test_ok:
                test_ok = await self._fix_tests_with_claude(project_id, repo_path, test_command)
                if not test_ok:
                    await self._set_phase(project_id, "failed", error_message="Tests still failing on retry")
                    return {"error": "Tests failed on retry"}

        await self._finalize(project_id)
        return {"ok": True, "project_id": project_id}

    # ── Helpers ─────────────────────────────────────────────────────────

    async def _set_phase(
        self, project_id: str, phase: str, error_message: str | None = None,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat() if phase in ("completed", "failed") else None
        await db.update_gm_project_phase(project_id, phase, error_message, ts)

    async def _run_claude(self, repo_path: str, prompt: str, label: str) -> bool:
        """Spawn a claude -p subprocess for an intelligent task. Returns True if exit code 0."""
        log.info("Spawning Claude for %s", label)
        try:
            proc = await asyncio.create_subprocess_exec(
                "claude",
                "--allowedTools", "Edit,Write,Bash,Read,Glob,Grep",
                "-p", prompt,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)
            ok = proc.returncode == 0
            if not ok:
                log.warning("Claude %s failed (exit %d): %s", label, proc.returncode, stderr.decode()[:500])
            return ok
        except asyncio.TimeoutError:
            log.error("Claude %s timed out", label)
            try:
                proc.kill()
            except Exception:
                pass
            return False
        except OSError as e:
            log.error("Failed to spawn Claude for %s: %s", label, e)
            return False

    async def _run_shell(self, command: str, cwd: str) -> tuple[int, str, str]:
        """Run a shell command, return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        return (
            proc.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
