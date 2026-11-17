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

## Resolution

Resolved on 2026-11-17. Commit `209718cc`.

### The issue named one defect; there were two

The issue's root cause is correct: `loadAccessPolicyFromDir` (`internal/endpoint/accesspolicy_dir.go:161`)
discards the second return value of `ParseAccessRule`. But fixing only that caller would have produced a
permanently empty warning list, because a second defect sits underneath it.

`ParseAccessRule` (`internal/endpoint/accesspolicy.go:363`) returns `warnings` as a separate value and
never assigns `rule.Warnings`. `AccessPolicy.Warnings()` (`:249`) reads `rule.Warnings` through
`Rules()`. So the field was always nil regardless of any caller, and the issue's own grep result
(`only the definition, no caller`) was consistent with both defects at once. The grep could not
distinguish "nobody calls it" from "it can never return anything".

### What was changed

| File | Change |
|---|---|
| `internal/endpoint/accesspolicy.go:467-471` | `rule.Warnings = warnings` before the final return, with a comment recording why the rule carries them |
| `src/main/agent-cluster-endpoint/main.go` | `logAccessPolicyWarnings` helper; called at the startup load (`:257`) and the SIGHUP reload (`:247`), each before its `tokens=N` line |

The fix is placed in `ParseAccessRule` rather than in `loadAccessPolicyFromDir` because the rule is what
survives into the policy in force. Any future caller that keeps the rule now gets the warnings, so the
contract cannot be lost again by a caller that ignores the second return value.

### Tests

Eight behavioural tests plus two source-level guards:

| Test | Proves |
|---|---|
| `TestAccessPolicyWarningsSurviveIntoThePolicyInForce` | a misspelled permission reaches `AccessPolicy.Warnings()` |
| `TestAccessPolicyWarningsAreEmptyForAValidPolicy` | a clean policy produces no warning |
| `TestAccessPolicyWarningsFollowAReload` | a reload replaces the warning set |
| `TestAccessPolicyWarningsAreOrderedBySourceFile` | two files warn in a deterministic order |
| `TestAccessPolicyWarningsAreLoggedAtWarn` | the level is WARN, not INFO |
| `TestAccessPolicyWarningsLogNothingForAValidPolicy` | no log line for a clean policy |
| `TestAccessPolicyWarningsLogEachWarningSeparately` | one line per warning, not one joined line |
| `TestAccessPolicyWarningsTolerateANilPolicy` | a nil policy does not panic |
| `TestAccessPolicyWarningsAreCalledAtBothLoadSites` | `main.go` calls the helper at both loads |
| `TestAccessPolicyWarningCallsPrecedeTheTokenCount` | the diagnostic precedes the reassuring count |

### Deliberate breakage

Every test was proven able to fail before it was trusted.

1. Removed `rule.Warnings = warnings` → three tests failed with
   `the policy in force must carry exactly one warning, got []`.
2. Downgraded `logger.Warn` to `logger.Info` → one test failed with
   `the warning must be logged at WARN, got INFO`.
3. Removed the startup call site from `main.go` → **all eight behavioural tests still passed.** This
   exposed a real gap: the behavioural tests call the helper directly and never prove `main` calls it.
   The two guard tests were added to close it, following the `catalog_deployment_guard_test.go`
   convention of reading the source instead of restating it.
4. Removed the reload call site → both guard tests failed, naming the missing call.
5. Swapped the reload call and its count line → `TestAccessPolicyWarningCallsPrecedeTheTokenCount`
   failed with `the reload token count is logged before its warnings`.

All breakages were restored and the suites re-run green.

### Verification

```text
go test ./src/main/agent-cluster-endpoint/ ./internal/endpoint/
ok  topsailai_agent_cluster/src/main/agent-cluster-endpoint  0.328s
ok  topsailai_agent_cluster/internal/endpoint                6.550s

go vet ./src/main/agent-cluster-endpoint/ ./internal/endpoint/   (clean)
gofmt -l src/main/agent-cluster-endpoint/ internal/endpoint/     (clean)
```

### Limitation

The guard tests assert the call sites exist and are ordered correctly in the source. They do not prove
the Endpoint binary emits the line at runtime, because that would require starting a real Endpoint with
a policy directory containing a misspelled permission. That live check remains part of the gd-dev
acceptance for scenario AUTH-LIVE-022, which can now be re-run against a rebuilt binary.

### Status

Resolved. Scenario AUTH-LIVE-022 can be re-evaluated after the Endpoint binary is rebuilt and deployed;
the deployed binary predates this commit, so the live scenario still reports the old behaviour until
then.
