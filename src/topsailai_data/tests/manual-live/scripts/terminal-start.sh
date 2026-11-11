#!/usr/bin/env bash
# terminal-start.sh launches the CLI in a real terminal and reports readiness.
#
# This script owns exactly one responsibility: start the program and expose
# either readiness or a startup failure. It never sends keystrokes, never
# asserts business output and never cleans up. Interaction lives in
# terminal-interact.sh so a startup problem and an interaction problem can be
# diagnosed separately.
#
# The CLI has no interactive REPL: invoked without a command it prints usage and
# exits. "Readiness" therefore means the binary answered a probe command inside
# the terminal, which proves the process started, the store opened and the
# terminal plumbing works.
#
# Usage:
#   terminal-start.sh --root <dir> [--bin <path>] [--session <name>]
#                     [--probe <command>] [--timeout <seconds>] [--ready <file>]
#                     [--help]
#
# Exit codes:
#   0  the probe command completed inside the terminal
#   1  startup failed or the probe timed out
#   2  invalid arguments
#   3  the requested root is inside the protected recovery backup

set -uo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
SCRIPTS_DIR="${EXE_FOLDER}"
PROJECT_ROOT="$(cd "${SCRIPTS_DIR}/../../.." && pwd)"

# shellcheck source=lib.sh
source "${SCRIPTS_DIR}/lib.sh"

# lib.sh enables "set -e" for the case scripts. This launcher must inspect a
# failed probe instead of aborting on it, so errexit is dropped again here.
set +e
set -uo pipefail

# PROTECTED_BACKUP is the recovery evidence that must never be mutated.
PROTECTED_BACKUP="${PROJECT_ROOT}/.tmp/data-recovery/20261111125501/original"

ROOT=""
BIN="${ML_BIN}"
SESSION=""
PROBE="list"
TIMEOUT=20
READY=""

usage() {
    cat <<'EOF'
terminal-start.sh launches the CLI in a real terminal and reports readiness.

Usage:
  terminal-start.sh --root <dir> [options]

Options:
  --root <dir>        store root used by the launched process (required)
  --bin <path>        CLI binary (default: <project>/bin/topsailai-data)
  --session <name>    tmux session name (default: ml-terminal-<pid>)
  --probe <command>   command run inside the terminal to prove readiness
                      (default: list)
  --timeout <sec>     readiness timeout in seconds (default: 20)
  --ready <file>      write the session name here once ready
  --help              show this help

Exit codes: 0 ready, 1 startup failed, 2 invalid arguments, 3 protected root.
EOF
}

