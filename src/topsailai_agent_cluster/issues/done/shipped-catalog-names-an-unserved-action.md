---
maintainer: AI
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: AGENT_CLUSTER
programming_language: go
---

# The shipped catalog names an action the provider does not serve

## Trigger

`cd providers/topsailai && go test ./... -count=1` fails at HEAD with two failures:

```text
--- FAIL: TestShippedCatalogKeepsShortcutCopiesIdentical (0.00s)
    catalog_shipped_test.go:214: shortcut "session.heartbeat" runs a different command than "heartbeat"
--- FAIL: TestShippedCatalogNamesOnlyProviderActions (0.00s)
    catalog_shipped_test.go:270: the shipped catalog names "not_a_provider_action", which the provider does not serve
```

`git status --short -- .` is empty at the time of observation, so both failures exist at HEAD and are not caused by an uncommitted change.

## Symptom

`conf/control-actions.conf.example:151-159` declares a `heartbeat` action whose argv is:

```text
runtime control not_a_provider_action ...
```

`not_a_provider_action` is a placeholder name, not a provider action. The shipped catalog is the file an operator copies by hand to configure the Provider, so a copy of it advertises an action that cannot run.

`conf/control-actions.conf.example:1205-1213` declares `session.heartbeat` as a shortcut whose argv names `heartbeat`. Because the target action's argv differs from the shortcut's argv, `TestShippedCatalogKeepsShortcutCopiesIdentical` also fails: a shortcut must inherit its target's command exactly.

## Impact

An operator who copies the shipped example and enables `heartbeat` gets a `ctl.heartbeat` entry that the provider rejects at invocation time, after the catalog lookup succeeded and after the Endpoint recorded the command as admitted. The failure is reported as a provider error rather than as an unconfigured action, so the operator is told the provider failed instead of being told the entry is wrong.

The second failure is a test-level guard, not an operator-facing defect: it exists to keep the shipped example honest, and it is currently reporting that the example is not honest.

## Expected

The shipped example must name only actions the provider serves, and a shortcut's argv must be identical to its target's argv. Either the placeholder is replaced with a real provider action, or the `heartbeat` entry and its shortcut are removed from the example.

## Scope

- `conf/control-actions.conf.example:151-159` and `:1205-1213`.
- No Go source change is expected; the guards in `providers/topsailai/catalog_shipped_test.go` are correct and must not be weakened to accept the placeholder.

## Verification

After the fix, `cd providers/topsailai && go test ./... -count=1` must pass with no failures, and `git diff -- conf/control-actions.conf.example` must show only the placeholder or entry change.

## Root cause

This was not a catalog design defect. `833513df refactor: shape the shipped catalog for the provider cli`
ran a destructive probe that renamed the `heartbeat` entry's argv action to `not_a_provider_action` to
prove `TestShippedCatalogNamesOnlyProviderActions` fails, and the probe was never restored. The parent
commit `833513df^` carries the original argv:

```text
"command": ["runtime", "control", "heartbeat", "-s", "{session}", "-a", "{payload}", "--json"]
```

The probe record in `.task/status_20261114T180000_provider-cli-unit8-4c.md` lists
`Name an action the provider does not serve` as a destructive probe, which confirms the placeholder was
probe input rather than intended content. The other two probes from the same commit (`permission`,
`alias_of`) left no residue: `grep -n '"permission"\|alias_of' conf/control-actions.conf.example` returns
nothing.

`heartbeat` is a real provider action: `cli_topsailai/runtime_cli.py` lists it in
`_FALLBACK_CONTROL_ACTIONS`, and `workspace/control_handlers/heartbeat.py` declares `action = "heartbeat"`.
The `session.heartbeat` shortcut's argv was always `heartbeat`, so restoring the target entry's argv makes
both failing guards pass together.

## Resolution

`conf/control-actions.conf.example:159` restored from `not_a_provider_action` to `heartbeat`. The
`heartbeat` entry and the `session.heartbeat` shortcut were kept, because both are valid configuration;
deleting them would have hidden the probe residue by removing a feature. No guard was added or weakened:
`TestShippedCatalogNamesOnlyProviderActions` and `TestShippedCatalogKeepsShortcutCopiesIdentical` already
cover this defect and are the tests that caught it.

## Status

Done. `cd providers/topsailai && go test ./... -count=1` passes with no failures.
