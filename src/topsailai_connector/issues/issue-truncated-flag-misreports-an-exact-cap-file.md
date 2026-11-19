---
maintainer: AI
author: DawsonLin
status: open
severity: low
created: 2026-11-19
platform: windows
---

# `file.read` reports `truncated: true` for a file whose size is exactly the cap

## Symptom

A file whose size is exactly `MaxResponseBytes` (262144 bytes) is read completely,
but the response says it was truncated. Measured on Windows against a running
Node, with the CLI on Linux:

```
exact256k.bin, 262144 bytes
  file.read (no --length)
    rc=0
    decoded content = 262144 bytes
    sha256 of the decoded content == sha256 of the source
    stderr: connector-server cli: content truncated at 262144 bytes
    --json: {"size":262144,"truncated":true}
```

The neighbouring sizes bracket the defect:

```
exact262143.bin, 262143 bytes  -> size 262143, truncated false
exact256k.bin,   262144 bytes  -> size 262144, truncated true   (wrong)
exact262145.bin, 262145 bytes  -> size 262144, truncated true   (correct)
```

The content is complete and byte-identical, so the flag is wrong rather than the
data. A caller that trusts the flag issues one more read at `offset=262144`, gets
`size:0, truncated:false`, and concludes the file was 262144 bytes: the right
answer reached by an unnecessary request. A caller that instead treats
`truncated:true` as "the file is larger than what I received" and stops will
believe a complete file is incomplete.

The defect is confined to the exact-multiple boundary, because a file of 262145
bytes fills the buffer and genuinely has more data behind it.

## Cause

`internal/node/fence.go` `Scope.Read` decides truncation from the byte count it
read, not from whether more data remains:

```go
truncated := int64(read) == limit && limit == MaxResponseBytes
```

When the file is exactly 262144 bytes, `read == 262144` and `limit == 262144`, so
the condition holds even though the read reached end of file. The expression
cannot distinguish "filled the buffer and stopped" from "filled the buffer and
there was nothing left".

## Detection gap

Every existing test reads a file smaller than the cap or a file larger than the
cap. The exact-multiple case is the only one where the two meanings of "read the
whole buffer" differ, and no test used a file of exactly `MaxResponseBytes`. The
condition reads correctly on its own, so review did not catch it either.

## Fix direction

Decide truncation by attempting one more byte, or by comparing the read count
against the file size reported by the already-obtained `FileInfo`. The second is
cheaper but is a claim about the file rather than about the read, so a file that
grows during the read would still be misreported; the first is exact. Either way
the test must use a file of exactly `MaxResponseBytes`, plus `MaxResponseBytes-1`
and `MaxResponseBytes+1`, and assert the flag rather than only the byte count.

## Scope

Read-only, no data loss, no security consequence. The wrong flag is a correctness
defect in the response contract described in `docs/API.md`, which states that
`truncated` reports whether the content was cut off.
