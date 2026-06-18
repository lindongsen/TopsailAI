---
status: done
created_at: 2026-06-17T17:00:00Z
resolved_at: 2026-06-17T17:00:00Z
---

# CLI `--no-color` flag still renders Unicode box-drawing borders

## Problem

The `--no-color` flag only disabled ANSI color codes but still printed Unicode box-drawing characters such as `╔═══╗`, `║`, and `╚═══╝`. This caused display issues in terminals that do not support Unicode or when plain ASCII output is desired.

## Root Cause

Box-drawing characters were hard-coded in:
- `printBanner()`
- `printSeparator()`
- `printDoubleSeparator()`
- `printableSeparator()`

These functions did not check the global `noColor` state.

## Fix

Updated `cmd/cli/display.go`:
- Added `boxHorizontal()` and `boxDoubleHorizontal()` helpers that return ASCII `-`/`=` when `noColor` is true, otherwise Unicode `─`/`═`.
- Updated `bannerBorder()` to return ASCII `+---+` and `|` borders when `noColor` is true.
- Updated `printBanner()`, `printSeparator()`, `printDoubleSeparator()`, and `printableSeparator()` to use the new helpers.

Updated `cmd/cli/display_test.go`:
- Added tests for `boxHorizontal()`, `boxDoubleHorizontal()`, `bannerBorder()`, and `printableSeparator()` in both color and no-color modes.

## Verification

- `go test ./cmd/cli` passes.
- `go build -o /tmp/acs-cli ./cmd/cli` succeeds.
- Running `/tmp/acs-cli --no-color` shows the banner with ASCII borders only:
  ```
  +------------------------------------------+
  |     ACS CLI Terminal                     |
  +------------------------------------------+
  ```

## Files Changed

- `cmd/cli/display.go`
- `cmd/cli/display_test.go`
