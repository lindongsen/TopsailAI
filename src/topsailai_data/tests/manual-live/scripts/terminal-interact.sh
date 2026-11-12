#!/usr/bin/env bash
# terminal-interact.sh drives an existing terminal session and captures evidence.
#
# This script owns exactly one responsibility: create or reuse a tmux session,
# send keystrokes, wait for observable output and capture the pane. It never
# starts the service, never asserts business correctness and never cleans up the
# store. Startup lives in terminal-start.sh so a startup failure and an
# interaction failure stay distinguishable.
#
# Usage:
#   terminal-interact.sh send --session <name> --keys <text> [--timeout <sec>]
#   terminal-interact.sh expect --session <name> --text <text> [--timeout <sec>]
#   terminal-interact.sh capture --session <name> [--out <file>]
#   terminal-interact.sh stop --session <name>
#   terminal-interact.sh --help
#
# Exit codes:
#   0  the requested action succeeded
#   1  the expected text never appeared, or the session is missing
#   2  invalid arguments

set -uo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
SCRIPTS_DIR="${EXE_FOLDER}"

# shellcheck source=lib.sh
source "${SCRIPTS_DIR}/lib.sh"

# lib.sh enables "set -e" for the case scripts. This driver must inspect a
# missing expectation instead of aborting on it, so errexit is dropped again.
set +e
set -uo pipefail

usage() {
    cat <<'EOF'
terminal-interact.sh drives an existing terminal session and captures evidence.

Usage:
  terminal-interact.sh send    --session <name> --keys <text> [--timeout <sec>]
  terminal-interact.sh expect  --session <name> --text <text> [--timeout <sec>]
  terminal-interact.sh capture --session <name> [--out <file>]
  terminal-interact.sh stop    --session <name>
  terminal-interact.sh --help

Options:
  --session <name>   tmux session to drive (required)
  --keys <text>      keystrokes to send; Enter is appended unless --no-enter
  --no-enter         send the keys without a trailing Enter
  --text <text>      literal text that must appear in the pane
  --timeout <sec>    wait timeout in seconds (default: 10)
  --out <file>       write the captured pane to this file

Exit codes: 0 success, 1 expectation not met or session missing, 2 invalid args.
EOF
}

ACTION=""
SESSION=""
KEYS=""
TEXT=""
TIMEOUT=10
OUT=""
APPEND_ENTER=1

# parse_args reads the documented options and rejects unknown input.
parse_args() {
    if [[ $# -eq 0 ]]; then
        printf 'error: an action is required\n' >&2
        usage >&2
        exit 2
    fi
    case "$1" in
        send|expect|capture|stop) ACTION="$1"; shift ;;
        --help|-h) usage; exit 0 ;;
        *)
            printf 'error: unknown action: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --session) SESSION="${2:-}"; shift 2 ;;
            --keys) KEYS="${2:-}"; shift 2 ;;
            --text) TEXT="${2:-}"; shift 2 ;;
            --timeout) TIMEOUT="${2:-}"; shift 2 ;;
            --out) OUT="${2:-}"; shift 2 ;;
            --no-enter) APPEND_ENTER=0; shift ;;
            --help|-h) usage; exit 0 ;;
            *)
                printf 'error: unknown argument: %s\n' "$1" >&2
                usage >&2
                exit 2
                ;;
        esac
    done

    if [[ -z "${SESSION}" ]]; then
        printf 'error: --session is required\n' >&2
        exit 2
    fi
    if ! [[ "${TIMEOUT}" =~ ^[0-9]+$ ]] || [[ "${TIMEOUT}" -le 0 ]]; then
        printf 'error: --timeout must be a positive integer: %s\n' "${TIMEOUT}" >&2
        exit 2
    fi
    case "${ACTION}" in
        send)
            if [[ -z "${KEYS}" ]]; then
                printf 'error: send requires --keys\n' >&2
                exit 2
            fi
            ;;
        expect)
            if [[ -z "${TEXT}" ]]; then
                printf 'error: expect requires --text\n' >&2
                exit 2
            fi
            ;;
    esac
}

# session_exists reports whether the named tmux session is alive.
session_exists() {
    tmux has-session -t "$1" 2>/dev/null
}

# require_session fails fast when the session is gone.
#
# A missing session is reported instead of being recreated, because recreating
# it would hide the fact that the program under test already exited.
require_session() {
    if ! session_exists "$1"; then
        printf 'error: session not found: %s\n' "$1" >&2
        return 1
    fi
    return 0
}

# do_send types the keys into the session.
do_send() {
    require_session "${SESSION}" || return 1
    if [[ "${APPEND_ENTER}" -eq 1 ]]; then
        tmux send-keys -t "${SESSION}" "${KEYS}" C-m
    else
        tmux send-keys -t "${SESSION}" "${KEYS}"
    fi
    printf 'interact: sent keys to %s\n' "${SESSION}"
}

# do_expect waits until the literal text appears in the pane.
#
# The comparison is a literal substring match, so a regex metacharacter in the
# expected text cannot accidentally match unrelated output.
do_expect() {
    require_session "${SESSION}" || return 1
    local waited=0 pane
    while [[ "${waited}" -lt $((TIMEOUT * 10)) ]]; do
        pane=$(tmux capture-pane -p -t "${SESSION}" 2>/dev/null)
        if printf '%s' "${pane}" | grep -Fq -- "${TEXT}"; then
            printf 'interact: found expected text in %s\n' "${SESSION}"
            return 0
        fi
        sleep 0.1
        waited=$((waited + 1))
    done
    printf 'error: expected text did not appear within %ss: %s\n' "${TIMEOUT}" "${TEXT}" >&2
    printf 'interact: last pane content follows\n' >&2
    tmux capture-pane -p -t "${SESSION}" 2>/dev/null | tail -20 >&2
    return 1
}

# do_capture writes the current pane content to a file or stdout.
do_capture() {
    require_session "${SESSION}" || return 1
    if [[ -n "${OUT}" ]]; then
        mkdir -p "$(dirname "${OUT}")"
        tmux capture-pane -p -t "${SESSION}" > "${OUT}" 2>/dev/null
        printf 'interact: captured %s to %s\n' "${SESSION}" "${OUT}"
    else
        tmux capture-pane -p -t "${SESSION}" 2>/dev/null
    fi
}

# do_stop stops only the named session.
#
# The session name is supplied by the caller and owned by this test, so no
# broad process-name matching is used and no unrelated terminal is affected.
do_stop() {
    if ! session_exists "${SESSION}"; then
        printf 'interact: session already gone: %s\n' "${SESSION}"
        return 0
    fi
    tmux kill-session -t "${SESSION}" 2>/dev/null
    printf 'interact: session %s stopped\n' "${SESSION}"
    if session_exists "${SESSION}"; then
        printf 'error: session still alive after stop: %s\n' "${SESSION}" >&2
        return 1
    fi
    return 0
}

main() {
    parse_args "$@"

    if ! command -v tmux >/dev/null 2>&1; then
        printf 'error: tmux is required to run a terminal test\n' >&2
        exit 1
    fi

    case "${ACTION}" in
        send) do_send || exit 1 ;;
        expect) do_expect || exit 1 ;;
        capture) do_capture || exit 1 ;;
        stop) do_stop || exit 1 ;;
    esac
    exit 0
}

main "$@"
