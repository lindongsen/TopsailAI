---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

## Scope correction

The human clarified on 2026-11-16 that this issue does not describe the reported
failure. The operator uses `history` followed by `resume <row>` or
`resume -s <session-id>`, and every target supplied is a persisted session the
operator has already confirmed is resumable. Analysis sessions (`sad-*`) are
explicitly out of scope, quoted verbatim:

> 你不要理会 sad-xxx

This issue records a real but separate defect. The reported failure is tracked in
`issues/resume-from-history-row-fails.md`.

# Resume fails for analysis session identifiers

## Trigger

Reported by the human on 2026-11-16, wording normalized, meaning preserved:

> resume 指令完全用不了

Reported together with a second symptom, quoted verbatim:

> 经常出现 provider error

## Symptom

`resume` fails with `session_not_found` for every session whose provider identifier starts with
`sad-`. The operator sees a provider error and cannot resume the session.

Reproduced on the live cluster:

```text
agent-cluster-cli --yes resume ac.ai-dev res_e0b7d28a5fabc5a70add3f77780d8e51
```

Provider response:

```text
action: resume
delivery_state: not_delivered
error_code: session_not_found
exit_code: 3
session_id: sad-060c0f632b7b
ok: false
resumed: true
startup_confirmed: false
```

Note the internal contradiction in the provider document: `resumed: true` while `ok: false` and
`startup_confirmed: false`. The `resumed` field is set before the lookup fails, so it does not
describe the outcome.

## Root cause

Two provider interfaces use two different identifier spaces, and the cluster passes the identifier
from one to the other.

The authority check reads `workspace list --json --local`
(`providers/topsailai/mutation_authority.go:48`). That list **does** contain `sad-*` rows, so the
check passes and the generation is empty, which is exactly the condition `requireResumableRecord`
accepts (`mutation_authority.go:133-142`).

The resume command then runs `workspace resume -s <id> --background --json`
(`providers/topsailai/mutation_argv.go:87`). That command resolves its target through the session
database, not through `workspace list`. The provider's own help states the contract:

```text
-s, --session SESSION_ID    exact persisted session ID
```

Verified by direct execution:

| Query | Result |
|---|---|
| `topsailai_list_sessions --json -- sad-060c0f632b7b` | `[]` |
| `topsailai_list_sessions --json -- wa-1fb57b5948b4` | full record |
| `topsailai_list_sessions --json -- 20261013131753` | full record |

So `wa-*` and `202*` sessions are resumable and `sad-*` sessions are not, because only the latter
are absent from the session database.

## Why `sad-*` sessions are absent from the session database

`sad-` is the analysis session prefix. Those sessions carry `category: agent_driver` and are created
by `scripts/session_agent_driver/`. They are analysis and driver sessions, not persisted user
sessions, so they are not written to the session database.

The provider project already records that these sessions are never cleaned up, because the driver
cannot authorize deletion of a session it is itself running
(`/TopsailAI/src/topsailai/cli/issues/issue-agent-driver-self-cleanup-never-authorized.md`). They
therefore accumulate and stay visible in `workspace list` forever.

## Scope on the live cluster

17 reported sessions, of which 12 are `sad-*`:

| Endpoint | `sad-*` rows | Other rows |
|---|---|---|
| `ac.ai-dev` | 4 | `wa-1fb57b5948b4`, `wa-32a8175d8abd`, `20261013131753` |
| `ac.topsail` | 4 | `wa-8bf2d54f19bb` |
| `ac.topsailai-dev` | 4 | none |
| `ac.gd-dev` | 0 | none |

Every `sad-*` row reports `state=unknown` with an empty `provider_generation`. The four identifiers
are identical across all three endpoints, because they come from one shared task directory.

## Why resume is unusable in practice, not only for `sad-*`

The `sad-*` failure alone would leave three resumable sessions. They are not resumable either, and the
reason is the opposite guard.

Every non-`sad-*` row is live:

| Session | Endpoint | State | Generation |
|---|---|---|---|
| `wa-1fb57b5948b4` | `ac.ai-dev` | `waiting_input` | `556893018` |
| `wa-32a8175d8abd` | `ac.ai-dev` | `running` | `573185430` |
| `20261013131753` | `ac.ai-dev` | `waiting_input` | `573467476` |
| `wa-8bf2d54f19bb` | `ac.topsail` | `running` | `573282214` |

`requireResumableRecord` rejects a live target with `target session is already live`
(`mutation_authority.go:138-140`). So every live row is refused by design, and every non-live row is
refused by the identifier mismatch.

The two guards therefore cover the whole inventory: a row is either live and refused as already
running, or unverified and refused as not found. No row can be resumed. That is why the operator
reported the command as completely unusable rather than as failing sometimes.

The provider can resume a `wa-*` session when that session is not live. This was observed on
2026-11-14, when four `wa-*` sessions were resumed successfully
(`/TopsailAI/src/topsailai/issues/issue-resume-loses-project-workspace-and-silent-failure.md`). The
capability exists; the cluster simply never presents a target that reaches it, because a session that
is not live is reported as `sad-*` or as a live row.

## Not caused by the 3248 upgrade

```text
git log --oneline 7dae9d69..7b57076a -- providers/topsailai/mutation_argv.go \
  providers/topsailai/mutation_authority.go src/main/agent-cluster-endpoint/adapter_factory.go
```

returns no commits. The defect predates the upgrade.

## Why the existing tests did not catch it

`providers/topsailai/mutation_test.go:127` asserts the argv shape with a synthetic identifier `s-1`:

```go
want: []string{"workspace", "resume", "-s", "s-1", "--background", "--json"},
```

That test proves the selector is passed as `-s`, which was the earlier defect recorded in
`issues/done/cli-provider-resume-argv.md`. It cannot prove that the identifier value is one the
provider's lookup understands, because `s-1` is not a real identifier from either space.

## Candidate fixes

| Direction | Change | Trade-off |
|---|---|---|
| A | Provider maps a runtime identifier to a persisted identifier before invoking `workspace resume` | Requires a provider project change; keeps one operator-facing identifier |
| B | Cluster refuses resume for `sad-*` and explains why | Cluster-only change; removes a false capability but the operator still cannot resume |
| C | Provider excludes `sad-*` from `discover` so they never appear in the cluster | Smallest surface; the operator loses visibility of analysis sessions entirely |

Direction C is the smallest change and removes the false offer at its source. Direction A is the
correct long-term fix if an operator should be able to resume by the identifier the cluster shows.
Direction B leaves a listed-but-unusable row, which is the same class of defect as the one recorded
in `LEARN.md` under "A gate on the action does not guard the menu that offers the action".

## Open question

`docs/agent-cluster-adapters.md` states that revalidation deliberately omits `--local` so a session
recorded on another host remains resumable, but `mutation_authority.go:48` passes `--local`. The two
disagree. This does not cause the `sad-*` failure, because those rows are local, but it must be
decided before either fix lands.

## Files

- `providers/topsailai/mutation_authority.go`
- `providers/topsailai/mutation_argv.go`
- `providers/topsailai/mutation_test.go`
- `docs/agent-cluster-adapters.md`
