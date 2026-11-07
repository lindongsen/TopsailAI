---
maintainer: AI
author: DawsonLin
---

# Session-scoped logs return an empty body while provider output exists

## Trigger

Observed during live tmux verification of the adapter-owned project launch unit. A real hello task was
submitted, the provider consumed it and produced a model response, but a session-scoped output snapshot
returned an empty body.

## Observed behavior

- Provider stdout/events contain the model response for the session.
- The cluster's session-scoped logs read returns an empty body for the same session.

## Impact

An operator reading session output through the cluster sees nothing even though the agent produced a
response. This is the primary observation surface for a running agent, so an empty body is
indistinguishable from "the agent produced no output".

## Constraint

Do not infer absence of output from an empty snapshot. The provider is authoritative for whether output
exists; an empty cluster read is an observation gap until proven otherwise.

## Root cause (determined 2026-11-07)

The boundary is **cluster-side**, and it is not a defect in the output read path. The read path works:
every session that the cluster can address returns real content.

The defect is that a provider session without a provider generation is excluded from the standard
inventory, so it becomes unroutable, and the resulting failure is reported as a successful empty body.

1. `internal/adapter/topsailai/adapter.go:257-261` drops any workspace item whose generation is empty:

   ```go
   // Workspace history can contain idle records without a provider generation;
   // they cannot be addressed safely, so exclude them from routable sessions.
   if item.SessionID == "" || generation == "" {
       continue
   }
   ```

2. `internal/tui/commands.go:128-134` resolves the generation from that inventory. For an excluded
   session the lookup finds nothing, so `generation` stays `""`.
3. The output request therefore carries an empty generation. The endpoint rejects it as
   `invalid_target` and returns an empty body.
4. The API envelope still reports `code: 0` (success), and the CLI exits `0`, so the operator sees an
   empty result rather than a failure.

## Evidence

Live cluster (`local-endpoint`, 2026-11-07):

- Provider `topsailai workspace --format json` lists **9** sessions; the cluster inventory lists **8**.
- The missing session is `wa-9fac8fc572be` (`status: idle`), whose `process_generation` is `null` while
  every other item has a numeric generation.
- `topsailai runtime logs -s wa-9fac8fc572be -n 3 --json` returns `ok=true` with 3 lines, so provider
  output exists for the excluded session.
- All 8 routable sessions return real content through the cluster CLI (`len` 182-1057 bytes,
  `truncated=true`), so the read path itself is healthy.
- A request with an empty generation returns
  `{"code":0,"data":{"data":"","truncated":false,"observed_at_ms":0,"error_code":"invalid_target"}}`.
- A request with a stale generation returns `error_code: "generation_mismatch"` under the same
  `code: 0` envelope.

## Secondary defect: a failed read exits successfully

Both `invalid_target` and `generation_mismatch` are reported with `code: 0` and CLI exit status `0`.
In plain mode the CLI prints the bare token (`invalid_target`) to stdout; in JSON mode it prints an
empty `data` with the error code. A caller that checks only the exit status cannot distinguish "no
output" from "the target could not be addressed".

## Resolution

Not yet fixed. Two candidate directions, to be chosen before implementation:

- Report an unroutable session explicitly instead of an empty body, and exit non-zero when
  `error_code` is set, so an observation gap is never presented as an empty result.
- Decide whether a generation-less provider session should be addressable at all. If the provider can
  read it by session ID alone, the inventory exclusion is too strict for read-only operations; if it
  genuinely cannot be addressed, the exclusion is correct and only the reporting must change.

## Status

Open. Root cause determined; the fix direction requires a human decision because it changes whether a
generation-less session is addressable and whether a failed read exits non-zero.
