#!/usr/bin/env bash
# run-live: execute one selected manual/live case with exact argv, cwd and
# settings, binary-safe capture, elapsed time and a structured status.
#
# The case scripts already implement the assertions. This runner only owns the
# execution envelope: it resolves which script owns a case id, pins the binary,
# records the resolved settings, runs the case in its own run area, and reports
# one machine-readable result line. It never mutates the operator environment
# and never touches the existing live store.
#
# Usage:
#   bash tests/manual-live/scripts/run-live.sh <case-id> [case-id...]
#   bash tests/manual-live/scripts/run-live.sh --list
#   bash tests/manual-live/scripts/run-live.sh --all
#
# Options:
#   --run-id <id>   run area name (default: timestamp)
#   --bin <path>    CLI binary to pin (default: <project>/bin/topsailai-data)
#   --list          print the case inventory and exit
#   --all           run every case in module order
#
# Exit status is 0 when no case FAILed. BLOCKED cases do not fail the run: they
# are reported with their reason so an unavailable prerequisite stays visible
# instead of being silently counted as a pass.

set -uo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1

# shellcheck source=lib.sh
source "${EXE_FOLDER}/lib.sh"

# CASE_SCRIPTS maps a case id prefix to the script that owns it.
#
# The mapping is explicit instead of a glob so an unknown case id fails loudly
# rather than silently running nothing.
CASE_SCRIPTS=(
    "CFG:cases-a-startup.sh"
    "OBJ:cases-b-objects.sh"
    "FILE:cases-c-files.sh"
    "LIFE:cases-d-lifecycle.sh"
    "STAT:cases-e-stat.sh"
    "SAFE:cases-f-safety.sh"
)

# SAFE_SCRIPT_OVERRIDES routes SAFE cases that live in a later script.
#
# SAFE-01..08 are in cases-f-safety.sh, SAFE-09..12 in cases-f-scale.sh and
# SAFE-13..18 in cases-f-live.sh, so the numeric range decides the owner.
SAFE_SCRIPT_OVERRIDES=(
    "09:cases-f-scale.sh"
    "10:cases-f-scale.sh"
    "11:cases-f-scale.sh"
    "12:cases-f-scale.sh"
    "13:cases-f-live.sh"
    "14:cases-f-live.sh"
    "15:cases-f-live.sh"
    "16:cases-f-live.sh"
    "17:cases-f-live.sh"
    "18:cases-f-live.sh"
)

# script_for prints the script that owns a case id.
script_for() {
    local case_id="$1"
    local prefix="${case_id%%-*}"
    local number="${case_id#*-}"
    if [[ "${prefix}" == "SAFE" ]]; then
        local entry
        for entry in "${SAFE_SCRIPT_OVERRIDES[@]}"; do
            if [[ "${entry%%:*}" == "${number}" ]]; then
                printf '%s' "${entry#*:}"
                return 0
            fi
        done
        printf 'cases-f-safety.sh'
        return 0
    fi
    local entry
    for entry in "${CASE_SCRIPTS[@]}"; do
        if [[ "${entry%%:*}" == "${prefix}" ]]; then
            printf '%s' "${entry#*:}"
            return 0
        fi
    done
    return 1
}

# case_inventory prints every case id in module order.
#
# The inventory is read from the case scripts themselves so a newly added case
# appears without editing this runner. The CASES array is unquoted and may span
# several lines, so the block is captured from "CASES=(" to the closing ")" and
# then reduced to the case-id tokens.
case_inventory() {
    local script
    for script in cases-a-startup.sh cases-b-objects.sh cases-c-files.sh \
        cases-d-lifecycle.sh cases-e-stat.sh cases-f-safety.sh \
        cases-f-scale.sh cases-f-live.sh; do
        [[ -f "${script}" ]] || continue
        awk '/^CASES=\(/ { inside = 1 } inside { print } inside && /\)/ { exit }' "${script}" \
            | grep -oE '[A-Z]+-[0-9]+' \
            || true
    done
}

