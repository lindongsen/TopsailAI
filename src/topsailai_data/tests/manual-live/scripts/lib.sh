#!/usr/bin/env bash
# Shared helpers for the manual/live acceptance harness.
#
# Every case runs the real compiled CLI as a subprocess against an isolated
# root, captures binary-safe stdout/stderr, and records a structured result.
# Nothing here mutates the operator's environment or the existing live store.

set -euo pipefail
# The sourcing script already resolved its own location; only derive it when
# lib.sh is executed directly, so a relative invocation cannot break the path.
if [[ -z "${EXE_FILE:-}" ]]; then
    EXE_FILE=$(readlink -f "$0")
fi
EXE_FOLDER=$(dirname "${EXE_FILE}")
SCRIPTS_DIR="${EXE_FOLDER}"
PROJECT_ROOT="$(cd "${SCRIPTS_DIR}/../../.." && pwd)"

ML_BIN="${ML_BIN:-${PROJECT_ROOT}/bin/topsailai-data}"
ML_RUN_ID="${ML_RUN_ID:-$(date +%Y%m%dT%H%M%S)}"
ML_BASE="${ML_BASE:-${PROJECT_ROOT}/.tmp/manual-live/${ML_RUN_ID}}"
ML_REPORTS="${ML_BASE}/reports"
ML_CASE_DIR="${ML_REPORTS}/cases"
ML_RESULTS="${ML_REPORTS}/results.jsonl"
ML_FIXTURES="${ML_BASE}/fixtures"
ML_STORES="${ML_BASE}/stores"
ML_ARTIFACTS="${ML_BASE}/artifacts"
ML_HOME="${ML_BASE}/home"

ML_CASE_ID=""
ML_CASE_PRIORITY=""
ML_CASE_ENV=""
ML_CASE_FAILURES=0
ML_CASE_NOTES=""
ML_CASE_BLOCKED=""

# ml_log prints a progress line to stderr so stdout stays machine-parseable.
ml_log() {
    printf '[manual-live] %s\n' "$*" >&2
}

# ml_init prepares the run directory tree and records binary identity.
ml_init() {
    mkdir -p "${ML_CASE_DIR}" "${ML_FIXTURES}" "${ML_STORES}" "${ML_ARTIFACTS}" "${ML_HOME}"
    if [[ ! -x "${ML_BIN}" ]]; then
        ml_log "binary not executable: ${ML_BIN}"
        return 1
    fi
    ML_BIN_SHA=$(sha256sum "${ML_BIN}" | awk '{print $1}')
    ML_BIN_REAL=$(readlink -f "${ML_BIN}")
    if [[ ! -f "${ML_REPORTS}/environment.json" ]]; then
        {
            printf '{\n'
            printf '  "run_id": "%s",\n' "${ML_RUN_ID}"
            printf '  "binary": "%s",\n' "${ML_BIN_REAL}"
            printf '  "binary_sha256": "%s",\n' "${ML_BIN_SHA}"
            printf '  "project_root": "%s",\n' "${PROJECT_ROOT}"
            printf '  "base": "%s",\n' "${ML_BASE}"
            printf '  "os": "%s",\n' "$(uname -srm)"
            printf '  "uid": %s,\n' "$(id -u)"
            printf '  "started_at": "%s"\n' "$(date -Is)"
            printf '}\n'
        } > "${ML_REPORTS}/environment.json"
    fi
}

# ml_case_root returns a fresh isolated store root for the current case.
ml_case_root() {
    local name="${1:-store}"
    local dir="${ML_STORES}/${ML_CASE_ID}/${name}"
    mkdir -p "${dir}"
    printf '%s' "${dir}"
}

# begin_case starts one case record.
begin_case() {
    ML_CASE_ID="$1"
    ML_CASE_PRIORITY="$2"
    ML_CASE_ENV="$3"
    ML_CASE_FAILURES=0
    ML_CASE_NOTES=""
    ML_CASE_BLOCKED=""
    ML_CASE_LOG="${ML_CASE_DIR}/${ML_CASE_ID}.log"
    : > "${ML_CASE_LOG}"
    printf '=== %s (%s, %s) ===\n' "${ML_CASE_ID}" "${ML_CASE_PRIORITY}" "${ML_CASE_ENV}" >> "${ML_CASE_LOG}"
}

# ml_note appends a free-form note to the current case log.
ml_note() {
    printf 'note: %s\n' "$*" >> "${ML_CASE_LOG}"
}

# ml_blocked marks the case as blocked by an unavailable prerequisite.
ml_blocked() {
    ML_CASE_BLOCKED="$*"
    printf 'blocked: %s\n' "$*" >> "${ML_CASE_LOG}"
}

# ml_expect compares an expected value with an actual value.
ml_expect() {
    local desc="$1" expected="$2" actual="$3"
    if [[ "${expected}" == "${actual}" ]]; then
        printf 'ok: %s\n' "${desc}" >> "${ML_CASE_LOG}"
        return 0
    fi
    ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
    printf 'FAIL: %s\n  expected: %s\n  actual:   %s\n' "${desc}" "${expected}" "${actual}" >> "${ML_CASE_LOG}"
    return 0
}

