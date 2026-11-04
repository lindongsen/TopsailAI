---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - ai_base/tool_approval/matcher.py
  - ai_base/tool_approval/instance.py
  - ai_base/tool_approval/transport.py
  - ai_base/tool_approval/decorator.py
  - ai_base/tool_approval/formatting.py
  - ai_base/tool_approval/registry.py
  - ai_base/agent_types/tool.py
  - cli/topsailai_test_tool_approval_rules.py
---

# External Tool Approval Policy

How to gate dangerous tool calls behind a human decision using a policy file that lives outside the
codebase, so the rules can change without a rebuild and without editing the agent.

## Why This Exists

An operations team runs an agent that can execute shell commands and write files. Most of what the
agent does is harmless: read a log, check a branch, write a scratch file. A small fraction is not:
delete a directory, force-push a branch, write under `/etc`. The team wants the harmless work to run
unattended and the dangerous work to stop and ask a human.

The obvious place to encode that distinction is inside each tool. That is the wrong place. The tool
owns one job — perform the operation — and it has no idea which deployment considers `rm` dangerous.
A second deployment may allow `rm` inside a scratch directory and forbid it everywhere else. Putting
the policy in the tool means every deployment edits the tool, and the policy ends up duplicated
across every tool that can do damage.

The approval gate is the natural solution because it sits **between** the agent's decision to call a
tool and the tool actually running. The policy is a JSON document that the operator points an
environment variable at, so the rules are data rather than code, and the same gate protects every
tool without any tool knowing it exists.

The second requirement is what makes this more than a confirmation prompt: the gate must behave
predictably when **nobody is there to answer**. An agent often runs unattended — in CI, in a
scheduled job, behind a pipe. A gate that blocks forever is worse than no gate, because it turns a
refused operation into a hung process. So every rule carries a timeout and a timeout policy, and the
timeout policy alone decides the outcome when no human answers.

| Aspect | This recipe |
|--------|-------------|
| Extension point | `TOPSAILAI_TOOL_APPROVAL_RULES` |
| Fires when | Before a tool executes, after the agent has chosen it |
| Policy format | JSON array, inline or in one or more files |
| Matching | `priority` ascending, first matching rule wins |
| Unanswered request | The rule's `policy` decides: `deny`, `allow`, or `ask_again` |
| Tools changed | None |
| Failure isolation | A broken policy file disables the gate and logs critical; tools still run |

## Quick Start

The example policy is `docs/cookbook/approval/examples/ops_policy/tool_approval.json`. Point the
variable at the **absolute** path of that file and enable the gate:

```bash
export TOPSAILAI_TOOL_APPROVAL_ENABLED=1
export TOPSAILAI_TOOL_APPROVAL_RULES=/TopsailAI/src/topsailai/docs/cookbook/approval/examples/ops_policy/tool_approval.json
```

The repository ships a CLI that evaluates the policy without running an agent, which is the fastest
way to see what a rule set decides:

```bash
cd /TopsailAI/src/topsailai
uv run python cli/topsailai_test_tool_approval_rules.py \
  --rules /TopsailAI/src/topsailai/docs/cookbook/approval/examples/ops_policy/tool_approval.json \
  "cmd_tool-exec_cmd:git status"
```

Real output:

```text
Loaded 6 approval rule(s) from /TopsailAI/src/topsailai/docs/cookbook/approval/examples/ops_policy/tool_approval.json
--- Case 1 ---
Tool    : cmd_tool-exec_cmd
Command : git status
Rule    : read-only-inspection
Decision: ALLOW
Note    : allowed without approval
```

A read-only command is allowed with no prompt. A destructive command asks:

```bash
uv run python cli/topsailai_test_tool_approval_rules.py \
  --rules /TopsailAI/src/topsailai/docs/cookbook/approval/examples/ops_policy/tool_approval.json \
  "cmd_tool-exec_cmd:rm -rf /tmp/x"
```

Real output:

```text
Loaded 6 approval rule(s) from /TopsailAI/src/topsailai/docs/cookbook/approval/examples/ops_policy/tool_approval.json
--- Case 1 ---
Tool    : cmd_tool-exec_cmd
Command : rm -rf /tmp/x
Rule    : destructive-command
Decision: ASK
Timeout : 30.0
Policy  : deny
```

