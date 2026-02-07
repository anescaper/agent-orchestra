# /review — Review Team Results

Review a team session's diff, get code review feedback, then merge or discard.

## Arguments
$ARGUMENTS

## Steps

1. **Identify session**: Use $ARGUMENTS as session ID. If not provided, list recent sessions and ask which to review.

2. **Get diff summary**:
   ```bash
   curl -s http://localhost:8080/api/teams/<session_id>/diff 2>/dev/null
   ```
   Or directly:
   ```bash
   git -C .worktrees/<session_id> diff --stat HEAD
   ```

3. **Show full diff**: Display the unified diff for review. If the diff is large, show the stat summary first and offer to show specific files.

4. **Code review**: Invoke the code-reviewer agent to analyze the diff. Focus on:
   - Correctness and potential bugs
   - Security issues
   - Style and consistency with project conventions
   - Missing tests or edge cases

5. **Decision**: Ask the user to merge or discard:
   - **Merge**: `curl -s -X POST http://localhost:8080/api/teams/<session_id>/merge` or `git merge --no-ff team/<session_id>`
   - **Discard**: `curl -s -X POST http://localhost:8080/api/teams/<session_id>/discard`

6. **Cleanup confirmation**: Verify the worktree was removed and branch was cleaned up.