# ml_expect_contains asserts that a captured file contains a literal string.
ml_expect_contains() {
    local desc="$1" file="$2" needle="$3"
    if grep -qF -- "${needle}" "${file}"; then
        printf 'ok: %s\n' "${desc}" >> "${ML_CASE_LOG}"
        return 0
    fi
    ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
    printf 'FAIL: %s\n  missing: %s\n  in: %s\n' "${desc}" "${needle}" "${file}" >> "${ML_CASE_LOG}"
    return 0
}

# ml_expect_not_contains asserts that a captured file lacks a literal string.
ml_expect_not_contains() {
    local desc="$1" file="$2" needle="$3"
    if grep -qF -- "${needle}" "${file}"; then
        ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
        printf 'FAIL: %s\n  unexpected: %s\n  in: %s\n' "${desc}" "${needle}" "${file}" >> "${ML_CASE_LOG}"
        return 0
    fi
    printf 'ok: %s\n' "${desc}" >> "${ML_CASE_LOG}"
    return 0
}

# ml_expect_file asserts that a path exists with an optional expected type.
ml_expect_file() {
    local desc="$1" path="$2" kind="${3:-any}"
    local ok=1
    case "${kind}" in
        any) [[ -e "${path}" ]] || ok=0 ;;
        dir) [[ -d "${path}" ]] || ok=0 ;;
        file) [[ -f "${path}" ]] || ok=0 ;;
        absent) [[ ! -e "${path}" ]] || ok=0 ;;
    esac
    if [[ "${ok}" -eq 1 ]]; then
        printf 'ok: %s (%s)\n' "${desc}" "${path}" >> "${ML_CASE_LOG}"
        return 0
    fi
    ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
    printf 'FAIL: %s\n  path: %s\n  kind: %s\n' "${desc}" "${path}" "${kind}" >> "${ML_CASE_LOG}"
    return 0
}

# ml_expect_sha asserts a file digest.
ml_expect_sha() {
    local desc="$1" path="$2" expected="$3"
    local actual
    actual=$(sha256sum "${path}" | awk '{print $1}')
    ml_expect "${desc}" "${expected}" "${actual}"
}

# ml_run executes the CLI with an allowlisted environment and captures output.
#
# Usage: ml_run <root> <out-prefix> [--env K=V ...] [--stdin <file>] -- <args...>
# Returns the CLI exit code; stdout/stderr are stored next to <out-prefix>.
# --stdin feeds a file to the child's stdin so stdin-driven commands can be
# exercised without shell redirection at the call site.
ml_run() {
    local root="$1" prefix="$2"
    shift 2
    local -a extra_env=()
    local stdin_file=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --env) extra_env+=("$2"); shift 2 ;;
            --stdin) stdin_file="$2"; shift 2 ;;
            --) shift; break ;;
            *) break ;;
        esac
    done
    local -a env_args=(
        "PATH=/usr/local/bin:/usr/bin:/bin"
        "HOME=${ML_HOME}"
        "LANG=C.UTF-8"
        "LC_ALL=C.UTF-8"
        "TZ=UTC"
        "TOPSAILAI_DATA_ROOT=${root}"
    )
    local item
    for item in "${extra_env[@]+"${extra_env[@]}"}"; do
        env_args+=("${item}")
    done
    local start end code=0
    start=$(date +%s%N)
    if [[ -n "${stdin_file}" ]]; then
        env -i "${env_args[@]}" "${ML_BIN}" "$@" \
            < "${stdin_file}" > "${prefix}.stdout" 2> "${prefix}.stderr" || code=$?
    else
        env -i "${env_args[@]}" "${ML_BIN}" "$@" \
            < /dev/null > "${prefix}.stdout" 2> "${prefix}.stderr" || code=$?
    fi
    end=$(date +%s%N)
    printf '%s\n' "$*" > "${prefix}.argv"
    printf 'exit=%s elapsed_ms=%s\n' "${code}" "$(( (end - start) / 1000000 ))" > "${prefix}.meta"
    printf 'cmd: %s\n  exit=%s elapsed_ms=%s\n' "$*" "${code}" "$(( (end - start) / 1000000 ))" >> "${ML_CASE_LOG}"
    return "${code}"
}

# ml_run_ok runs the CLI and fails the case when the exit code is non-zero.
ml_run_ok() {
    local root="$1" prefix="$2"
    shift 2
    local code=0
    ml_run "${root}" "${prefix}" "$@" || code=$?
    if [[ "${code}" -ne 0 ]]; then
        ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
        printf 'FAIL: command expected success but exited %s: %s\n' "${code}" "$*" >> "${ML_CASE_LOG}"
        sed -n '1,20p' "${prefix}.stderr" >> "${ML_CASE_LOG}" || true
    fi
    return 0
}