`ASK` means the gate will prompt a human and wait up to `30.0` seconds. If nobody answers, `deny`
wins and the tool does not run.

## Folder Layout

```text
docs/cookbook/approval/
  External_Tool_Approval_Policy.md
  examples/
    ops_policy/
      tool_approval.json
```

The policy file is the only artifact. There is no consumer script and no code to compile: the gate
reads the JSON and evaluates it in process. That is why this recipe has one example file instead of
an `examples/` folder with a runnable program.

## Rule Contract

The policy is a JSON array of rule objects. Every field is optional except `match`, and a rule with
no `params` matches every call to the named tool.

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `name` | string | `""` | Label shown in the approval prompt and in CLI output |
| `match` | string | required | Tool name pattern; only `*` is a wildcard |
| `mode` | string | `require` | `require` asks a human, `bypass` (alias `skip`) runs immediately |
| `params` | array | `[]` | Argument conditions; an empty array matches any arguments |
| `logic` | string | `and` | How `params` combine: `and` or `or` |
| `timeout` | number | `60` | Seconds to wait for a human answer |
| `policy` | string | `deny` | Outcome when nobody answers: `deny`, `allow`, or `ask_again` |
| `priority` | number | `0` | Sort key; lower value is evaluated first |

Each entry in `params` is one condition:

| Field | Meaning |
|-------|---------|
| `param` | Argument name to inspect, for example `cmd` or `file_path` |
| `op` | Comparison operator |
| `value` | Expected value; its type depends on the operator |

Supported `op` values:

| Operator | Behaviour |
|----------|-----------|
| `exists` | The argument is present and not `None` |
| `eq` | Equal to `value` |
| `ne` | Not equal to `value` |
| `contains` | The argument contains `value` as a substring |
| `not_contains` | The argument does not contain `value` |
| `starts_with` | The argument starts with `value` |
| `ends_with` | The argument ends with `value` |
| `regex` | `re.search(value, argument)` matches |
| `in` | The argument is one of the comma-separated items in `value` |
| `not_in` | The argument is none of the comma-separated items in `value` |
| `gt` | Numerically greater than `value` |
| `gte` | Numerically greater than or equal to `value` |
| `lt` | Numerically less than `value` |
| `lte` | Numerically less than or equal to `value` |

Two details matter when writing rules. First, `match` treats only `*` as a wildcard: `?` and `[` are
literal characters, and matching is case sensitive. Second, a condition whose `param` key is absent
is skipped rather than failing, so under `logic: and` such a condition is always true.

## Example Policy

The example encodes one realistic operations policy: read-only inspection and scratch writes run
unattended, destructive commands and production writes require a human, network egress retries the
prompt once, and a long build is allowed to proceed on timeout because a build is recoverable.

```json
[
  {
    "name": "read-only-inspection",
    "match": "cmd_tool-exec_cmd",
    "mode": "bypass",
    "priority": 10,
    "logic": "or",
    "params": [
      { "param": "cmd", "op": "starts_with", "value": "git status" },
      { "param": "cmd", "op": "starts_with", "value": "git log" },
      { "param": "cmd", "op": "starts_with", "value": "git diff" },
      { "param": "cmd", "op": "starts_with", "value": "ls " },
      { "param": "cmd", "op": "starts_with", "value": "cat " },
      { "param": "cmd", "op": "starts_with", "value": "grep " }
    ]
  },
  {
    "name": "scratch-file-write",
    "match": "file_tool-write_file",
    "mode": "bypass",
    "priority": 20,
    "params": [
      { "param": "file_path", "op": "regex", "value": "^/tmp/\\.tmp/" }
    ]
  },
  {
    "name": "destructive-command",
    "match": "cmd_tool-exec_cmd",
    "mode": "require",
    "priority": 30,
    "timeout": 30,
    "policy": "deny",
    "logic": "or",
    "params": [
      { "param": "cmd", "op": "regex", "value": "(^|\\s)(rm|rmdir|shred|dd|mkfs)\\s" },
      { "param": "cmd", "op": "contains", "value": "git reset --hard" },
      { "param": "cmd", "op": "contains", "value": "git push --force" },
      { "param": "cmd", "op": "starts_with", "value": "sudo " }
    ]
  },
  {
    "name": "production-file-write",
    "match": "file_tool-write_file",
    "mode": "require",
    "priority": 40,
    "timeout": 60,
    "policy": "deny",
    "params": [
      { "param": "file_path", "op": "regex", "value": "^/(etc|srv|opt|var)/" }
    ]
  },
  {
    "name": "network-egress",
    "match": "cmd_tool-exec_cmd",
    "mode": "require",
    "priority": 50,
    "timeout": 20,
    "policy": "ask_again",
    "params": [
      { "param": "cmd", "op": "regex", "value": "(^|\\s)(curl|wget|ssh|scp)\\s" }
    ]
  },
  {
    "name": "long-running-build",
    "match": "cmd_tool-exec_cmd",
    "mode": "require",
    "priority": 60,
    "timeout": 15,
    "policy": "allow",
    "logic": "and",
    "params": [
      { "param": "cmd", "op": "starts_with", "value": "make " },
      { "param": "cmd", "op": "contains", "value": "test" }
    ]
  }
]
```

