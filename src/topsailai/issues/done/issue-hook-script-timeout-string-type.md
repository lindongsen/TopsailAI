---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
references:
  - /TopsailAI/src/topsailai/utils/hook_tool.py
  - /TopsailAI/src/topsailai/utils/cmd_tool.py
---

# Issue: `timeout=` in a hook script entry is passed to `exec_cmd` as a string

## Symptom

`utils/hook_tool.py::build_cmd_parameters()` copies the parsed `timeout` option
straight from the environment string into the `exec_cmd` keyword arguments:

```python
result = dict(
    cmd=script_file,
    timeout=cmd_options.get("timeout") or DEFAULT_CMD_TIMEOUT,
    ...
)
```

`get_hook_scripts_info()` builds `cmd_options` from `shlex.split()` tokens, so
every value is a `str`. `cmd_tool.exec_cmd()` then forwards it to
`process.communicate(timeout=...)`, which requires a number. The call raises:

```text
TypeError: unsupported operand type(s) for +: 'float' and 'str'
```

The exception is caught by `call_hook_scripts()` and logged as
`call hook failed: [<ENV_KEY>], unsupported operand type(s) for +: 'float' and 'str'`,
so the hook silently does nothing.

## Reproduction

```bash
export TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER="/path/to/script.py timeout=10"
```

The script is started (its side effects are visible) but its result is never
collected, and `call_hook_scripts()` returns `{script: None}`. Omitting the
`timeout=` option works, because the default `DEFAULT_CMD_TIMEOUT` is an `int`.

## Reachability

Every caller of `hook_tool.call_hook_scripts()` is affected:

- `workspace/agent/hooks/post_final_answer.py` — `TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER`
- `tools/memory_tool_utils/memory_hooks.py` — `TOPSAILAI_HOOK_SCRIPTS_MEMORY_WRITE`

Both documented formats explicitly show `timeout=`, so the documented usage is
the broken one. `TOPSAILAI_MEMORY_SYNC_HOOKS` is unaffected because it validates
`timeout` as an `int` before dispatch.

## Impact

A configured hook appears to run and reports no error to the operator beyond a
log line, while its return value is always `None`. Any consumer that relies on
the returned tuple (exit code, stdout) cannot distinguish "hook succeeded" from
"hook never ran". The child process is also left unreaped by the caller, because
the exception happens inside `communicate()`.

## Suggested fix

Coerce the option in `build_cmd_parameters()` with the same validation the memory
sync path uses: accept a positive integer, fall back to `DEFAULT_CMD_TIMEOUT`
with a warning otherwise. Add a unit test that passes `timeout=10` through
`get_hook_scripts_info()` and asserts the resulting `exec_cmd` keyword is an
`int`.

## Discovered while

Writing the cookbook recipe for `TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER`. The
documented `timeout=` form was copied from
`docs/Environment_Variables.md` and failed on the first real run, which is how
the defect surfaced.

## Closure verification (2026-11-17)

Fixed in `utils/hook_tool.py::build_cmd_parameters()`. The parsed option is now
coerced with the existing `format_tool.to_int()` helper, which was already
imported in that module, instead of introducing a second conversion. A value
that is missing, non-numeric, zero, negative, or fractional falls back to
`DEFAULT_CMD_TIMEOUT` and logs a warning naming the script and the rejected
value.

Measured before the fix:

```
build_cmd_parameters('x.py', {'timeout': '30'})  ->  '30'  (str)
exec_cmd(cmd='echo hi', timeout='5')
  -> TypeError: unsupported operand type(s) for +: 'float' and 'str'
```

Measured after the fix:

```
build_cmd_parameters('x.py', {'timeout': '30'})  ->  30  (int)
exec_cmd(cmd='echo hook-ok', timeout=5)          ->  (0, 'hook-ok\n', '')
TOPSAILAI_HOOK_SCRIPTS_PROBE=".../hook_probe.py timeout=10"
  call_hook_scripts(...) -> {'.../hook_probe.py': (0, 'hook ran\n', '')}
```

The last line is the documented usage from `docs/Environment_Variables.md`,
which previously returned `{script: None}` because the exception was swallowed
inside `communicate()`.

`exec_cmd()` itself was left unchanged: it correctly requires a number, and
widening it would hide the same defect at every other call site.

Tests: `tests/unit/test_topsailai_utils_hook_tool.py` 24 passed. The
pre-existing `test_build_cmd_parameters_custom_timeout` asserted the buggy
contract (`result['timeout'] == '60'` with a comment admitting the string), so
it was corrected rather than left as a guard for the defect. Added coverage for
string coercion, five invalid spellings, and the real `get_hook_scripts_info()`
parsing path.

Negative control: the updated test file was copied into an isolated worktree at
pristine `HEAD` with the source fix absent, and the imported module was verified
to resolve inside that worktree. Result: 9 failed, 15 passed. With the fix:
24 passed. Related consumers `test_topsailai_workspace_agent_hooks_post_final_answer.py`
and `test_topsailai_tools_memory_hooks.py` also pass, 73 passed in total.
