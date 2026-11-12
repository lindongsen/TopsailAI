#!/usr/bin/env bash
# fault-fixtures: build fault fixtures on a disposable copy of a store.
#
# Every fixture mutates the target store, so the target must be a copy. The
# protected recovery backup is refused unconditionally: a fixture that damaged
# it would destroy the only evidence of the pre-cutover data.
#
# Usage:
#   bash tests/manual-live/scripts/fault-fixtures.sh --root <copy> <fixture> [options]
#
# Fixtures:
#   corrupt-metadata --variant <name>   rewrite one metadata record
#   corrupt-stat                        truncate one stat record
#   readonly-meta                       make the metadata tree read-only
#   readonly-payload                    make one payload directory read-only
#   symlink-payload                     add an interior symlink to a payload
#   malicious-tar --kind <name>         build a hostile tar archive
#   legacy-stat                         add a legacy object/.stat.json
#   restore --from <backup>             restore files from a backup copy
#
# Options:
#   --root <path>    store copy to mutate (required)
#   --id <object-id> object to target (default: first listed object)
#   --variant <n>    corrupt-metadata variant (required for that fixture)
#   --kind <n>       malicious-tar kind (required for that fixture)
#   --from <path>    restore source (required for restore)
#   --out <path>     where malicious-tar writes the archive
#
# Safety:
#   - the protected backup path is refused before any mutation
#   - every mutation prints "fixture: <name> applied to <path>"
#   - restore verifies the restored digest against the backup

set -uo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1

# shellcheck source=lib.sh
source "${EXE_FOLDER}/lib.sh"

# lib.sh enables errexit; fixtures must report their own failures instead of
# aborting mid-way, so errexit is dropped again here.
set +e
set -uo pipefail

# PROTECTED_BACKUP is the recovery evidence that must never be mutated.
PROTECTED_BACKUP="${PROJECT_ROOT}/.tmp/data-recovery/20261111125501/original"

ROOT=""
ONLY_ID=""
VARIANT=""
KIND=""
FROM=""
OUT=""
FIXTURE=""

usage() {
    sed -n '2,32p' "${EXE_FILE}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root) ROOT="$2"; shift 2 ;;
        --id) ONLY_ID="$2"; shift 2 ;;
        --variant) VARIANT="$2"; shift 2 ;;
        --kind) KIND="$2"; shift 2 ;;
        --from) FROM="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        -*) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
        *) FIXTURE="$1"; shift ;;
    esac
done

if [[ -z "${ROOT}" ]]; then
    printf 'error: --root is required\n' >&2
    exit 2
fi
if [[ -z "${FIXTURE}" ]]; then
    printf 'error: a fixture name is required\n' >&2
    exit 2
fi
if [[ ! -d "${ROOT}" ]]; then
    printf 'error: root does not exist: %s\n' "${ROOT}" >&2
    exit 2
fi

