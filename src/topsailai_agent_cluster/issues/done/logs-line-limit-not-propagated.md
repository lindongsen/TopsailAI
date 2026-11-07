---
maintainer: AI
author: DawsonLin
---

# Session-scope `logs -n` line limit was not propagated

## Trigger

Human report (verbatim):

> 我发现 session scope中的 logs -n 这个lines参数没有生效

The operator ran `logs -n <lines>` inside a session scope of the interactive REPL and observed that the
requested trailing line count did not change the returned output.

## Observed behavior

`parseLogsArgs` accepted `-n`, `--lines` and `--lines=` and returned the requested count, but the count
never reached the Endpoint or the provider. The provider always received its own default line count, so
`logs -n 250` returned the same short snapshot as `logs`. The only effect of `-n` was a client-side tail
trim of an already short document, which is a no-op for any count above the provider default.

## Root cause

The line count was dropped at the client/server boundary and the remaining wire field was semantically
overloaded:

1. `internal/tui/interactive_ops.go` parsed `-n` into `maxLines` correctly.
2. `internal/tui/commands.go` `CommandRunner.Logs` passed only `maxBytes` to `API.GetOutput` and used
   `maxLines` solely for `RenderSnapshot`, a client-side trim.
3. `internal/tui/commands.go` `CommandAPI.GetOutput` had no line-count parameter.
4. `internal/client/api.go` sent only `max_bytes`.
5. `internal/server/http.go` built `protocol.OutputSnapshotRequest` with `MaxBytes` only.
6. `internal/protocol/command.go` `OutputSnapshotRequest` had no line field.
7. `internal/endpoint/executor.go` forwarded the byte budget as `adapter.OutputRequest.Limit`.
8. `internal/adapter/topsailai/adapter.go` interpreted `Limit` as a **line count** and clamped it to
   `20` whenever it exceeded `10000`, so the 64 KiB byte budget silently became `-n 20`.
9. `internal/adapter/command.go` interpreted the same `Limit` field as **bytes** (`--max-bytes`).

The single `Limit` field therefore meant bytes for the generic command adapter and lines for the
TopsailAI adapter, which is why the defect could not be fixed by changing one clamp.

## Resolution

`OutputSnapshotRequest` and `adapter.OutputRequest` now carry two explicit budgets, `MaxBytes` and
`MaxLines`. The TUI, client, Server, Endpoint executor and both adapters pass both values, and each
adapter uses only the budget that matches its provider contract: TopsailAI maps `MaxLines` to
`runtime logs -n`, the generic command adapter maps `MaxBytes` to `--max-bytes`. An omitted `max_lines`
stays `0`, which preserves the previous provider default of 20 lines for callers that do not ask for a
specific count.

## Prevention

Regression tests assert the provider argv for an explicit line count, assert that the byte budget no
longer influences `-n`, and assert that the generic command adapter still receives the byte budget.