# ml_run_fail runs the CLI and fails the case when the exit code is zero.
ml_run_fail() {
    local root="$1" prefix="$2"
    shift 2
    local code=0
    ml_run "${root}" "${prefix}" "$@" || code=$?
    if [[ "${code}" -eq 0 ]]; then
        ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
        printf 'FAIL: command expected failure but succeeded: %s\n' "$*" >> "${ML_CASE_LOG}"
    fi
    return 0
}

# end_case finalizes the case record and appends one JSON line.
end_case() {
    local status="PASS"
    if [[ -n "${ML_CASE_BLOCKED}" ]]; then
        status="BLOCKED"
    elif [[ "${ML_CASE_FAILURES}" -gt 0 ]]; then
        status="FAIL"
    fi
    printf 'status: %s failures: %s\n' "${status}" "${ML_CASE_FAILURES}" >> "${ML_CASE_LOG}"
    printf '{"case":"%s","priority":"%s","env":"%s","status":"%s","failures":%s,"blocked":"%s","log":"%s"}\n' \
        "${ML_CASE_ID}" "${ML_CASE_PRIORITY}" "${ML_CASE_ENV}" "${status}" "${ML_CASE_FAILURES}" \
        "${ML_CASE_BLOCKED}" "${ML_CASE_LOG}" >> "${ML_RESULTS}"
    printf '%-10s %-4s %s\n' "${ML_CASE_ID}" "${status}" "${ML_CASE_BLOCKED}" >&2
    ML_CASE_ID=""
}

# ml_make_markdown writes a fixture with a leading description frontmatter.
ml_make_markdown() {
    local path="$1" description="$2" body="${3:-# body}"
    mkdir -p "$(dirname "${path}")"
    {
        printf -- '---\n'
        printf 'description: %s\n' "${description}"
        printf -- '---\n\n'
        printf '%s\n' "${body}"
    } > "${path}"
}

# ml_manifest prints a stable path/size/sha256 manifest for a directory tree.
ml_manifest() {
    local dir="$1"
    ( cd "${dir}" && find . -type f -print0 | sort -z | xargs -0 -r sha256sum )
}

# ml_run_nobody executes the CLI as the unprivileged nobody user so permission
# faults are real instead of silently bypassed by root.
#
# Usage: ml_run_nobody <root> <out-prefix> [--env K=V ...] -- <args...>
ml_run_nobody() {
    local root="$1" prefix="$2"
    shift 2
    local -a extra_env=()
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --env) extra_env+=("$2"); shift 2 ;;
            --) shift; break ;;
            *) break ;;
        esac
    done
    local -a env_args=(
        "PATH=/usr/local/bin:/usr/bin:/bin"
        "HOME=${ML_HOME}"
        "LANG=C.UTF-8"
        "LC_ALL=C.UTF-8"
        "TZ=UTC"
        "TOPSAILAI_DATA_ROOT=${root}"
    )
    local item
    for item in "${extra_env[@]+"${extra_env[@]}"}"; do
        env_args+=("${item}")
    done
    local start end code=0
    start=$(date +%s%N)
    setpriv --reuid=65534 --regid=65534 --clear-groups \
        env -i "${env_args[@]}" "${ML_BIN}" "$@" > "${prefix}.stdout" 2> "${prefix}.stderr" || code=$?
    end=$(date +%s%N)
    printf '%s\n' "$*" > "${prefix}.argv"
    printf 'exit=%s elapsed_ms=%s user=nobody\n' "${code}" "$(( (end - start) / 1000000 ))" > "${prefix}.meta"
    printf 'cmd(nobody): %s\n  exit=%s elapsed_ms=%s\n' "$*" "${code}" "$(( (end - start) / 1000000 ))" >> "${ML_CASE_LOG}"
    return "${code}"
}

# ml_chown_nobody hands an isolated store to the unprivileged test user.
ml_chown_nobody() {
    chown -R 65534:65534 "$1"
}

# ml_wait_for_file blocks until a path exists or the timeout elapses.
ml_wait_for_file() {
    local path="$1" timeout="${2:-10}"
    local waited=0
    while [[ ! -e "${path}" ]]; do
        if [[ "${waited}" -ge $(( timeout * 100 )) ]]; then
            return 1
        fi
        sleep 0.01
        waited=$((waited + 1))
    done
    return 0
}

# ml_meta_dir prints the Hash metadata directory for an object ID.
ml_meta_dir() {
    local root="$1" id="$2"
    local hash
    hash=$(printf '%s' "${id}" | sha256sum | awk '{print $1}')
    printf '%s/meta/%s/%s/%s/%s' "${root}" "${hash:0:2}" "${hash:2:2}" "${hash:4:2}" "${hash}"
}

# ml_payload_dir prints the payload directory for an object ID.
ml_payload_dir() {
    local root="$1" id="$2"
    local path
    path=$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --format json 2>/dev/null \
        | jq -r --arg id "${id}" '.[] | select(.id==$id) | .path' 2>/dev/null || true)
    if [[ -z "${path}" || "${path}" == "null" ]]; then
        return 1
    fi
    printf '%s/object/%s' "${root}" "${path}"
}