# refuse_protected rejects the recovery backup and anything inside it.
#
# The check resolves both paths first so a symlink or a ".." segment cannot
# smuggle the backup path past a plain string comparison.
refuse_protected() {
    local target real_target real_backup
    target="$1"
    real_target=$(readlink -f "${target}" 2>/dev/null || printf '%s' "${target}")
    real_backup=$(readlink -f "${PROTECTED_BACKUP}" 2>/dev/null || printf '%s' "${PROTECTED_BACKUP}")
    case "${real_target}" in
        "${real_backup}"|"${real_backup}"/*)
            printf 'error: refusing to mutate the protected recovery backup: %s\n' "${real_target}" >&2
            printf 'error: copy the store first and pass the copy as --root\n' >&2
            return 1
            ;;
    esac
    return 0
}

if ! refuse_protected "${ROOT}"; then
    exit 3
fi

# target_id prints the requested object id or the first listed object.
target_id() {
    if [[ -n "${ONLY_ID}" ]]; then
        printf '%s' "${ONLY_ID}"
        return 0
    fi
    local id
    id=$(TOPSAILAI_DATA_ROOT="${ROOT}" TOPSAILAI_DATA_TRACK_STAT=0 \
        "${ML_BIN}" list --include-deleted --format json 2>/dev/null \
        | jq -r '.[0].id // empty' 2>/dev/null)
    if [[ -z "${id}" ]]; then
        printf 'error: no object found in %s\n' "${ROOT}" >&2
        return 1
    fi
    printf '%s' "${id}"
}

# payload_dir_of prints the payload directory of an object id.
#
# The path is read from the metadata record instead of "list", because a fixture
# may already have corrupted that record and "list" fails as a whole when any
# record is unreadable. The Hash metadata directory is derived from the id, so
# this lookup keeps working after corruption.
payload_dir_of() {
    local id="$1" dir path
    dir=$(ml_meta_dir "${ROOT}" "${id}")
    if [[ ! -f "${dir}/metadata.json" ]]; then
        printf 'error: metadata record not found for %s\n' "${id}" >&2
        return 1
    fi
    # The stored record uses PascalCase keys, so the selector must be ".Path".
    # A snake_case ".path" selector would silently return empty and every
    # payload fixture would fail with "has no path".
    path=$(jq -r '.Path // empty' "${dir}/metadata.json" 2>/dev/null)
    if [[ -z "${path}" ]]; then
        printf 'error: metadata record for %s has no path\n' "${id}" >&2
        return 1
    fi
    printf '%s/object/%s' "${ROOT}" "${path}"
}

# fixture_corrupt_metadata rewrites one metadata record with a chosen defect.
#
# The variants match the corruption classes asserted by SAFE-06 so the fixture
# and the case cannot drift apart.
fixture_corrupt_metadata() {
    local id dir file
    id=$(target_id) || return 1
    dir=$(ml_meta_dir "${ROOT}" "${id}")
    file="${dir}/metadata.json"
    if [[ ! -f "${file}" ]]; then
        printf 'error: metadata record not found: %s\n' "${file}" >&2
        return 1
    fi
    case "${VARIANT}" in
        unknown-field)
            jq '. + {mystery_field: "x"}' "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}" ;;
        unknown-object-id)
            jq '. + {object_id: "x"}' "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}" ;;
        unknown-schema-field)
            jq '. + {schema_version: 1}' "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}" ;;
        # The record uses PascalCase keys, so every selector below must match
        # that spelling. A snake_case selector such as ".schema_version" would
        # only add an unknown field and never reach the defect under test.
        name-mismatch)
            jq '.Name = "different-name"' "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}" ;;
        future-schema)
            jq '.SchemaVersion = 99' "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}" ;;
        dataref-mismatch)
            jq '.DataRef = "2026/0101/0000/elsewhere"' "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}" ;;
        bad-status)
            jq '.Status = "bogus"' "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}" ;;
        escaping-path)
            jq '.Path = "../escape"' "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}" ;;
        truncated)
            head -c 20 "${file}" > "${file}.tmp" && mv "${file}.tmp" "${file}" ;;
        missing)
            rm -f "${file}" ;;
        directory)
            rm -f "${file}" && mkdir -p "${file}" ;;
        *)
            printf 'error: unknown corrupt-metadata variant: %s\n' "${VARIANT}" >&2
            return 1
            ;;
    esac
    printf 'fixture: corrupt-metadata/%s applied to %s\n' "${VARIANT}" "${file}"
}

# fixture_corrupt_stat truncates one stat record.
#
# A store created with stat tracking disabled has no stat record yet, so a
# missing record is seeded first. The fixture must produce a corrupt record in
# every case, otherwise the case would silently test nothing.
fixture_corrupt_stat() {
    local id dir file
    id=$(target_id) || return 1
    dir=$(ml_meta_dir "${ROOT}" "${id}")
    file="${dir}/stat.json"
    if [[ ! -f "${file}" ]]; then
        printf '{"schema_version": 1, "read_count": 0, "write_count": 0}\n' > "${file}"
    fi
    printf '{"schema_version": 1, "read_count": ' > "${file}"
    printf 'fixture: corrupt-stat applied to %s\n' "${file}"
}

# fixture_readonly_meta makes the metadata tree read-only for the test user.
#
# The store is handed to nobody first, because root ignores permission bits and
# a root-owned read-only tree would not reproduce the failure.
fixture_readonly_meta() {
    ml_chown_nobody "${ROOT}"
    chmod 0555 "${ROOT}" "${ROOT}/object" "${ROOT}/meta"
    printf 'fixture: readonly-meta applied to %s\n' "${ROOT}/meta"
}

# fixture_readonly_payload makes one payload directory read-only.
#
# The payload path is resolved from the metadata record instead of "list",
# because a previous fixture may already have corrupted that record and "list"
# fails as a whole when any record is unreadable.
fixture_readonly_payload() {
    local id dir
    id=$(target_id) || return 1
    dir=$(payload_dir_of "${id}") || return 1
    if [[ ! -d "${dir}" ]]; then
        printf 'error: payload directory not found for %s\n' "${id}" >&2
        return 1
    fi
    ml_chown_nobody "${ROOT}"
    chmod 0555 "${dir}"
    printf 'fixture: readonly-payload applied to %s\n' "${dir}"
}

# fixture_symlink_payload adds an interior symlink pointing outside the store.
#
# The payload path is resolved from the metadata record for the same reason as
# fixture_readonly_payload: "list" cannot be trusted after a corrupting fixture.
fixture_symlink_payload() {
    local id dir outside
    id=$(target_id) || return 1
    dir=$(payload_dir_of "${id}") || return 1
    if [[ ! -d "${dir}" ]]; then
        printf 'error: payload directory not found for %s\n' "${id}" >&2
        return 1
    fi
    outside="${ML_ARTIFACTS}/outside-sentinel.txt"
    mkdir -p "${ML_ARTIFACTS}"
    printf 'SENTINEL\n' > "${outside}"
    ln -sfn "${outside}" "${dir}/link.txt"
    printf 'fixture: symlink-payload applied to %s\n' "${dir}/link.txt"
}

# fixture_malicious_tar builds a hostile archive without extracting it.
fixture_malicious_tar() {
    local out="${OUT:-${ML_ARTIFACTS}/malicious-${KIND}.tar}"
    local stage="${ML_ARTIFACTS}/tar-stage"
    mkdir -p "${ML_ARTIFACTS}"
    rm -rf "${stage}"
    mkdir -p "${stage}"
    case "${KIND}" in
        traversal)
            printf 'x\n' > "${stage}/payload.txt"
            tar -cf "${out}" -C "${stage}" payload.txt
            printf 'x\n' > "${stage}/../escape.txt"
            tar -rf "${out}" -C "${stage}/.." escape.txt
            rm -f "${stage}/../escape.txt"
            ;;
        absolute)
            printf 'x\n' > "${stage}/payload.txt"
            tar -cf "${out}" -P "${stage}/payload.txt" 2>/dev/null \
                || tar -cf "${out}" -C "${stage}" payload.txt
            ;;
        link)
            printf 'x\n' > "${stage}/payload.txt"
            ln -sfn /etc/passwd "${stage}/link.txt"
            tar -cf "${out}" -C "${stage}" payload.txt link.txt
            ;;
        malformed)
            printf 'not a tar archive\n' > "${out}"
            ;;
        truncated)
            printf 'x\n' > "${stage}/payload.txt"
            tar -cf "${out}" -C "${stage}" payload.txt
            head -c 200 "${out}" > "${out}.part" && mv "${out}.part" "${out}"
            ;;
        *)
            printf 'error: unknown malicious-tar kind: %s\n' "${KIND}" >&2
            return 1
            ;;
    esac
    printf 'fixture: malicious-tar/%s applied to %s\n' "${KIND}" "${out}"
}

# fixture_legacy_stat adds a pre-cutover object/.stat.json record.
#
# The current binary treats this file as ordinary user data, so the fixture
# proves that a legacy record is neither read nor updated.
fixture_legacy_stat() {
    local id dir
    id=$(target_id) || return 1
    dir=$(payload_dir_of "${id}") || return 1
    if [[ ! -d "${dir}" ]]; then
        printf 'error: payload directory not found for %s\n' "${id}" >&2
        return 1
    fi
    printf '{"schema_version": 1, "read_count": 5, "write_count": 2}\n' > "${dir}/.stat.json"
    printf 'fixture: legacy-stat applied to %s\n' "${dir}/.stat.json"
}

# fixture_restore copies files back from a backup and verifies each digest.
fixture_restore() {
    if [[ -z "${FROM}" ]]; then
        printf 'error: --from is required for restore\n' >&2
        return 1
    fi
    if [[ ! -d "${FROM}" ]]; then
        printf 'error: restore source does not exist: %s\n' "${FROM}" >&2
        return 1
    fi
    local rel src dst expected actual restored=0 failed=0
    while IFS= read -r rel; do
        src="${FROM}/${rel}"
        dst="${ROOT}/${rel}"
        [[ -f "${src}" ]] || continue
        mkdir -p "$(dirname "${dst}")"
        cp -p "${src}" "${dst}"
        expected=$(sha256sum "${src}" | awk '{print $1}')
        actual=$(sha256sum "${dst}" | awk '{print $1}')
        if [[ "${expected}" == "${actual}" ]]; then
            restored=$((restored + 1))
        else
            failed=$((failed + 1))
            printf 'error: digest mismatch after restore: %s\n' "${rel}" >&2
        fi
    done < <(cd "${FROM}" && find . -type f -printf '%P\n' | sort)
    printf 'fixture: restore applied to %s (restored=%s failed=%s)\n' "${ROOT}" "${restored}" "${failed}"
    [[ "${failed}" -eq 0 ]]
}

case "${FIXTURE}" in
    corrupt-metadata) fixture_corrupt_metadata ;;
    corrupt-stat) fixture_corrupt_stat ;;
    readonly-meta) fixture_readonly_meta ;;
    readonly-payload) fixture_readonly_payload ;;
    symlink-payload) fixture_symlink_payload ;;
    malicious-tar) fixture_malicious_tar ;;
    legacy-stat) fixture_legacy_stat ;;
    restore) fixture_restore ;;
    *) printf 'error: unknown fixture: %s\n' "${FIXTURE}" >&2; exit 2 ;;
esac
