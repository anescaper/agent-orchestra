# Team Launching

Team session lifecycle from template selection through execution and output.

## Team Templates (config/orchestra.yml)

| Template | Teammates | Purpose |
|----------|-----------|---------|
| feature-dev | architect (300s) + implementer (600s) + reviewer (300s) | Full feature lifecycle |
| code-review | security-reviewer (300s) + style-reviewer (300s) | Security + style review |
| debug | reproducer (300s) + analyzer (300s) + fixer (300s) | Systematic debugging |
| research | searcher (300s) + synthesizer (300s) | Research and summarize |

## Core Module

`dashboard/team_launcher.py` — `TeamLauncher` singleton class.

## Launch Flow

1. `get_available_teams()` — parse templates from orchestra.yml
2. `launch(team_name, task_description, repo_path)`:
   - Validate team template exists
   - Create git worktree via `worktree.create_worktree()`
   - Insert `team_sessions` row in DB
   - Spawn `claude -p` subprocess with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
   - Stream output via progress callback (WebSocket broadcast)
3. `_stream_and_finish()` — collect output, set status, write `outputs/teams-*.json`

## Cancel / Cleanup

```python
cancel(session_id, timeout=10)  # SIGTERM then SIGKILL
cancel_all()                     # Shutdown cleanup for all active sessions
```

## DB Schema (team_sessions)

Columns: session_id, team_name, task_description, status, started_at, completed_at, filename, teammate_count, success_count, fail_count, repo_path, branch_name, worktree_path

## Output Location

- JSON: `outputs/teams-{session_id}.json`
- Ingested by `watcher.py` into DB automatically

## Server Endpoints

- `POST /api/teams/launch` — body: `{team_name, task_description, repo_path}`
- `POST /api/teams/{id}/cancel` — cancel running session
- `GET /api/teams/templates` — list available templates
- `GET /api/teams` — list all sessions
- `GET /api/teams/{id}` — session detail with teammate tasks
