#!/usr/bin/env bash
# observe-layout: narrow read-only observation of the payload and Hash metadata
# layout, tags and statistics.
#
# This is not a general backend browser. It exists so a case can assert a stated
# layout fact without dumping business content: it prints counts, paths, sizes,
# digests and status values, and it never prints file bodies, credentials,
# tokens or personal content. It never writes, moves, renames or deletes.
#
# Usage:
#   bash tests/manual-live/scripts/observe-layout.sh --root <store> [options]
#
# Options:
#   --root <path>     store root to observe (required)
#   --id <object-id>  restrict object-level output to one object
#   --section <name>  print one section: summary|objects|meta|tags|stat|integrity
#   --format <fmt>    text (default) or json
#   --max-objects <n> cap object listings (default 50)
#
# Read-only guarantees:
#   - stat tracking is disabled for every CLI call, so no counter changes
#   - the store is never opened for writing; only find/stat/sha256sum and the
#     CLI read commands are used
#   - a before/after manifest of the observed root is printed so the caller can
#     prove that observation changed nothing

set -uo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1

# shellcheck source=lib.sh
source "${EXE_FOLDER}/lib.sh"

# lib.sh enables "set -e" for the case scripts. This observer must keep running
# after a non-zero probe so it can report every section, so errexit is dropped
# again here instead of aborting on the first failed read.
set +e
set -uo pipefail

ROOT=""
ONLY_ID=""
SECTION="summary"
FORMAT="text"
MAX_OBJECTS=50

usage() {
    sed -n '2,30p' "${EXE_FILE}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --root) ROOT="$2"; shift 2 ;;
        --id) ONLY_ID="$2"; shift 2 ;;
        --section) SECTION="$2"; shift 2 ;;
        --format) FORMAT="$2"; shift 2 ;;
        --max-objects) MAX_OBJECTS="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
    esac
done

if [[ -z "${ROOT}" ]]; then
    printf 'error: --root is required\n' >&2
    exit 2
fi
if [[ ! -d "${ROOT}" ]]; then
    printf 'error: root does not exist: %s\n' "${ROOT}" >&2
    exit 2
fi

# ml_init creates the run directory tree and records binary identity. It is
# required because the observer writes its manifests under ML_ARTIFACTS and
# runs the CLI with an isolated HOME.
if ! ml_init; then
    printf 'error: harness initialization failed\n' >&2
    exit 2
fi

# observe_manifest prints a stable manifest of the observed root.
#
# The namespace lock is excluded because acquiring it touches its mtime, which
# is a permitted initialization effect rather than a business mutation.
observe_manifest() {
    (
        cd "${ROOT}" || exit 1
        find . -type f ! -name '.topsailai-data-namespace.lock' -print0 \
            | sort -z | xargs -0 -r sha256sum
    )
}

# cli_read runs a read-only CLI command with stat tracking disabled.
cli_read() {
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" \
        LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC \
        TOPSAILAI_DATA_ROOT="${ROOT}" TOPSAILAI_DATA_TRACK_STAT=0 \
        "${ML_BIN}" "$@" 2>/dev/null
}

# section_summary prints store-level counts.
section_summary() {
    local payload_dirs meta_dirs tags stat_files locks
    payload_dirs=$(find "${ROOT}/object" -type f -name '*.md' 2>/dev/null | wc -l)
    meta_dirs=$(find "${ROOT}/meta" -name 'metadata.json' 2>/dev/null | wc -l)
    tags=$(find "${ROOT}/meta" -name 'tags' 2>/dev/null | wc -l)
    stat_files=$(find "${ROOT}/meta" -name 'stat.json' 2>/dev/null | wc -l)
    locks=$(find "${ROOT}/meta" -name 'lock' 2>/dev/null | wc -l)
    printf 'root: %s\n' "${ROOT}"
    printf 'layout marker: %s\n' "$([[ -f "${ROOT}/topsailai_data.json" ]] && echo present || echo absent)"
    printf 'payload marker files: %s\n' "${payload_dirs}"
    printf 'metadata records: %s\n' "${meta_dirs}"
    printf 'tag files: %s\n' "${tags}"
    printf 'stat records: %s\n' "${stat_files}"
    printf 'lock files: %s\n' "${locks}"
}