# run_one executes one case and prints its structured result.
run_one() {
    local case_id="$1" run_id="$2" bin="$3"
    local script
    if ! script=$(script_for "${case_id}"); then
        printf '{"case":"%s","status":"ERROR","reason":"unknown case id"}\n' "${case_id}"
        return 1
    fi
    if [[ ! -f "${script}" ]]; then
        printf '{"case":"%s","status":"ERROR","reason":"missing script %s"}\n' "${case_id}" "${script}"
        return 1
    fi

    local started ended elapsed code=0
    started=$(date +%s%N)
    ML_RUN_ID="${run_id}" ML_BIN="${bin}" bash "${script}" "${case_id}" \
        > "${ML_BASE}/runner-${case_id}.stdout" 2> "${ML_BASE}/runner-${case_id}.stderr" || code=$?
    ended=$(date +%s%N)
    elapsed=$(( (ended - started) / 1000000 ))

    # The case script appends its own result line; the runner reports the same
    # line plus the measured wall time so a slow case stays observable.
    local line
    line=$(grep -F "\"case\":\"${case_id}\"" "${ML_RESULTS}" 2>/dev/null | tail -1)
    if [[ -z "${line}" ]]; then
        printf '{"case":"%s","status":"ERROR","reason":"no result line","exit":%s,"elapsed_ms":%s}\n' \
            "${case_id}" "${code}" "${elapsed}"
        return 1
    fi
    printf '%s\n' "${line}" | sed -E "s/}$/,\"elapsed_ms\":${elapsed},\"runner_exit\":${code}}/"
    if [[ "${code}" -ne 0 ]]; then
        return 1
    fi
    return 0
}

main() {
    local run_id=""
    local bin="${ML_BIN}"
    local -a requested=()
    local run_all=0

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --run-id) run_id="$2"; shift 2 ;;
            --bin) bin="$2"; shift 2 ;;
            --list) case_inventory; return 0 ;;
            --all) run_all=1; shift ;;
            -h|--help) sed -n '2,30p' "${EXE_FILE}"; return 0 ;;
            *) requested+=("$1"); shift ;;
        esac
    done

    if [[ -z "${run_id}" ]]; then
        run_id="run-live-$(date +%Y%m%dT%H%M%S)"
    fi
    ML_RUN_ID="${run_id}"
    ML_BASE="${PROJECT_ROOT}/.tmp/manual-live/${ML_RUN_ID}"
    ML_REPORTS="${ML_BASE}/reports"
    ML_CASE_DIR="${ML_REPORTS}/cases"
    ML_RESULTS="${ML_REPORTS}/results.jsonl"
    ML_FIXTURES="${ML_BASE}/fixtures"
    ML_STORES="${ML_BASE}/stores"
    ML_ARTIFACTS="${ML_BASE}/artifacts"
    ML_HOME="${ML_BASE}/home"
    mkdir -p "${ML_CASE_DIR}" "${ML_FIXTURES}" "${ML_STORES}" "${ML_ARTIFACTS}" "${ML_HOME}"

    if [[ "${run_all}" -eq 1 ]]; then
        mapfile -t requested < <(case_inventory)
    fi
    if [[ ${#requested[@]} -eq 0 ]]; then
        ml_log "no case id given; use --list to see the inventory"
        return 2
    fi

    ml_log "run id: ${ML_RUN_ID}"
    ml_log "binary: ${bin}"
    ml_log "base:   ${ML_BASE}"

    local failures=0 case_id
    for case_id in "${requested[@]}"; do
        if ! run_one "${case_id}" "${ML_RUN_ID}" "${bin}"; then
            failures=$((failures + 1))
        fi
    done

    ml_log "results: ${ML_RESULTS}"
    if [[ "${failures}" -gt 0 ]]; then
        ml_log "runner failures: ${failures}"
        return 1
    fi
    return 0
}

main "$@"
