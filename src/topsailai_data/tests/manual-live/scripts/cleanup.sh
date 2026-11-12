#!/usr/bin/env bash
#
# cleanup.sh removes only the resources this test harness created.
#
# The harness writes stores, artifacts and probe directories under .tmp/ and
# /tmp. Those grow without bound across runs, so a bounded cleanup is required.
# The script is deliberately narrow: it never removes project source, never
# removes another task's .tmp directory, and it hard-refuses the protected
# recovery backup.
#
# Safety rules enforced here:
#   1. The protected recovery backup is refused after resolving symlinks, so a
#      symlink or a ".." segment cannot smuggle it past the check.
#   2. Every removal prints "deleted: <path>" so the action is auditable.
#   3. --dry-run prints the plan and removes nothing.
#   4. reports/ is preserved by default because the execution report is built
#      from results.jsonl; --purge-reports removes it explicitly.
#   5. After removal the backup file count is re-checked against the recorded
#      baseline, so an accidental backup deletion cannot pass silently.
#
# Usage:
#   cleanup.sh --dry-run
#   cleanup.sh
#   cleanup.sh --purge-reports
#   cleanup.sh --help
#
# Exit codes: 0 success, 1 verification failure, 2 invalid arguments,
#             3 protected path refused.

set -uo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
PROJECT_ROOT=$(dirname "$(dirname "$(dirname "${EXE_FOLDER}")")")

# PROTECTED_BACKUP is the recovery evidence that must never be mutated.
PROTECTED_BACKUP="${PROJECT_ROOT}/.tmp/data-recovery/20261111125501/original"

# BASELINE_BACKUP_FILES is the recorded file count of the protected backup.
BASELINE_BACKUP_FILES=782

DRY_RUN=0
PURGE_REPORTS=0

usage() {
    cat <<'EOF'
cleanup.sh removes only the resources created by the manual/live harness.

Usage:
  cleanup.sh [--dry-run] [--purge-reports] [--help]

Options:
  --dry-run        Print the removal plan and remove nothing.
  --purge-reports  Also remove reports/ inside each run directory. By default
                   reports/ is preserved because the execution report is built
                   from results.jsonl.
  --help           Print this help.

Removed:
  .tmp/manual-live/run-*/store
  .tmp/manual-live/run-*/artifacts
  .tmp/manual-live/run-*/reports        (only with --purge-reports)
  .tmp/g3verify, .tmp/g3verify.sh, .tmp/g5verify.sh
  /tmp/g2*, /tmp/g3*, /tmp/g4*, /tmp/g5*, /tmp/e1v..e7v, /tmp/nsl*,
  /tmp/f1*, /tmp/fakehome, /tmp/mlbin, /tmp/c1probe, /tmp/c2probe,
  /tmp/ctl, /tmp/p18, /tmp/p22, /tmp/t.sh, /tmp/orig-obj.txt,
  /tmp/stage-obj.txt
  /dev/shm/ml-*

Never removed:
  .tmp/data-recovery/20261111125501/original   (protected recovery backup)
  .tmp/bdd, .tmp/cutover-*, .tmp/marker-repair, .tmp/namespace-safety,
  .tmp/stat-lock, .tmp/tag-storage, .tmp/layout-primitives
  any project source file
EOF
}