# section_objects prints object identity, path and status without content.
section_objects() {
    local listing
    listing=$(cli_read list --include-deleted --format json --limit "${MAX_OBJECTS}")
    if [[ -z "${listing}" ]]; then
        printf 'objects: none\n'
        return 0
    fi
    printf '%s\n' "${listing}" \
        | jq -r '.[] | "\(.id)\t\(.status)\t\(.path)"' 2>/dev/null \
        || printf 'objects: unparsable listing\n'
}

# section_meta prints the Hash metadata path of one object or all records.
section_meta() {
    if [[ -n "${ONLY_ID}" ]]; then
        local dir
        dir=$(ml_meta_dir "${ROOT}" "${ONLY_ID}")
        printf 'meta dir: %s\n' "${dir}"
        printf 'metadata.json: %s\n' "$([[ -f "${dir}/metadata.json" ]] && echo present || echo absent)"
        printf 'tags: %s\n' "$([[ -f "${dir}/tags" ]] && echo present || echo absent)"
        printf 'stat.json: %s\n' "$([[ -f "${dir}/stat.json" ]] && echo present || echo absent)"
        printf 'lock: %s\n' "$([[ -f "${dir}/lock" ]] && echo present || echo absent)"
        return 0
    fi
    find "${ROOT}/meta" -name 'metadata.json' 2>/dev/null | head -"${MAX_OBJECTS}" | while read -r file; do
        printf '%s\n' "${file#"${ROOT}/"}"
    done
}

# section_tags prints tag values only for the requested object.
#
# Tags are business metadata, so they are printed only when an explicit object
# id is supplied; a store-wide dump would leak unrelated content.
section_tags() {
    if [[ -z "${ONLY_ID}" ]]; then
        printf 'tags: pass --id to print tag values\n'
        return 0
    fi
    local dir
    dir=$(ml_meta_dir "${ROOT}" "${ONLY_ID}")
    if [[ ! -f "${dir}/tags" ]]; then
        printf 'tags: none\n'
        return 0
    fi
    printf 'tags:\n'
    sed 's/^/  /' "${dir}/tags"
}

# section_stat prints counter values without any business content.
section_stat() {
    if [[ -n "${ONLY_ID}" ]]; then
        local dir
        dir=$(ml_meta_dir "${ROOT}" "${ONLY_ID}")
        if [[ ! -f "${dir}/stat.json" ]]; then
            printf 'stat: none\n'
            return 0
        fi
        jq -r 'to_entries[] | "\(.key): \(.value)"' "${dir}/stat.json" 2>/dev/null \
            || printf 'stat: unparsable record\n'
        return 0
    fi
    local total
    total=$(find "${ROOT}/meta" -name 'stat.json' 2>/dev/null | wc -l)
    printf 'stat records: %s\n' "${total}"
}

# section_integrity prints digests that prove observation changed nothing.
section_integrity() {
    local before="${ML_ARTIFACTS}/observe-before.txt"
    local after="${ML_ARTIFACTS}/observe-after.txt"
    mkdir -p "${ML_ARTIFACTS}"
    observe_manifest > "${before}"
    observe_manifest > "${after}"
    printf 'manifest entries: %s\n' "$(wc -l < "${before}")"
    if diff -q "${before}" "${after}" > /dev/null; then
        printf 'observation effect: none\n'
    else
        printf 'observation effect: changed\n'
        diff "${before}" "${after}" | head -20
    fi
    printf 'manifest digest: %s\n' "$(sha256sum "${before}" | awk '{print $1}')"
}

case "${SECTION}" in
    summary) section_summary ;;
    objects) section_objects ;;
    meta) section_meta ;;
    tags) section_tags ;;
    stat) section_stat ;;
    integrity) section_integrity ;;
    *) printf 'error: unknown section: %s\n' "${SECTION}" >&2; exit 2 ;;
esac