What each rule decides, verified by running the CLI against this exact file:

| Input | Rule | Decision | Timeout | Policy |
|-------|------|----------|---------|--------|
| `git status` | `read-only-inspection` | `ALLOW` | - | - |
| `rm -rf /tmp/x` | `destructive-command` | `ASK` | `30.0` | `deny` |
| `curl https://example.com` | `network-egress` | `ASK` | `20.0` | `ask_again` |
| `make test` | `long-running-build` | `ASK` | `15.0` | `allow` |
| `echo hello` | `no match` | `NO_APPROVAL` | - | - |
| `/tmp/.tmp/scratch.txt` | `scratch-file-write` | `ALLOW` | - | - |
| `/etc/passwd` | `production-file-write` | `ASK` | `60.0` | `deny` |
| `/tmp/other.txt` | `no match` | `NO_APPROVAL` | - | - |

The last row of each group is the important one: a call that matches no rule is **not** blocked. The
gate only acts on rules the operator wrote, so an incomplete policy fails open by design.

## No TTY Behaviour

This is the part that decides whether the gate is usable unattended. When the process has no
terminal, the gate cannot prompt, so the rule's `policy` decides the outcome after `timeout`
seconds. The CLI reports this explicitly:

```bash
cd /TopsailAI/src/topsailai
uv run python cli/topsailai_test_tool_approval_rules.py \
  --rules /TopsailAI/src/topsailai/docs/cookbook/approval/examples/ops_policy/tool_approval.json \
  -i --timeout 1 "cmd_tool-exec_cmd:rm -rf /tmp/x" < /dev/null 2>&1
```

Real output:

```text
[WARN] stdin is not a TTY and no agent runtime input function is registered; the approval prompt cannot be answered, the timeout policy will decide.
--- Case 1 ---
Tool    : cmd_tool-exec_cmd
Command : rm -rf /tmp/x
Rule    : destructive-command
Decision: ASK
Timeout : 1.0
Policy  : deny
Outcome : DENIED
By      : policy
Note    : tool call would be blocked
```

The `[WARN]` line is the signal that no human can answer. `By: policy` distinguishes a timeout
decision from a human decision, which reports `By: user`.

The same rule set with `policy: allow` produces the opposite outcome, which is why `allow` must be
reserved for operations that are safe to repeat:

```bash
uv run python cli/topsailai_test_tool_approval_rules.py \
  --rules /TopsailAI/src/topsailai/docs/cookbook/approval/examples/ops_policy/tool_approval.json \
  -i --timeout 1 "cmd_tool-exec_cmd:make test" < /dev/null 2>&1
```

Real output:

```text
Outcome : APPROVED
By      : policy
Note    : tool call would be executed
```

`ask_again` is the third policy and it costs two wait rounds rather than one: the gate resets the
request to pending, waits again, and only then denies. Measured with `/usr/bin/time` on the same
command, `policy: deny` finished in `1.19` seconds while `policy: ask_again` finished in `2.19`
seconds. Use `ask_again` only when a human is likely to be slow but present, because it doubles the
worst-case delay before the tool is refused.

