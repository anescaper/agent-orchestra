# /launch — Launch a Team Session

Launch a team to work on a task using an isolated git worktree.

## Arguments
$ARGUMENTS

## Steps

1. **Parse arguments**: Extract team name and task description from $ARGUMENTS (format: `<team-name> "<task description>"`)

2. **Validate team**: Check that the team name exists in `config/orchestra.yml`. Valid teams: feature-dev, code-review, debug, research. If invalid, list available teams and stop.

3. **Check prerequisites**:
   - Verify the repo has no uncommitted changes on the current branch (`git status --porcelain`)
   - If there are changes, warn the user and ask whether to proceed

4. **Launch via dashboard API** (if dashboard is running):
   ```bash
   curl -s -X POST http://localhost:8080/api/teams/launch \
     -H 'Content-Type: application/json' \
     -d '{"team_name": "<team>", "task_description": "<task>", "repo_path": "."}'
   ```

5. **Or launch via script** (if dashboard is not running):
   ```bash
   ./scripts/launch-team.sh <team-name> "<task description>"
   ```

6. **Report**: Show the session ID and how to check progress (`/status`) or review results (`/review`)