# refuse_protected rejects the recovery backup and anything inside it.
#
# Both paths are resolved first so a symlink or a ".." segment cannot smuggle
# the backup path past a plain string comparison.
refuse_protected() {
    local target="$1" real_target real_backup
    real_target=$(readlink -f "${target}" 2>/dev/null || printf '%s' "${target}")
    real_backup=$(readlink -f "${PROTECTED_BACKUP}" 2>/dev/null || printf '%s' "${PROTECTED_BACKUP}")
    case "${real_target}" in
        "${real_backup}"|"${real_backup}"/*)
            printf 'error: refusing to remove the protected recovery backup: %s\n' "${real_target}" >&2
            printf 'error: the backup is the only evidence of the pre-cutover store\n' >&2
            return 1
            ;;
    esac
    return 0
}

# backup_file_count prints the number of regular files in the protected backup.
backup_file_count() {
    find "${PROTECTED_BACKUP}" -type f 2>/dev/null | wc -l | tr -d ' '
}

# plan_targets prints every path this run would remove.
#
# The list is built from explicit globs instead of a broad sweep so an
# unrelated directory can never be swept in by accident.
plan_targets() {
    local dir

    for dir in "${PROJECT_ROOT}"/.tmp/manual-live/run-*; do
        [[ -d "${dir}" ]] || continue
        [[ -d "${dir}/store" ]] && printf '%s\n' "${dir}/store"
        [[ -d "${dir}/artifacts" ]] && printf '%s\n' "${dir}/artifacts"
        if [[ "${PURGE_REPORTS}" -eq 1 && -d "${dir}/reports" ]]; then
            printf '%s\n' "${dir}/reports"
        fi
    done

    for dir in \
        "${PROJECT_ROOT}/.tmp/g3verify" \
        "${PROJECT_ROOT}/.tmp/g3verify.sh" \
        "${PROJECT_ROOT}/.tmp/g5verify.sh"; do
        [[ -e "${dir}" ]] && printf '%s\n' "${dir}"
    done

    local pattern
    for pattern in \
        /tmp/g2 /tmp/g2.md /tmp/g2store \
        /tmp/g3 /tmp/g3.md /tmp/g3link /tmp/g3store /tmp/g3v \
        /tmp/g4 /tmp/g4.md /tmp/g4store /tmp/g4t /tmp/g4ready /tmp/g4pid \
        /tmp/g5.md /tmp/g5probe /tmp/g5pty.out /tmp/g5pty.nocr \
        /tmp/g5pipe.out /tmp/g5err.out /tmp/g5bin.dat /tmp/g5bin.pipe \
        /tmp/g5bin.pty /tmp/g5tmux.out \
        /tmp/e1v /tmp/e2v /tmp/e3v /tmp/e4v /tmp/e6v /tmp/e7v \
        /tmp/nsl3 /tmp/nslA /tmp/nslock /tmp/nslock.md /tmp/nslock2 \
        /tmp/f1-hard.md /tmp/f1-link.md /tmp/f1.md /tmp/f1c /tmp/f1fx \
        /tmp/f1fx2 /tmp/f1p /tmp/f1probe /tmp/f1q /tmp/f1r /tmp/f1shape \
        /tmp/f1unmarked /tmp/fakehome /tmp/mlbin /tmp/c1probe /tmp/c2probe \
        /tmp/ctl /tmp/p18 /tmp/p22 /tmp/t.sh /tmp/orig-obj.txt \
        /tmp/stage-obj.txt; do
        [[ -e "${pattern}" ]] && printf '%s\n' "${pattern}"
    done

    for dir in /dev/shm/ml-*; do
        [[ -e "${dir}" ]] && printf '%s\n' "${dir}"
    done

    return 0
}

# remove_target removes one path and prints an audit line.
#
# The protected-path check runs for every target, so a target that resolves into
# the backup is refused even when it was produced by a glob.
remove_target() {
    local target="$1"
    if ! refuse_protected "${target}"; then
        return 1
    fi
    if [[ ! -e "${target}" ]]; then
        return 0
    fi
    if [[ -d "${target}" && ! -L "${target}" ]]; then
        rm -rf -- "${target}"
    else
        rm -f -- "${target}"
    fi
    if [[ -e "${target}" ]]; then
        printf 'error: removal failed: %s\n' "${target}" >&2
        return 1
    fi
    printf 'deleted: %s\n' "${target}"
    return 0
}

main() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run) DRY_RUN=1 ;;
            --purge-reports) PURGE_REPORTS=1 ;;
            --help|-h) usage; exit 0 ;;
            *)
                printf 'error: unknown argument: %s\n' "$1" >&2
                usage >&2
                exit 2
                ;;
        esac
        shift
    done

    if [[ ! -d "${PROTECTED_BACKUP}" ]]; then
        printf 'error: protected backup not found: %s\n' "${PROTECTED_BACKUP}" >&2
        exit 1
    fi
    if ! refuse_protected "${PROJECT_ROOT}/.tmp/manual-live"; then
        exit 3
    fi

    local before_count
    before_count=$(backup_file_count)
    printf 'cleanup: protected backup files before: %s\n' "${before_count}"

    local targets
    targets=$(plan_targets)
    local total=0
    if [[ -n "${targets}" ]]; then
        total=$(printf '%s\n' "${targets}" | wc -l | tr -d ' ')
    fi
    printf 'cleanup: planned targets: %s\n' "${total}"

    if [[ "${DRY_RUN}" -eq 1 ]]; then
        if [[ -n "${targets}" ]]; then
            printf '%s\n' "${targets}" | while IFS= read -r target; do
                printf 'would delete: %s\n' "${target}"
            done
        fi
        printf 'cleanup: dry run complete, nothing removed\n'
        exit 0
    fi

    local removed=0 failed=0
    if [[ -n "${targets}" ]]; then
        while IFS= read -r target; do
            if remove_target "${target}"; then
                removed=$((removed + 1))
            else
                failed=$((failed + 1))
            fi
        done <<< "${targets}"
    fi

    local after_count
    after_count=$(backup_file_count)
    printf 'cleanup: removed: %s failed: %s\n' "${removed}" "${failed}"
    printf 'cleanup: protected backup files after: %s\n' "${after_count}"

    if [[ "${after_count}" != "${BASELINE_BACKUP_FILES}" ]]; then
        printf 'error: protected backup file count changed: expected %s actual %s\n' \
            "${BASELINE_BACKUP_FILES}" "${after_count}" >&2
        exit 1
    fi
    if [[ "${failed}" -ne 0 ]]; then
        exit 1
    fi

    printf 'cleanup: protected backup intact (%s files)\n' "${after_count}"
    exit 0
}

main "$@"