## Interactive Approval

When a terminal is present, the gate renders a request and reads one line. The prompt shows the
matched rule and its pattern directly under the request id, then the tool, timeout, policy, and the
full arguments:

```text
[APPROVAL REQUEST] b42b57c3-...
Rule: destructive-command
Pattern: cmd_tool-exec_cmd
Tool   : cmd_tool-exec_cmd
Timeout: 30.0s
Policy : deny
Args:
  cmd: rm -rf /tmp/x
Type 'approve'(yes) or 'deny'(no): > approve
```

Answering `approve` runs the tool:

```text
Outcome : APPROVED
By      : user
Note    : tool call would be executed
```

Answering `deny` blocks it:

```text
Outcome : DENIED
By      : user
Note    : tool call would be blocked
```

Any other input is treated as a refusal rather than a retry. Typing `maybe` produces a warning and a
denial:

```text
> maybe
Outcome : DENIED
By      : user
```

The accepted answers are `approve`, `yes`, and `y` for approval, and `deny`, `no`, and `n` for
refusal. Everything else denies, because an ambiguous answer must never authorize a destructive
operation.

The arguments are rendered in a readable block rather than as escaped JSON: a string containing line
breaks is printed literally behind a `| ` marker, containers are printed one entry per line, and an
empty argument mapping renders as `(none)`. Two variables bound only the display —
`TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_LINES` (default `40`) and
`TOPSAILAI_TOOL_APPROVAL_DISPLAY_MAX_VALUE_CHARS` (default `2000`). The tool always receives the
original untruncated arguments, so a long value is shortened on screen but not in the call.

## Rejected Inputs

Every row below is a real run against this example policy. They are the mistakes that cost the most
time, because most of them fail silently.

| Input | Observed result | Why |
|-------|-----------------|-----|
| `--rules docs/cookbook/approval/examples/ops_policy/tool_approval.json` | `Loaded 0 approval rule(s)`, then `no match` / `NO_APPROVAL`, exit `0` | A relative path is treated as a file path but resolved against the working directory, so the file is not found |
| `--rules /tmp/.tmp/approval_doc/broken.json` | `Loaded 0 approval rule(s)`, `CRITICAL ... Invalid JSON in approval rules file ...: Illegal trailing comma before end of object: line 2 column 53 (char 54)`, `ERROR ... Disabling tool approval due to configuration error` | A malformed policy disables the gate instead of blocking every tool |
| `"curl https://example.com"` without a tool prefix | `Tool : curl https`, `Args : {'value': '//example.com'}`, `no match` | The CLI splits on the first `:`, so the URL scheme is consumed as part of the tool name |
| `TOPSAILAI_TOOL_APPROVAL_ENABLED=0` together with `--rules` | still `Loaded 6` and `Decision: ASK` | The CLI forces the gate on so it can evaluate rules |
| `mode: "maybe"` | `Decision: ASK`, `Timeout: 60.0`, `Policy: deny` | An unknown mode falls back to `require`, the safe default |
| `policy: "explode"` | `Policy: deny` | An unknown policy is discarded and the default applies |
| `starts_with "ls ?"` against `ls -l` | `no match` | `?` is a literal character; only `*` is a wildcard |
| `regex "([unclosed"` | `no match` / `NO_APPROVAL` | A regex that fails to compile is swallowed and the condition is false |
| `in` with `value: "echo hi,ls -l"` against `echo hi ` | not matched | `in` splits the value on `,`, so a trailing space changes the item |
| condition with no `param` key under `logic: and` | matched for both `ls -l` and `echo hi` | A condition without a `param` is skipped, so it cannot fail |

Two of these deserve emphasis. The relative-path row is the most dangerous, because the command
exits successfully and the operator sees a working agent with no gate at all. The malformed-JSON row
is the second, because a typo in the policy silently removes protection instead of stopping the
agent. Both are deliberate: the gate is an advisory safety layer, and a broken policy must not take
the whole agent down. The consequence is that the policy file needs its own review, exactly like
code.

## Loader Behaviour

