---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# Policy load warnings are computed but never emitted

## Trigger

Discovered during the gd-dev live acceptance, scenario AUTH-LIVE-022. A policy file declaring an
operation the Endpoint does not serve was loaded, and the documented warning never appeared.

## Symptom

A policy file containing `permissions not.a.real.operation` loads successfully and the Endpoint
logs only the token count:

```text
INFO loaded endpoint access policy path=/opt/agent-cluster/policy tokens=8
```

No `WARN` line is emitted. The documentation states the warning is mandatory, so an operator who
mistypes an operation name gets silent acceptance instead of the diagnostic that exists to catch
exactly that mistake.

## Root cause

The warning is computed and then discarded. Three sites disagree:

- `internal/endpoint/accesspolicy.go:237` defines `Warnings()` on the parsed rule.
- `internal/endpoint/accesspolicy.go:425` returns the warnings from `ParseAccessRule`.
- `loadAccessPolicyFromDir` discards the second return value:

```go
rule, _, err := ParseAccessRule(...)
```

`src/main/agent-cluster-endpoint/main.go:208-230` logs only `tokens=N`. A repository-wide search
for a caller finds only the definition:

```text
$ grep -rn "\.Warnings()" internal/ src/
internal/endpoint/accesspolicy.go:237:func (r AccessRule) Warnings() []string {
```

So the "accept but warn" contract is implemented as "accept" only.

## Why it was not caught

The acceptance path is a hard error for an unknown scope and a warning for an unknown permission.
The scope path is tested because it fails loudly. The permission path returns success, so a test
that asserts "the file loads" passes while the warning is absent. No test asserts the warning text,
because the warning is not reachable from any production caller.

## Impact

An operator who writes `permissions output.raed` instead of `output.read` gets a policy that grants
nothing for that line and no diagnostic. The Endpoint then refuses the operation the operator
believed they had granted, and the refusal names the operation rather than the typo, so the
mistake is attributed to the Endpoint instead of to the policy file.

The same silence applies to a `permissions` entry naming an operation from a newer Endpoint
version, which is the version-skew case the warning was written for.

## Documentation contradiction

Both documents state the warning is mandatory:

- `docs/agent-cluster-protocol.md:309-310`
- `docs/agent-cluster-endpoint-access-policy.md:292,684`

The code does not implement it, so the documents describe behaviour that does not exist.

## Fix

Emit the warnings at both load sites:

1. `loadAccessPolicyFromDir` keeps the second return value and returns it with the rule.
2. `main.go` logs each warning at `WARN` with the file path and the warning text, before the
   `tokens=N` line.
3. The `SIGHUP` reload path logs the same warnings, because a reload is the moment an operator
   expects feedback on an edited file.

A test must assert the warning text for an unknown permission and must be confirmed to fail before
it is confirmed to pass.

## Status

Open. Scenario AUTH-LIVE-022 is recorded as **FAIL**, not PASS, because the documented behaviour is
absent. The live acceptance does not report unit 5 as passed while this scenario fails.
