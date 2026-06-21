---
status: fixed
priority: high
created_by: AIMember.km1-tester
fixed_by: AIMember.km3-programmer
fixed_at: 2026-06-21T04:00:00Z
related_docs:
  - docs/cases/TestCase_manual_cli_permissions.md
  - docs/cases/TestCase_manual_cli_cluster.md
  - docs/cases/TestCase_manual_cli_agent_trigger.md
---

# Issue: CLI interactive prompt with default value concatenates default and user input

## Summary

`InteractivePrompt.PromptStringWithDefault` in `cmd/cli/interactive.go` used `readline.ReadlineWithDefault(defaultValue)`, which placed the default value into the editable input buffer. When the user started typing without first clearing the buffer, the typed text was appended to the default, producing invalid values such as `acc-admin001acc-xxx`.

This affected any CLI flow that used `PromptStringWithDefault`, including `/api-key:create`, `/api-key:list`, `/api-key:delete`, `/account:update`, and any future command with a default value.

## Environment

- Workspace: `/TopsailAI/src/topsailai_server/agent_community`
- Server binary: `./bin/acs-server`
- CLI binary: `./bin/acs-cli`
- Server port: `7370`
- Database: PostgreSQL (`acs` database)
- NATS: local server (`nats://localhost:4222`)
- Test plans affected:
  - `docs/cases/TestCase_manual_cli_permissions.md` (PERM-004, PERM-006, PERM-009, PERM-011)
  - `docs/cases/TestCase_manual_cli_cluster.md`
  - `docs/cases/TestCase_manual_cli_agent_trigger.md`

## Reproduction Steps

1. Start the ACS server and authenticate the CLI as any account (e.g., admin).
2. Run a command that prompts with a default value, for example:
   ```
   /api-key:create
   ```
3. At the prompt:
   ```
   Account ID [acc-admin001]: acc-xxx
   ```
   type `acc-xxx` without first clearing the pre-filled default.

## Expected Behavior

The prompt accepts `acc-xxx` as the final value.

## Actual Behavior (Before Fix)

The resulting value was the concatenation of the default and the typed input:
```
acc-admin001acc-xxx
```
This caused subsequent API calls to return HTTP 404 `owner account not found` (or similar errors for other commands).

## Root Cause

`PromptStringWithDefault` called `readline.ReadlineWithDefault(defaultValue)`, which populated the editable input buffer with the default value. Any keystrokes appended to that buffer, causing the default and user input to be concatenated.

## Fix

### Changes Made

- **File:** `cmd/cli/interactive.go`
  - Changed `PromptStringWithDefault` to use `Readline()` instead of `ReadlineWithDefault(defaultValue)`.
  - The default value is still displayed in the prompt label (`Label [default]: `), matching the existing `PromptBool` pattern.
  - Empty input returns the default value; non-empty input returns the trimmed user value.

- **File:** `cmd/cli/interactive_test.go`
  - Added `TestPromptStringWithDefault_PromptShowsDefault` to verify the prompt label includes the default.
  - Added `TestPromptStringWithDefault_InputDoesNotAppendToDefault` to regression-test the concatenation bug.

### Code Diff

```diff
 // PromptStringWithDefault prompts for a string with a default value.
-// Pressing Enter without input accepts the default.
+// The default is shown in the prompt label, but the input line is left empty
+// so that typing does not append to a pre-filled buffer. Pressing Enter
+// without input accepts the default.
 func (p *InteractivePrompt) PromptStringWithDefault(label, defaultValue string) (string, error) {
 	p.reader.Clean()
 	p.reader.SetPrompt(fmt.Sprintf("%s [%s]: ", label, defaultValue))
-	line, err := p.reader.ReadlineWithDefault(defaultValue)
+	line, err := p.reader.Readline()
 	if err != nil {
 		return "", ErrCancelled
 	}
```

### Test Commands

```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./cmd/cli/ -run TestPromptStringWithDefault -v
go test ./cmd/cli/ -run 'TestPrompt|TestSequentialPrompts|TestPromptAccountCreate|TestPromptAPIKeyCreate|TestPromptPasswordChange|TestPromptInt|TestPromptChoice|TestPromptBool' -v
```

### Verification Results

- All `TestPromptStringWithDefault_*` tests pass.
- All prompt-related tests pass.
- Full `go test ./cmd/cli/` passes except for the unrelated pre-existing failure `TestHandleAccountCreate_ManagerPassesRoleThrough` (stale test expecting manager to send `role=admin`, while the CLI correctly forces `role=user`).
- `make build-cli` succeeds.

## Next Steps

1. Reviewer (`AIMember.km2-reviewer`) reviews this fix.
2. After approval, tester (`AIMember.km1-tester`) resumes `TestCase_manual_cli_permissions.md` from the affected interactive steps, then continues with the cluster and agent-trigger test plans.
