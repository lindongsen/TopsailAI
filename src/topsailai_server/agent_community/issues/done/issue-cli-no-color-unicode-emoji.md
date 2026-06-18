# Issue: --no-color flag still emits Unicode emoji characters

## Status

fixed

## Description

The `--no-color` CLI flag disabled ANSI color codes and Unicode box-drawing
characters, but event labels still contained Unicode emoji such as `🤖`, `📢`,
`👤`, and `📰`. This caused rendering issues on terminals without emoji/font
support and was inconsistent with the plain-ASCII expectation of `--no-color`.

## Affected code

- `cmd/cli/display.go`
  - `formatMessage`
  - `formatGroupEvent`
  - `formatMemberEvent`
  - `formatGenericEvent`

## Fix

Added icon helper functions (`agentIcon`, `eventIcon`, `memberIcon`,
`genericEventIcon`) that return plain ASCII labels when `noColor` is enabled
and Unicode emoji otherwise. Updated all event/message formatters to use the
helpers.

## Verification

- `go test ./cmd/cli` passes.
- `go build -o /tmp/acs-cli ./cmd/cli` succeeds.
- Running `/tmp/acs-cli --no-color` no longer prints Unicode emoji in event
  labels; they are replaced with `[BOT]`, `[EVENT]`, and `[MEMBER]`.
