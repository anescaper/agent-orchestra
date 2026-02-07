# /status — Check System Status

Show the current state of teams, worktrees, dashboard, and recent outputs.

## Steps

1. **Team sessions**: List active and recent team sessions
   ```bash
   curl -s http://localhost:8080/api/teams 2>/dev/null || echo "Dashboard not running"
   ```

2. **Git worktrees**: List all active worktrees
   ```bash
   git worktree list
   ```

3. **Dashboard health**: Check if the dashboard is reachable
   ```bash
   curl -s http://localhost:8080/api/status 2>/dev/null
   ```

4. **Recent outputs**: List the 5 most recent output files
   ```bash
   ls -lt outputs/ | head -6
   ```

5. **Summary**: Present a concise status overview:
   - Number of active team sessions (running/completed/failed)
   - Number of active worktrees
   - Dashboard: running/stopped
   - Latest output file and its timestamp
