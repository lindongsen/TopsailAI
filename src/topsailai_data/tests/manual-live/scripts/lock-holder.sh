#!/usr/bin/env bash
# Lock holder for the manual/live acceptance harness.
#
# The harness needs a process that provably holds an advisory flock while a case
# runs, so lock contention is deterministic instead of a race between CLI
# processes. This script is that holder. It never touches the store itself: it
# only opens the lock path the caller names.
#
# Usage:
#   lock-holder.sh hold    --lock <path> --ready <file> [--pidfile <file>] [--timeout <s>]
#   lock-holder.sh release --ready <file> [--pidfile <file>] [--timeout <s>]
#   lock-holder.sh probe   --lock <path>
#   lock-holder.sh --help
#
# The caller MUST launch "hold" as a background job and capture the PID with $!:
#
#   lock-holder.sh hold --lock "${lock}" --ready "${ready}" --pidfile "${pidfile}" &
#   HOLDER_PID=$!
#   lock-holder.sh wait-ready --ready "${ready}" --timeout 10
#
# Do NOT wrap "hold" in a command substitution such as holder=$(... hold ...).
# A command substitution runs the callee in a subshell, and the subshell exit
# tears down the background holder it started, which silently releases the lock
# and makes every contention assertion pass for the wrong reason.
#
# Three pitfalls are deliberately avoided here:
#   1. "local" is never used inside a background subshell, because a subshell is
#      not a function scope and "local" aborts the holder under "set -e".
#   2. The holder PID is never returned through a command substitution, for the
#      reason stated above.
#   3. Counting never uses "grep | wc -l", because "pipefail" turns a no-match
#      grep into a failed pipeline that "set -e" silently aborts on.

set -euo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
PROJECT_ROOT="$(cd "${EXE_FOLDER}/../../.." && pwd)"

# PROTECTED_BACKUP is the recovery evidence that must never be mutated.
PROTECTED_BACKUP="${PROJECT_ROOT}/.tmp/data-recovery/20261111125501/original"

DEFAULT_TIMEOUT=30

usage() {
    cat <<'USAGE'
lock-holder.sh - hold an advisory flock for manual/live lock-contention cases

Subcommands:
  hold     Acquire an exclusive flock, publish a ready file, then block until
           the ready file is removed or the timeout expires.
  release  Remove the ready file and wait for the holder to exit.
  probe    Report whether a lock path is currently held.
  wait-ready
           Block until a ready file appears.

Options:
  --lock <path>      Lock file to open and flock. Required by hold and probe.
  --ready <file>     Ready file that signals the lock is held. Required by hold,
                     release and wait-ready.
  --pidfile <file>   File where hold records its own PID. Recommended so that
                     release can reap the holder without the caller passing it.
  --timeout <s>      Seconds to wait. Default 30.
  --help             Print this text.

Exit codes:
  0  success
  1  timeout or runtime failure
  2  invalid arguments
  3  refused because the path is inside the protected recovery backup

Example:
  lock-holder.sh hold --lock "${lock}" --ready "${ready}" --pidfile "${pid}" &
  HOLDER_PID=$!
  lock-holder.sh wait-ready --ready "${ready}" --timeout 10
  lock-holder.sh probe --lock "${lock}"        # prints "held"
  lock-holder.sh release --ready "${ready}" --pidfile "${pid}"
  lock-holder.sh probe --lock "${lock}"        # prints "free"
USAGE
}

