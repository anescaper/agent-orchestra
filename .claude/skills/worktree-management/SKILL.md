# Worktree Management

Git worktree lifecycle for isolated team development branches.

## Core Module

`dashboard/worktree.py` — all worktree operations.

## Constants

- `WORKTREE_DIR = ".worktrees"` — worktree storage directory
- `BRANCH_PREFIX = "team"` — branches named `team/{session_id}`

## Lifecycle

### Create
```python
create_worktree(repo_path, session_id)
# Creates branch team/{session_id} from current HEAD
# Checkout at .worktrees/{session_id}
```

### Inspect
```python
list_worktrees(repo_path)         # Parse git worktree list --porcelain
get_worktree_diff(repo_path, id)  # Unified diff (committed + uncommitted)
get_worktree_stat(repo_path, id)  # --stat summary
```

### Complete
```python
merge_worktree(repo_path, id)     # Commit, merge --no-ff, delete branch
delete_worktree(repo_path, id)    # Force-remove without merging
```

## Git Commands Used

```bash
git worktree add .worktrees/{id} -b team/{id}
git worktree list --porcelain
git -C .worktrees/{id} diff HEAD
git -C .worktrees/{id} diff --stat HEAD
git -C .worktrees/{id} add -A && git -C .worktrees/{id} commit
git merge --no-ff team/{id}
git worktree remove --force .worktrees/{id}
git branch -D team/{id}
```

## Integration

- `team_launcher.py` calls `create_worktree()` on launch, stores path in DB
- `server.py` exposes `/api/teams/{id}/diff`, `/api/teams/{id}/merge`, `/api/teams/{id}/discard`
- Dashboard UI shows diff modal and merge/discard buttons per session