# refuse_protected rejects the recovery backup and anything inside it.
#
# Both paths are resolved first so a symlink or a ".." segment cannot smuggle
# the backup path past a plain string comparison.
refuse_protected() {
    local target="$1"
    local real_target real_backup
    real_target=$(readlink -f "${target}" 2>/dev/null || printf '%s' "${target}")
    real_backup=$(readlink -f "${PROTECTED_BACKUP}" 2>/dev/null || printf '%s' "${PROTECTED_BACKUP}")
    case "${real_target}" in
        "${real_backup}"|"${real_backup}"/*)
            printf 'error: refusing to start a terminal against the protected recovery backup: %s\n' "${real_target}" >&2
            printf 'error: copy the store first and pass the copy as --root\n' >&2
            return 1
            ;;
    esac
    return 0
}

# parse_args reads the documented options and rejects unknown input.
parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --root) ROOT="${2:-}"; shift 2 ;;
            --bin) BIN="${2:-}"; shift 2 ;;
            --session) SESSION="${2:-}"; shift 2 ;;
            --probe) PROBE="${2:-}"; shift 2 ;;
            --timeout) TIMEOUT="${2:-}"; shift 2 ;;
            --ready) READY="${2:-}"; shift 2 ;;
            --help|-h) usage; exit 0 ;;
            *)
                printf 'error: unknown argument: %s\n' "$1" >&2
                usage >&2
                exit 2
                ;;
        esac
    done

    if [[ -z "${ROOT}" ]]; then
        printf 'error: --root is required\n' >&2
        exit 2
    fi
    if [[ ! -d "${ROOT}" ]]; then
        printf 'error: root directory does not exist: %s\n' "${ROOT}" >&2
        exit 2
    fi
    if [[ ! -x "${BIN}" ]]; then
        printf 'error: binary is not executable: %s\n' "${BIN}" >&2
        exit 2
    fi
    if ! [[ "${TIMEOUT}" =~ ^[0-9]+$ ]] || [[ "${TIMEOUT}" -le 0 ]]; then
        printf 'error: --timeout must be a positive integer: %s\n' "${TIMEOUT}" >&2
        exit 2
    fi
    if [[ -z "${SESSION}" ]]; then
        SESSION="ml-terminal-$$"
    fi
}

# session_exists reports whether the named tmux session is alive.
session_exists() {
    tmux has-session -t "$1" 2>/dev/null
}

# kill_own_session stops only the session this script created.
#
# The session name is owned by this process, so no broad process-name matching
# is used and no unrelated terminal is affected.
kill_own_session() {
    local name="$1"
    if session_exists "${name}"; then
        tmux kill-session -t "${name}" 2>/dev/null
        printf 'terminal: session %s stopped\n' "${name}"
    fi
}

# start_session creates a detached session and runs the probe command.
start_session() {
    local name="$1"
    if session_exists "${name}"; then
        printf 'error: session already exists: %s\n' "${name}" >&2
        return 1
    fi
    if ! tmux new-session -d -s "${name}" -x 120 -y 40 2>/dev/null; then
        printf 'error: cannot create tmux session: %s\n' "${name}" >&2
        return 1
    fi
    # The probe runs with stat tracking disabled so a readiness check never
    # mutates usage statistics in the store under test.
    #
    # The marker is assembled from two adjacent quoted strings so the literal
    # "PROBEDONE:" never appears in the echoed command line. A plain marker such
    # as "__PROBE_EXIT=$?" would be matched by the readiness poll on the echo
    # itself, before the probe had run, and the captured exit status would be
    # empty.
    tmux send-keys -t "${name}" \
        "cd $(printf '%q' "${PROJECT_ROOT}") && TOPSAILAI_DATA_ROOT=$(printf '%q' "${ROOT}") TOPSAILAI_DATA_TRACK_STAT=0 $(printf '%q' "${BIN}") ${PROBE}; echo \"PROBE\"\"DONE:\$?\"" C-m
    return 0
}

# wait_ready polls the pane until the probe reports its exit status.
#
# The marker line is produced by the shell inside the terminal, so seeing it
# proves the process actually ran rather than merely being scheduled. The
# pattern requires at least one digit, so an empty marker can never be accepted
# as a successful probe.
wait_ready() {
    local name="$1" waited=0 pane
    while [[ "${waited}" -lt $((TIMEOUT * 10)) ]]; do
        pane=$(tmux capture-pane -p -t "${name}" 2>/dev/null)
        if printf '%s' "${pane}" | grep -q 'PROBEDONE:[0-9]'; then
            printf '%s' "${pane}" | grep -o 'PROBEDONE:[0-9][0-9]*' | tail -1
            return 0
        fi
        sleep 0.1
        waited=$((waited + 1))
    done
    return 1
}

main() {
    parse_args "$@"

    if ! refuse_protected "${ROOT}"; then
        exit 3
    fi

    if ! command -v tmux >/dev/null 2>&1; then
        printf 'error: tmux is required to run a terminal test\n' >&2
        exit 1
    fi

    if ! start_session "${SESSION}"; then
        exit 1
    fi

    local marker
    if ! marker=$(wait_ready "${SESSION}"); then
        printf 'error: terminal did not become ready within %ss\n' "${TIMEOUT}" >&2
        printf 'terminal: last pane content follows\n' >&2
        tmux capture-pane -p -t "${SESSION}" 2>/dev/null | tail -20 >&2
        kill_own_session "${SESSION}"
        exit 1
    fi

    printf 'terminal: session %s ready\n' "${SESSION}"
    printf 'terminal: probe exit %s\n' "${marker#PROBEDONE:}"

    if [[ -n "${READY}" ]]; then
        mkdir -p "$(dirname "${READY}")"
        printf '%s\n' "${SESSION}" > "${READY}"
        printf 'terminal: ready file written to %s\n' "${READY}"
    fi

    # The session is intentionally left running: terminal-interact.sh drives it
    # and terminal-interact.sh stop owns the shutdown.
    exit 0
}

main "$@"