# refuse_protected rejects the recovery backup and anything inside it.
#
# Both paths are resolved first, so a symlink or a ".." segment cannot smuggle
# the backup path past a plain string comparison.
refuse_protected() {
    local target="$1"
    local real_target real_backup
    real_target=$(readlink -f "${target}" 2>/dev/null || printf '%s' "${target}")
    real_backup=$(readlink -f "${PROTECTED_BACKUP}" 2>/dev/null || printf '%s' "${PROTECTED_BACKUP}")
    case "${real_target}" in
        "${real_backup}"|"${real_backup}"/*)
            printf 'error: refusing to lock inside the protected recovery backup: %s\n' "${real_target}" >&2
            printf 'error: copy the store first and pass the copy as --lock\n' >&2
            return 1
            ;;
    esac
    return 0
}

# cmd_hold acquires the lock and blocks until the ready file disappears.
#
# The ready file is created only after flock succeeds, so its presence is proof
# that the lock is held rather than a guess based on a sleep duration.
cmd_hold() {
    local lock="" ready="" pidfile="" timeout="${DEFAULT_TIMEOUT}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --lock) lock="$2"; shift 2 ;;
            --ready) ready="$2"; shift 2 ;;
            --pidfile) pidfile="$2"; shift 2 ;;
            --timeout) timeout="$2"; shift 2 ;;
            *) printf 'error: unknown option for hold: %s\n' "$1" >&2; return 2 ;;
        esac
    done
    if [[ -z "${lock}" || -z "${ready}" ]]; then
        printf 'error: hold requires --lock and --ready\n' >&2
        return 2
    fi
    if ! refuse_protected "${lock}"; then
        return 3
    fi

    mkdir -p "$(dirname "${lock}")" "$(dirname "${ready}")"
    rm -f "${ready}"

    # File descriptor 9 carries the lock for the whole lifetime of this process.
    exec 9>"${lock}" || { printf 'error: cannot open lock file: %s\n' "${lock}" >&2; return 1; }
    if ! flock -x -w "${timeout}" 9; then
        printf 'holder: timeout after %ss waiting for %s\n' "${timeout}" "${lock}" >&2
        return 1
    fi

    if [[ -n "${pidfile}" ]]; then
        mkdir -p "$(dirname "${pidfile}")"
        printf '%s\n' "$$" > "${pidfile}"
    fi
    : > "${ready}"

    # Block until the caller removes the ready file. The bounded wait keeps a
    # crashed caller from leaving an orphan holder behind forever.
    local waited=0
    local limit=$(( timeout * 100 ))
    while [[ -e "${ready}" ]]; do
        if [[ "${waited}" -ge "${limit}" ]]; then
            printf 'holder: ready file was not removed within %ss\n' "${timeout}" >&2
            break
        fi
        sleep 0.01
        waited=$((waited + 1))
    done

    rm -f "${pidfile}"
    return 0
}

# cmd_release removes the ready file and waits for the holder to exit.
cmd_release() {
    local ready="" pidfile="" timeout="${DEFAULT_TIMEOUT}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --ready) ready="$2"; shift 2 ;;
            --pidfile) pidfile="$2"; shift 2 ;;
            --timeout) timeout="$2"; shift 2 ;;
            *) printf 'error: unknown option for release: %s\n' "$1" >&2; return 2 ;;
        esac
    done
    if [[ -z "${ready}" ]]; then
        printf 'error: release requires --ready\n' >&2
        return 2
    fi

    rm -f "${ready}"
    if [[ -z "${pidfile}" || ! -f "${pidfile}" ]]; then
        printf 'release: no pidfile, the holder is expected to exit on its own\n'
        return 0
    fi

    local pid
    pid=$(cat "${pidfile}")
    local waited=0
    local limit=$(( timeout * 100 ))
    while kill -0 "${pid}" 2>/dev/null; do
        if [[ "${waited}" -ge "${limit}" ]]; then
            printf 'error: holder %s is still alive after %ss\n' "${pid}" "${timeout}" >&2
            return 1
        fi
        sleep 0.01
        waited=$((waited + 1))
    done
    rm -f "${pidfile}"
    printf 'release: holder %s exited\n' "${pid}"
    return 0
}

# cmd_probe reports whether a lock path is currently held.
#
# "flock -n" opens the file itself and fails immediately when another process
# holds the lock, so the probe never blocks and never creates a stale holder.
cmd_probe() {
    local lock=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --lock) lock="$2"; shift 2 ;;
            *) printf 'error: unknown option for probe: %s\n' "$1" >&2; return 2 ;;
        esac
    done
    if [[ -z "${lock}" ]]; then
        printf 'error: probe requires --lock\n' >&2
        return 2
    fi
    if [[ ! -e "${lock}" ]]; then
        printf 'free\n'
        return 0
    fi
    if flock -n -x "${lock}" true 2>/dev/null; then
        printf 'free\n'
    else
        printf 'held\n'
    fi
    return 0
}

# cmd_wait_ready blocks until a ready file appears.
cmd_wait_ready() {
    local ready="" timeout="${DEFAULT_TIMEOUT}"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --ready) ready="$2"; shift 2 ;;
            --timeout) timeout="$2"; shift 2 ;;
            *) printf 'error: unknown option for wait-ready: %s\n' "$1" >&2; return 2 ;;
        esac
    done
    if [[ -z "${ready}" ]]; then
        printf 'error: wait-ready requires --ready\n' >&2
        return 2
    fi
    local waited=0
    local limit=$(( timeout * 100 ))
    while [[ ! -e "${ready}" ]]; do
        if [[ "${waited}" -ge "${limit}" ]]; then
            printf 'error: ready file did not appear within %ss: %s\n' "${timeout}" "${ready}" >&2
            return 1
        fi
        sleep 0.01
        waited=$((waited + 1))
    done
    return 0
}

main() {
    if [[ $# -eq 0 ]]; then
        usage >&2
        return 2
    fi
    local command="$1"
    shift
    case "${command}" in
        hold) cmd_hold "$@" ;;
        release) cmd_release "$@" ;;
        probe) cmd_probe "$@" ;;
        wait-ready) cmd_wait_ready "$@" ;;
        --help|-h|help) usage; return 0 ;;
        *)
            printf 'error: unknown subcommand: %s\n' "${command}" >&2
            usage >&2
            return 2
            ;;
    esac
}

main "$@"
