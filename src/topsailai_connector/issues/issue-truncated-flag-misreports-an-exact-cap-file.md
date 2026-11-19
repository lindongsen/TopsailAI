---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-19
---

# `truncated` is reported for a file whose size is exactly the cap

## Symptom

A `file.read` of a file whose size is exactly `MaxResponseBytes` (262144 bytes)
returns the complete content and reports `truncated: true`.

Measured against a real Server and Node:

```
exact256k.bin, 262144 bytes
  file.read  -> 262144 bytes written, sha256 identical to the source
  --json     -> {"size":262144,"truncated":true}
  stderr     -> content truncated at 262144 bytes
```

A file of 262145 bytes also reports `truncated: true`, and that answer is correct.
The defect is therefore confined to the boundary where the file size equals the cap.

## Cause

`internal/node/fence.go`, `Scope.Read`:

```go
truncated := int64(read) == limit && limit == MaxResponseBytes
```

The expression cannot distinguish "filled the buffer and more remains" from "filled
the buffer and the file ended exactly there". Both produce `read == limit`.

## Impact

The content is never wrong, so this is not a data-loss defect. The consequence is a
caller that treats the flag as "the file is larger than what I received":

- A caller that loops on `truncated` makes one extra request and receives zero bytes.
  The result is correct and the cost is one round trip.
- A caller that reports an error when `truncated` is true after a whole-file read
  rejects a complete file as incomplete.

The CLI's `-o` loop is written so it does not depend on this direction: it stops on
`truncated == false`, on a zero-byte response, or when the `--length` budget is spent.
A `false` value always means end of file, so trusting only that direction never drops
data.

## Detection gap

Every existing test used a file smaller than the cap or larger than the cap. No test
used a file whose size is exactly the cap, so the boundary was never exercised. The
`chunkServer` fixture in `internal/server/cli/output_test.go` reproduces the Node's
rule including this defect, deliberately, so the CLI is tested against the Node that
exists rather than an ideal one.

## Fix

Compare the byte count against the file size, or attempt one more byte and report
truncated only when it exists. The second form costs one extra read on the boundary
and needs no size query, so it is the smaller change.

## Verification required

- A file of exactly the cap reports `truncated: false`.
- A file of cap+1 reports `truncated: true`.
- A file smaller than the cap reports `truncated: false`.
- The CLI `-o` loop still produces a byte-identical result for all three, and the
  exactly-cap case drops from two requests to one.
