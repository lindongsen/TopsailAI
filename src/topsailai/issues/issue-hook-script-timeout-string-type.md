---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
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