| Behaviour | Detail |
|-----------|--------|
| Variable | `TOPSAILAI_TOOL_APPROVAL_RULES` |
| Accepted forms | One JSON array literal, one file path, or several file paths joined by `;` |
| Path detection | A value containing `/`, containing `\`, or ending in `.json` is treated as a path |
| Parse order | The whole value is tried as JSON first; only on failure is it split on `;` |
| Default path | `os.path.join(TOPSAILAI_WORK_FOLDER, "tool_approval.json")` when the variable is empty |
| Missing default file | Yields an empty rule list, so the gate allows everything |
| Multiple files | Rule arrays are concatenated in the order given |
| Ordering | Sorted by `priority` ascending; the first matching rule wins |
| Declaration order | Irrelevant; only `priority` decides |
| Cache | Rules are cached per process in `_RULES_CACHE` |
| Cache invalidation | `clear_approval_rules_cache()`, or a new process |
| Config error | Sets `TOPSAILAI_TOOL_APPROVAL_ENABLED=0` and logs critical (fail open) |
| Default timeout | `60.0` seconds |
| Default policy | `deny` |
| Read timing | At call time, so a new process picks up an edited file without a rebuild |

`priority` ordering was verified by inverting two rules. With `narrow-bypass` at `5` and
`broad-require` at `90`, `git status` matched `narrow-bypass` and was allowed. Reversing the values
to `broad-require` at `1` and `narrow-bypass` at `5` made the same command match `broad-require` and
require approval, even though the file order did not change. The lower number always wins.

The cache is the one behaviour that surprises operators. Loading a different rule file in the same
process returns the first result:

| Step | Result |
|------|--------|
| Load `extra.json` | `['extra-deny-rm']` |
| Change the variable, load again | `['extra-deny-rm']` (stale) |
| Call `clear_approval_rules_cache()`, load again | the six example rules |

A long-running agent therefore keeps the policy it started with. Editing the file affects the next
process, not the current one.

## What This Recipe Cannot Do

- **It cannot prompt without a terminal.** With no TTY and no registered runtime input function, the
  gate never reads stdin. The timeout policy decides, so an unattended run cannot obtain a human
  answer no matter how long the timeout is.
- **It cannot fail closed on a broken policy.** A malformed file disables the gate and logs critical.
  If the policy must be authoritative, validate it in CI before deployment rather than relying on the
  runtime.
- **It cannot protect a tool that matches no rule.** An incomplete policy allows everything it does
  not mention. Coverage is the operator's responsibility, and the CLI is the way to check it.
- **It cannot reload rules inside a running process.** The rule list is cached; a change needs
  `clear_approval_rules_cache()` or a restart.
- **It cannot express a wildcard beyond `*`.** `?` and `[` are literal, and matching is case
  sensitive, so a pattern that looks like a glob silently matches nothing.
- **It cannot detect a condition that forgot its `param` key.** Such a condition is skipped, which
  under `logic: and` makes the whole rule match more broadly than intended.
- **It cannot report a bad regex.** A pattern that fails to compile yields a false condition instead
  of an error, so the rule quietly stops matching.
- **It cannot distinguish a human refusal from an unrecognized answer.** Both report `By: user` and
  `DENIED`; only the log line records that the input was unrecognized.
- **It cannot stop the agent when a tool is denied.** The denial is returned to the model as a tool
  observation string, so the agent continues and may choose another approach. The gate blocks one
  call, not the task.
- **It cannot bound the arguments it passes.** The display limits truncate only what is shown; the
  tool receives the full value.

## Related Documents

- [Cookbook index](../README.md) — the rules every recipe follows.
- [External Tool Execution Audit](../hook/External_Tool_Execution_Audit.md) — observing tool calls after they
  run, which complements this gate.
- [Memory Sync To An External Index](../hook/Memory_Sync_To_External_Index.md) — another external-integration
  recipe built on a Hook rather than a policy file.
- [Post-Final-Answer Notification](../hook/Post_Final_Answer_Notification.md) — publishing the agent's answer
  to an external system.
- [Skill Lifecycle Guard](../hook/Skill_Lifecycle_Guard.md) — recording skill execution for compliance.
- [Environment Variables](../../Environment_Variables.md#tool-approval) — the full variable
  reference for this gate.
