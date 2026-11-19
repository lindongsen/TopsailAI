---
maintainer: AI
author: DawsonLin
status: fixed
severity: low
created: 2026-11-19
fixed: 2026-11-19
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

## Resolution

Fixed on 2026-11-19 by taking the answer from the file instead of from the byte
count. `Scope.Read` now calls `moreDataRemains`, which probes one further byte
only when the cap was the binding limit and the buffer filled:

```go
func moreDataRemains(file *os.File, path string, read int64, limit int64) (bool, error) {
	if limit != MaxResponseBytes || read < limit {
		return false, nil
	}
	var probe [1]byte
	n, err := file.Read(probe[:])
	if n > 0 {
		return true, nil
	}
	if err != nil && !errors.Is(err, io.EOF) {
		return false, newError(protocol.CodeInternal, "read %q: %v", path, err)
	}
	return false, nil
}
```

The probe was chosen over comparing against `FileInfo.Size()` because the
`FileInfo` describes the file when it was opened, not when the read finished, so
a file that grows during the read would still be misreported. The probe answers
the question the flag actually asks.

A probe failure is `internal`, not "no more data". Treating an I/O error as end
of file would report a complete response for a read that could not be completed,
which is the same class of defect as the one being fixed.

### Tests added

| Test | Property |
|---|---|
| `TestScopeReadTruncationAtTheCapBoundary` | cap-1 `false`, cap `false`, cap+1 `true`, asserting the flag and the byte count at each size |
| `TestScopeReadTruncationAtTheCapBoundaryWithOffset` | a cap+100 file read at `offset=100` reaches end of file exactly and reports `false`; at `offset=99` one byte remains and reports `true` |
| `TestMoreDataRemainsReportsAProbeFailure` | a closed file yields `CodeInternal` rather than a silent `false` |
| `TestMoreDataRemainsSkipsTheProbeAfterAShortRead` | a read below the cap does not probe, proved by closing the file so a probe would fail |
| `TestMoreDataRemainsSkipsTheProbeForAnExplicitLength` | an explicit length equal to the read does not probe, even though the file has more data behind it |

The last two exist because mutation testing found the guard untested. Removing
`read < limit` left every test green, because the only case that reached the
guard used `limit == read == 6` with `limit != MaxResponseBytes`, which the first
condition already short-circuits. Splitting the case into two tests, each closing
the file so a probe would fail, made the guard observable.

### Mutation evidence

| Mutation | Result |
|---|---|
| Restore the byte-count rule | `exactly_the_cap` and the offset case fail |
| Make the probe never report remaining data | `one_byte_above_the_cap` and the offset case fail |
| Treat a probe failure as end of file | `TestMoreDataRemainsReportsAProbeFailure` fails |
| Remove the `read < limit` guard | all tests passed before the two guard tests were added; they fail afterwards |

Each mutation was reverted and the file compared with its backup by `md5sum`.

### Documentation updated

- `docs/API.md` states that `truncated` reports whether the content was cut off,
  not whether the response reached the cap, with the cap and cap+1 contrast.
- `docs/cases/TestCase_operations.md` gained `TC-OP-22a`, which asserts all three
  sizes and the follow-up read at `offset=262144`.
- `docs/cases/README.md` counts were updated for the new case.

### Verification

`gofmt -l` clean, `go vet ./...` clean, `go test ./...` green, `make check` rc=0
with 83.5% total coverage and 87.6% for `internal/node`.
