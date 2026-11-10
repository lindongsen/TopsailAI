---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-09
---

# `agent.models` is advertised as `read_output` while it mutates the live model

## Symptom

A credential that holds only the `read_output` scope can change the model of a running
agent. The catalog entry that carries the operation declares a read permission, so
admission accepts a mutating call.

## Evidence

- `conf/control-actions.conf.example:421-429` declares `agent.models` with
  `"permission": "read_output"`, `payload_constants: {"instruction": "agent.models"}`,
  schema `{args: array, kwargs: object}`, and command
  `["runtime","control","call_instruction","-s","{session}","-a","{payload}","--json"]`.
- `conf/control-actions.md:324` lists `agent.models` in the `read_output` shortcut table,
  while line 334 excludes `agent.set_llm` from shortcuts because it changes the model.
  The same reasoning applies to `agent.models` when it carries an argument.
- The provider applies the change: `workspace/plugin_instruction/agent.py:272-322`
  `select_model` selects by 1-based index or by name, and `agent.py:57-147`
  `_apply_model_config` swaps model, api_base, api_key and environment in the live agent.
- Admission uses the declared permission: `internal/server/commands.go:212-216` calls
  `declaredPermission` then `security.AuthorizeOperation`, and
  `internal/security/scopes.go:65-79` grants access when the caller holds the declared
  permission.

Reachability is verified by producer source, not inferred from the consuming mapping.

## Impact

A read-only operator credential is sufficient to change which model a running agent uses.
The change is in-process and survives until the agent restarts, so it silently alters
subsequent agent behaviour and cost.

## Suggested fix

Split the catalog entry into two:

- `agent.models` with `read_output`, no `args`, listing only.
- `agent.model.select` with `control`, `args` required, applying one entry.

Alternatively keep one entry and raise its permission to `control`, at the cost of
requiring a control credential even to list.

## Related

- `internal/adapter/topsailai/ctl_actions.go:40` hardcodes `SafetyClass: "mutating"` for
  every catalog action, so a read-only listing cannot be advertised truthfully.
- Planned command work: `.task/plan_20261109T150000_session-model-command.md`.
