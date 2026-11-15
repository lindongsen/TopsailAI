---
maintainer: AI
author: DawsonLin
---
# Encoding detection samples only the first 32 KiB and corrupts later UTF-8

`file read` returns different bytes than were stored whenever a non-ASCII
character appears after byte 32766 of a file whose first 32768 bytes are pure
ASCII. The command exits `0` and the output is still valid UTF-8, so the
corruption is silent.

## Observed behaviour

A 66000-byte file of ASCII text with a single `U+2502` (BOX DRAWINGS LIGHT
VERTICAL, bytes `e2 94 82`) placed at byte 40000:

```
bin/topsailai-data create ex66000 --from ex66000.md
bin/topsailai-data get ex66000 ex66000.md > roundtrip.md
cmp ex66000.md roundtrip.md            # identical, 66000 bytes

bin/topsailai-data file read ex66000.md --object ex66000 > read.md
cmp ex66000.md read.md                 # differs, 66000 -> 66002 bytes
```

The stored bytes are correct. `get` returns them byte for byte. Only
`file read` corrupts them, and it corrupts them on every run.

The position of the character decides the outcome:

```
U+2502 at byte 10000   -> clean
U+2502 at byte 32765   -> clean
U+2502 at byte 32766   -> corrupt (66000 -> 66002)
U+2502 at byte 40000   -> corrupt (66000 -> 66002)
U+2502 at 10000 and 40000 -> clean   (the 10000 one lands inside the sample)
```

## Root cause

`pkg/filetool/decode.go:15` bounds encoding detection to the first 32768 bytes:

```
const encodingSampleSize = 32768
```

`decodeBytes` samples only that prefix, then applies the detected decoder to the
whole buffer:

```
sample := data
if len(sample) > encodingSampleSize {
    sample = sample[:encodingSampleSize]
}
if enc := lookupEncoding(detectEncoding(sample)); enc != nil {
    decoded, _, err := transform.Bytes(enc.NewDecoder(), data)
    ...
}
```

For a pure-ASCII prefix, `chardet` returns six candidates all at confidence 10,
and `detectEncoding` breaks the tie by ascending charset name, which selects
`Big5`. Measured directly:

```
pure ascii 32768           -> UTF-8(10) Big5(10) GB-18030(10) EUC-JP(10) EUC-KR(10) Shift_JIS(10)
pipe at 32765 (in sample)  -> UTF-8(80) Big5(10) Shift_JIS(10) GB-18030(10)
pipe at 32766 (cut)        -> UTF-8(10) Shift_JIS(10) GB-18030(10) EUC-JP(10) EUC-KR(10) Big5(10)

pure-ascii sample winner: "Big5"
decode err=<nil>  len 66000 -> 66002
bytes at 40000: efbfbd efbfbd 61 61 61 61
```

The Big5 decoder turns the three UTF-8 bytes `e2 94 82` into two U+FFFD
replacement characters, which is exactly the observed 66000 -> 66002 growth.

The fallback that would have preserved the bytes is unreachable, because the
Big5 decode succeeds and returns before `utf8.Valid(data)` is consulted:

```
if enc := lookupEncoding(detectEncoding(sample)); enc != nil {
    decoded, _, err := transform.Bytes(enc.NewDecoder(), data)
    if err == nil {
        return string(decoded)      // returns here, never checks utf8.Valid
    }
}
if utf8.Valid(data) {
    return string(data)
}
```

## Impact

- Any file larger than 32 KiB whose first 32 KiB is ASCII and which contains
  non-ASCII text later is silently corrupted on read. Markdown tables, box
  drawing characters, CJK prose appended after an ASCII header, and log files
  with a late non-ASCII line are all affected.
- The corruption is not idempotent-safe: feeding the corrupted output back
  through `put` stores the corrupted bytes, because the write path is
  byte-exact. A read-modify-write cycle therefore destroys the original content
  permanently.
- This was hit in practice on
  `note--agent-cluster-deb-rebuild-and-redeploy-runbook` (66649 bytes, 18
  `U+2502` characters all after byte 58147). A read-modify-write cycle turned
  every `|` in the fleet-state table into `Ã¢ÂÂ` mojibake, and the damage was
  only noticed because the write-back was compared byte for byte.
- `get` and `put` are unaffected, so the defect is confined to the `file read`
  family (`read`, `read-lines`, `read-around`, `read-context`, `read-files`).

## Regression origin

This is a regression, not an original defect. Commit `9d971bd5` ("fix: make file
read encoding detection deterministic") replaced `chardet.DetectBest` with
`DetectAll` plus an explicit ascending-charset tie-break. Measured over 200 runs
on a pure-ASCII 32768-byte sample:

```
DetectBest (before 9d971bd5):            UTF-8 200/200
DetectAll + tie-break (after 9d971bd5):  Big5  200/200
```

The old call returned UTF-8 for an evidence-free sample, so the corruption did
not exist before that commit. Making detection deterministic removed the only
accidental protection.

## Suggested fix

A whole-buffer `utf8.Valid` guard alone is insufficient. A file that is valid
UTF-8 except for one stray invalid byte fails that guard, so detection still
runs and the valid runs are still destroyed. Measured on a 66000-byte ASCII file
with a `U+2502` at byte 40000 and one `0xFF` at byte 50000:

```
valid-utf8 + 1 invalid byte: 66001 -> 66005, pipe preserved: false
```

The fix therefore needs two rules:

1. Return the buffer unchanged when it is valid UTF-8.
2. When the detection sample is ASCII-only, decode as UTF-8 with replacement
   instead of trusting the detected charset, because an ASCII-only sample is
   compatible with every ASCII-superset encoding and carries no evidence.

Rule 2 is what covers the mixed-validity case: valid runs survive and only the
genuinely invalid bytes become `U+FFFD`. A sample carrying real non-ASCII
evidence still reaches the detected decoder, so Latin-1 and other single-byte
encodings keep working.

Both decode paths must be fixed, because they sample independently:
`decodeBytes` handles the whole-buffer path, and `openLineReader` in
`pkg/filetool/read_lines.go` handles the streaming path used by `read-lines`,
`read-around`, `read-context`, and `read-files`. The streaming reader cannot
inspect the whole buffer, so it applies rule 2 to its sample.

Regression tests should cover a `U+2502` at bytes 32765, 32766, 32767, and
40000 of a 66000-byte ASCII file, a CJK sequence past the boundary, a valid
UTF-8 file containing one stray invalid byte, and a Latin-1 file that must still
be detected as Latin-1. The existing tests in `pkg/filetool/decode_test.go` all
used short inputs, which is why none of them reached the sample boundary.

## Resolution

Fixed in `pkg/filetool/decode.go` (added `isAsciiOnly`, reordered `decodeBytes`)
and `pkg/filetool/read_lines.go` (`openLineReader` applies the ASCII-only rule).
Covered by `tests/bdd/features/encoding-fidelity.feature` (7 scenarios, 11 runs)
and new unit tests in `pkg/filetool/decode_test.go` and
`pkg/filetool/read_test.go`.

Verification: `go build ./...` clean, `go vet ./...` clean, `go test ./...`
passes, BDD suite 129 scenarios / 850 steps all passing. The live object
`note--agent-cluster-deb-rebuild-and-redeploy-runbook` now reads byte-identically
at 66649 bytes with all 18 `U+2502` characters restored and no mojibake.

Status: done.
