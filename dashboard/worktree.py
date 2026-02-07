"""Git worktree management for isolated team development branches."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger("dashboard.worktree")

WORKTREE_DIR = ".worktrees"
BRANCH_PREFIX = "team"


async def _run_git(*args: str, cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )


async def create_worktree(repo_path: str, session_id: str) -> dict:
    """Create a new branch + worktree for a team session.

    Returns dict with branch_name, worktree_path, or error.
    """
    branch = f"{BRANCH_PREFIX}/{session_id}"
    wt_dir = str(Path(repo_path) / WORKTREE_DIR / session_id)

    # Get current branch to use as base
    rc, base_branch, err = await _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_path)
    if rc != 0:
        return {"error": f"Failed to get current branch: {err}"}

    # Create the branch from current HEAD
    rc, out, err = await _run_git("branch", branch, "HEAD", cwd=repo_path)
    if rc != 0:
        return {"error": f"Failed to create branch: {err}"}

    # Create the worktree
    rc, out, err = await _run_git("worktree", "add", wt_dir, branch, cwd=repo_path)
    if rc != 0:
        # Clean up branch on failure
        await _run_git("branch", "-D", branch, cwd=repo_path)
        return {"error": f"Failed to create worktree: {err}"}

    log.info("Created worktree %s on branch %s", wt_dir, branch)
    return {
        "branch_name": branch,
        "worktree_path": wt_dir,
        "base_branch": base_branch,
    }


async def list_worktrees(repo_path: str) -> list[dict]:
    """List active team worktrees."""
    rc, out, err = await _run_git("worktree", "list", "--porcelain", cwd=repo_path)
    if rc != 0:
        log.error("Failed to list worktrees: %s", err)
        return []

    worktrees = []
    current: dict = {}
    for line in out.split("\n"):
        if not line.strip():
            if current and current.get("branch", "").startswith(f"refs/heads/{BRANCH_PREFIX}/"):
                worktrees.append(current)
            current = {}
        elif line.startswith("worktree "):
            current["worktree"] = line[len("worktree "):]
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):]

    # Handle last entry
    if current and current.get("branch", "").startswith(f"refs/heads/{BRANCH_PREFIX}/"):
        worktrees.append(current)

    return worktrees


async def get_worktree_diff(repo_path: str, session_id: str) -> dict:
    """Get unified diff of worktree changes vs base branch."""
    branch = f"{BRANCH_PREFIX}/{session_id}"

    # Find merge base
    rc, base, err = await _run_git("merge-base", "HEAD", branch, cwd=repo_path)
    if rc != 0:
        return {"error": f"Failed to find merge base: {err}"}

    # Get unified diff
    rc, diff, err = await _run_git("diff", base, branch, cwd=repo_path)
    if rc != 0:
        return {"error": f"Failed to get diff: {err}"}

    return {"diff": diff, "base_commit": base}


async def get_worktree_stat(repo_path: str, session_id: str) -> dict:
    """Get --stat summary of worktree changes vs base branch."""
    branch = f"{BRANCH_PREFIX}/{session_id}"

    rc, base, err = await _run_git("merge-base", "HEAD", branch, cwd=repo_path)
    if rc != 0:
        return {"error": f"Failed to find merge base: {err}"}

    rc, stat, err = await _run_git("diff", "--stat", base, branch, cwd=repo_path)
    if rc != 0:
        return {"error": f"Failed to get stat: {err}"}

    return {"stat": stat, "base_commit": base}


async def merge_worktree(repo_path: str, session_id: str) -> dict:
    """Merge the team branch into current branch, remove worktree, delete branch."""
    branch = f"{BRANCH_PREFIX}/{session_id}"
    wt_dir = str(Path(repo_path) / WORKTREE_DIR / session_id)

    # Remove worktree first
    rc, out, err = await _run_git("worktree", "remove", wt_dir, "--force", cwd=repo_path)
    if rc != 0:
        log.warning("Worktree remove failed (may already be gone): %s", err)

    # Merge with --no-ff to preserve branch history
    rc, out, err = await _run_git("merge", "--no-ff", branch, "-m", f"Merge team session {session_id}", cwd=repo_path)
    if rc != 0:
        return {"error": f"Merge failed: {err}"}

    # Delete the branch
    rc2, out2, err2 = await _run_git("branch", "-d", branch, cwd=repo_path)
    if rc2 != 0:
        log.warning("Branch delete failed: %s", err2)

    log.info("Merged and cleaned up session %s", session_id)
    return {"ok": True, "merge_output": out}


async def delete_worktree(repo_path: str, session_id: str) -> dict:
    """Force-remove worktree and delete branch without merging."""
    branch = f"{BRANCH_PREFIX}/{session_id}"
    wt_dir = str(Path(repo_path) / WORKTREE_DIR / session_id)

    # Force-remove worktree
    rc, out, err = await _run_git("worktree", "remove", wt_dir, "--force", cwd=repo_path)
    if rc != 0:
        log.warning("Worktree remove failed (may already be gone): %s", err)

    # Force-delete branch
    rc, out, err = await _run_git("branch", "-D", branch, cwd=repo_path)
    if rc != 0:
        log.warning("Branch delete failed: %s", err)

    log.info("Discarded worktree and branch for session %s", session_id)
    return {"ok": True}
