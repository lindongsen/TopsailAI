---
maintainer: AI
author: DawsonLin
status: done
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

## Resolution

The authorization boundary moved to the Endpoint, so the path this issue describes is not
reachable in the current mechanism. This is a boundary migration, not a fix to the catalog
entry the issue named.

- The catalog declares no permission. `conf/control-actions.md:225` states it in the field
  table: `permission` is "Not declared here. The operator scope is declared on the Endpoint's
  `ADAPTERS` capability entry for the same operation name, because the Endpoint is the
  component that enforces it". `docs/Environment_Variables.md:242` says the same from the
  operator side: "`required_permission` in the adapter document is what a caller must hold".
  `providers/topsailai/catalog_shipped_test.go:155` `TestShippedCatalogDeclaresNoPermission`
  fails if a `permission` field is ever added back, with the reason in its comment: a
  permission field in the catalog would be a second, unread copy of an authorization
  decision, and the copy nobody reads is the one that drifts.
- The change path is a first-class operation, not a catalog entry.
  `protocol.OperationAgentModelSelect` is granted only by `security.ScopeControl`
  (`internal/endpoint/accesspolicy.go:73-81`), while `security.ScopeReadOutput`
  (`:65-68`) covers only `output.read` and `output.follow`. `ctl.*` operations are covered
  by `control` alone (`:337`). A caller therefore needs an explicit
  `permissions ctl.agent.models` line in the policy, which is an operator decision rather
  than a read-only credential being over-granted.
  `providers/topsailai/mutation_argv.go:126` `modelSelectArgs` builds the argv directly and
  its comment states why: "A first-class capability must not depend on someone having also
  written a catalog entry". The selection does not go through the catalog at all.
- The Evidence above is therefore stale. `conf/control-actions.conf.example` carries no
  `permission` field (`grep -c '"permission"'` returns 0), so the quoted
  `conf/control-actions.conf.example:421-429` no longer exists. The `read_output` grouping
  the Evidence cites at `conf/control-actions.md:324` was also wrong on its own terms, and
  that table now groups shortcuts by effect instead of by permission, with `agent.models`
  in the mutating group because it selects a model when it carries an argument.

What remains true is the general point the issue made: a shortcut narrows the menu, not the
wire. The Endpoint does not validate a payload against the advertised schema, so a caller
that builds the payload itself can still submit any instruction name the provider registers.
That is documented in `conf/control-actions.md` and is a separate concern from this issue.

The `Related` note about `internal/adapter/topsailai/ctl_actions.go:40` is also historical:
that package was deleted with the in-process adapter.
