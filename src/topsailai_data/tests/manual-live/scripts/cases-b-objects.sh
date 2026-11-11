#!/usr/bin/env bash
# Module B: objects and discovery cases (OBJ-01 .. OBJ-24).
#
# Every case uses an isolated root below the run area. The existing live store
# is never referenced here. Assertions are derived from observed CLI contract
# behaviour, not from assumptions about the implementation.

set -euo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1

# shellcheck source=lib.sh
source "${EXE_FOLDER}/lib.sh"

usage() {
    cat <<'EOF'
Usage: cases-b-objects.sh [case-id ...]

Runs object and discovery cases. Without arguments every case runs.

Exit codes:
  0  all selected cases passed or were blocked
  1  at least one case failed
  2  invalid arguments
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

ml_init

selected() {
    local case_id="$1"
    shift
    [[ $# -eq 0 ]] && return 0
    local want
    for want in "$@"; do
        [[ "${want}" == "${case_id}" ]] && return 0
    done
    return 1
}

# json_field prints one field of the single object returned by list --format json.
# --include-deleted is required because lifecycle cases inspect deleted and
# ceased records, which the default list hides.
json_field() {
    local root="$1" id="$2" field="$3"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --include-deleted --format json 2>/dev/null \
        | jq -r --arg id "${id}" --arg f "${field}" '.[] | select(.id==$id) | .[$f]'
}

# json_count prints the number of objects returned by list --format json.
json_count() {
    local root="$1"
    shift
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --format json "$@" 2>/dev/null | jq 'length'
}

run_obj_01() {
    begin_case OBJ-01 P0 I
    local root="${ML_STORES}/OBJ-01/store"
    local out="${ML_CASE_DIR}/OBJ-01"
    ml_make_markdown "${ML_FIXTURES}/obj01/note.md" "obj01 description" "# obj01 body"
    local src_sha
    src_sha=$(sha256sum "${ML_FIXTURES}/obj01/note.md" | awk '{print $1}')

    ml_run_ok "${root}" "${out}-create" create obj01 --classify work/2026 \
        --tag alpha,beta,alpha --from "${ML_FIXTURES}/obj01/note.md"
    ml_expect_contains "create reports the object" "${out}-create.stdout" "created object obj01"

    ml_run_ok "${root}" "${out}-show" show obj01
    ml_expect_contains "show reports the ID" "${out}-show.stdout" "ID:            obj01"
    ml_expect_contains "show reports the description" "${out}-show.stdout" "obj01 description"
    ml_expect_contains "show reports active status" "${out}-show.stdout" "Status:        active"
    ml_expect_contains "show reports schema version 2" "${out}-show.stdout" "SchemaVersion: 2"

    # Duplicate tags are deduplicated while order is preserved.
    ml_expect "duplicate tags are deduplicated" "alpha, beta" \
        "$(json_field "${root}" obj01 tags | jq -r 'join(", ")')"

    # The path uses the local-time prefix and keeps the classify directories.
    local path
    path=$(json_field "${root}" obj01 path)
    if [[ "${path}" =~ ^[0-9]{4}/[0-9]{4}/[0-9]{4}/work/2026/obj01$ ]]; then
        ml_expect "path uses the local-time prefix" "match" "match"
    else
        ml_expect "path uses the local-time prefix" "match" "${path}"
    fi

    # The mandatory marker keeps the exact source bytes.
    ml_run_ok "${root}" "${out}-get" get obj01 obj01.md
    ml_expect_sha "marker bytes are preserved" "${out}-get.stdout" "${src_sha}"

    # A second process invocation reads the same identity and content.
    ml_run_ok "${root}" "${out}-restart" show obj01
    ml_expect_contains "restart keeps the same ID" "${out}-restart.stdout" "ID:            obj01"
    ml_expect_contains "restart keeps the same path" "${out}-restart.stdout" "Path:          ${path}"
    ml_run_ok "${root}" "${out}-restart-get" get obj01 obj01.md
    ml_expect_sha "restart keeps the same marker bytes" "${out}-restart-get.stdout" "${src_sha}"
    end_case
}

run_obj_02() {
    begin_case OBJ-02 P1 I
    local root="${ML_STORES}/OBJ-02/store"
    local out="${ML_CASE_DIR}/OBJ-02"
    ml_make_markdown "${ML_FIXTURES}/obj02/fallback.md" "frontmatter description" "# fallback"

    ml_run_ok "${root}" "${out}-fallback" create obj02a --from "${ML_FIXTURES}/obj02/fallback.md"
    ml_expect "description falls back to frontmatter" "frontmatter description" \
        "$(json_field "${root}" obj02a description)"

    ml_run_ok "${root}" "${out}-explicit" create obj02b --description "explicit description" \
        --from "${ML_FIXTURES}/obj02/fallback.md"
    ml_expect "explicit description wins over frontmatter" "explicit description" \
        "$(json_field "${root}" obj02b description)"
    end_case
}

run_obj_03() {
    begin_case OBJ-03 P1 I
    local root="${ML_STORES}/OBJ-03/store"
    local out="${ML_CASE_DIR}/OBJ-03"

    # Each unusable frontmatter variant must be rejected without an active object.
    local variant
    for variant in no-frontmatter non-string missing-key malformed empty-description; do
        ml_run_fail "${root}" "${out}-${variant}" create "obj03-${variant}" \
            --from "${ML_FIXTURES}/md/${variant}.md"
        ml_expect_contains "rejects ${variant} without a description" \
            "${out}-${variant}.stderr" "description is required"
    done

    ml_run_fail "${root}" "${out}-empty" create obj03-empty --from "${ML_FIXTURES}/md/empty.md"
    ml_expect_contains "rejects empty input" "${out}-empty.stderr" "markdown content is required"

    ml_expect "no active object was created" "0" "$(json_count "${root}")"

    # An explicit description distinguishes a fallback failure from invalid payload.
    ml_run_ok "${root}" "${out}-explicit" create obj03-explicit --description "explicit" \
        --from "${ML_FIXTURES}/md/no-frontmatter.md"
    ml_expect "explicit description allows body-only markdown" "explicit" \
        "$(json_field "${root}" obj03-explicit description)"
    end_case
}

run_obj_04() {
    begin_case OBJ-04 P1 I
    local root="${ML_STORES}/OBJ-04/store"
    local out="${ML_CASE_DIR}/OBJ-04"

    # The frontmatter block sits at the start of the file in every variant, so
    # the bounded prefix still contains it.
    local variant
    for variant in boundary-before boundary-at boundary-after; do
        ml_run_ok "${root}" "${out}-${variant}" create "obj04-${variant}" \
            --from "${ML_FIXTURES}/md/${variant}.md"
        ml_expect "bounded prefix extracts ${variant}" "boundary" \
            "$(json_field "${root}" "obj04-${variant}" description)"
    done

    # A description value that pushes the closing fence past 8 KiB is not read.
    python3 - "${ML_FIXTURES}/obj04" <<'PY'
import sys, pathlib
base = pathlib.Path(sys.argv[1])
base.mkdir(parents=True, exist_ok=True)
(base / "long-block.md").write_text(
    "---\ndescription: " + "y" * 9000 + "\n---\n\nbody\n", encoding="utf-8"
)
PY
    ml_run_fail "${root}" "${out}-long-block" create obj04-long-block \
        --from "${ML_FIXTURES}/obj04/long-block.md"
    ml_expect_contains "frontmatter beyond the bounded prefix is not read" \
        "${out}-long-block.stderr" "description is required"
    end_case
}

run_obj_05() {
    begin_case OBJ-05 P1 I
    local root="${ML_STORES}/OBJ-05/store"
    local out="${ML_CASE_DIR}/OBJ-05"
    ml_make_markdown "${ML_FIXTURES}/obj05/plain.md" "plain source" "# plain source"

    # Plain file source.
    ml_run_ok "${root}" "${out}-plain" create obj05-plain --from "${ML_FIXTURES}/obj05/plain.md"
    ml_expect "plain file source keeps the description" "plain source" \
        "$(json_field "${root}" obj05-plain description)"

    # Tar archive source.
    mkdir -p "${ML_FIXTURES}/obj05/tar"
    ml_make_markdown "${ML_FIXTURES}/obj05/tar/obj05-tar.md" "tar source" "# tar source"
    tar -cf "${ML_FIXTURES}/obj05/tar.tar" -C "${ML_FIXTURES}/obj05/tar" obj05-tar.md
    ml_run_ok "${root}" "${out}-tar" create obj05-tar --from "${ML_FIXTURES}/obj05/tar.tar"
    ml_expect "tar source keeps the description" "tar source" \
        "$(json_field "${root}" obj05-tar description)"

    # In-memory stdin source with every parameter supplied on the command line.
    ml_make_markdown "${ML_FIXTURES}/obj05/stdin.md" "stdin source" "# stdin source"
    ml_run_ok "${root}" "${out}-stdin" --stdin "${ML_FIXTURES}/obj05/stdin.md" \
        create obj05-stdin --description "stdin source" --from -
    ml_expect "stdin source keeps the description" "stdin source" \
        "$(json_field "${root}" obj05-stdin description)"

    # Each source stores its own marker bytes exactly as supplied.
    ml_run_ok "${root}" "${out}-get-plain" get obj05-plain obj05-plain.md
    ml_expect_sha "plain marker matches its source" "${out}-get-plain.stdout" \
        "$(sha256sum "${ML_FIXTURES}/obj05/plain.md" | awk '{print $1}')"
    ml_run_ok "${root}" "${out}-get-tar" get obj05-tar obj05-tar.md
    ml_expect_sha "tar marker matches its source" "${out}-get-tar.stdout" \
        "$(sha256sum "${ML_FIXTURES}/obj05/tar/obj05-tar.md" | awk '{print $1}')"
    ml_run_ok "${root}" "${out}-get-stdin" get obj05-stdin obj05-stdin.md
    ml_expect_sha "stdin marker matches its source" "${out}-get-stdin.stdout" \
        "$(sha256sum "${ML_FIXTURES}/obj05/stdin.md" | awk '{print $1}')"
    end_case
}

run_obj_06() {
    begin_case OBJ-06 P0 I
    local root="${ML_STORES}/OBJ-06/store"
    local out="${ML_CASE_DIR}/OBJ-06"
    ml_make_markdown "${ML_FIXTURES}/obj06/first.md" "first description" "# first"
    ml_make_markdown "${ML_FIXTURES}/obj06/second.md" "second description" "# second"

    ml_run_ok "${root}" "${out}-create" create obj06 --classify work --tag keep \
        --from "${ML_FIXTURES}/obj06/first.md"
    local path_before created_before
    path_before=$(json_field "${root}" obj06 path)
    created_before=$(json_field "${root}" obj06 created_at)

    # A duplicate ID is rejected globally, even under a different classify path.
    ml_run_fail "${root}" "${out}-dup" create obj06 --classify other \
        --from "${ML_FIXTURES}/obj06/second.md"
    ml_expect_contains "duplicate ID is rejected" "${out}-dup.stderr" "object already exists"

    # The previous content, state, identity and tags are untouched.
    ml_expect "path is unchanged" "${path_before}" "$(json_field "${root}" obj06 path)"
    ml_expect "creation time is unchanged" "${created_before}" "$(json_field "${root}" obj06 created_at)"
    ml_expect "description is unchanged" "first description" "$(json_field "${root}" obj06 description)"
    ml_expect "tags are unchanged" "keep" "$(json_field "${root}" obj06 tags | jq -r 'join(",")')"
    ml_run_ok "${root}" "${out}-get" get obj06 obj06.md
    ml_expect_sha "content is unchanged" "${out}-get.stdout" \
        "$(sha256sum "${ML_FIXTURES}/obj06/first.md" | awk '{print $1}')"

    # A deleted object also blocks creation of the same ID.
    ml_run_ok "${root}" "${out}-delete" delete obj06
    ml_run_fail "${root}" "${out}-dup-deleted" create obj06 --from "${ML_FIXTURES}/obj06/second.md"
    ml_expect_contains "deleted ID blocks creation" "${out}-dup-deleted.stderr" "object already exists"
    end_case
}

run_obj_07() {
    begin_case OBJ-07 P1 I
    local root="${ML_STORES}/OBJ-07/store"
    local out="${ML_CASE_DIR}/OBJ-07"
    ml_make_markdown "${ML_FIXTURES}/obj07/old.md" "old description" "# old"
    ml_make_markdown "${ML_FIXTURES}/obj07/new.md" "new description" "# new"

    ml_run_ok "${root}" "${out}-create" create obj07 --tag oldtag --from "${ML_FIXTURES}/obj07/old.md"
    ml_run_ok "${root}" "${out}-delete" delete obj07
    ml_run_ok "${root}" "${out}-finalize" delete obj07
    ml_run_ok "${root}" "${out}-ceased" show obj07
    ml_expect_contains "object is ceased before recreation" "${out}-ceased.stdout" "Status:        ceased"

    # Creating over a ceased ID purges the old identity and creates new content.
    ml_run_ok "${root}" "${out}-recreate" create obj07 --tag newtag --from "${ML_FIXTURES}/obj07/new.md"
    ml_expect "recreated object is active" "active" "$(json_field "${root}" obj07 status)"
    ml_expect "recreated object has the new description" "new description" \
        "$(json_field "${root}" obj07 description)"
    ml_expect "recreated object has only the new tag" "newtag" \
        "$(json_field "${root}" obj07 tags | jq -r 'join(",")')"
    ml_run_ok "${root}" "${out}-get" get obj07 obj07.md
    ml_expect_sha "recreated content is the new payload" "${out}-get.stdout" \
        "$(sha256sum "${ML_FIXTURES}/obj07/new.md" | awk '{print $1}')"

    # Unrelated controls are untouched.
    ml_run_ok "${root}" "${out}-control" create obj07-control --from "${ML_FIXTURES}/obj07/old.md"
    ml_expect "control object stays active" "active" "$(json_field "${root}" obj07-control status)"
    end_case
}

run_obj_08() {
    begin_case OBJ-08 P1 I
    local root="${ML_STORES}/OBJ-08/store"
    local out="${ML_CASE_DIR}/OBJ-08"
    ml_make_markdown "${ML_FIXTURES}/obj08/note.md" "obj08 description" "# obj08"

    # Supported spellings round-trip.
    ml_run_ok "${root}" "${out}-unicode" create "对象-1" --from "${ML_FIXTURES}/obj08/note.md"
    ml_expect "unicode name round-trips" "对象-1" "$(json_field "${root}" "对象-1" id)"
    ml_run_ok "${root}" "${out}-unicode-classify" create obj08-uc --classify "分类/子类" \
        --from "${ML_FIXTURES}/obj08/note.md"
    ml_expect_contains "unicode classify path is kept" "${out}-unicode-classify.stdout" "分类/子类"

    # Invalid names are rejected. Each variant gets an explicit index prefix so
    # the captured file names stay predictable and unique.
    local -a bad_names=("" ".." " x" "x " "a/b" "a\\b" "a.lock" "a.deleted" "a.ceased" "NUL" "CON")
    local idx=0
    local bad
    for bad in "${bad_names[@]}"; do
        idx=$((idx + 1))
        ml_run_fail "${root}" "${out}-bad-${idx}" create "${bad}" \
            --from "${ML_FIXTURES}/obj08/note.md"
        ml_expect_contains "invalid name variant ${idx} is rejected" \
            "${out}-bad-${idx}.stderr" "invalid object name"
    done
    ml_expect_contains "reserved marker suffix is rejected" "${out}-bad-7.stderr" \
        "reserved marker suffix"
    ml_expect_contains "reserved device name is rejected" "${out}-bad-10.stderr" "reserved name"
    ml_expect "no invalid name created an object" "2" "$(json_count "${root}")"

    # Invalid classify segments are rejected.
    ml_run_fail "${root}" "${out}-bad-classify" create obj08-bad --classify "CON" \
        --from "${ML_FIXTURES}/obj08/note.md"
    ml_expect_contains "reserved classify segment is rejected" "${out}-bad-classify.stderr" \
        "invalid classify segment"

    # Case semantics are recorded rather than asserted, because the local
    # adapter treats names as case-sensitive on this platform.
    ml_run_ok "${root}" "${out}-case" create Obj08Case --from "${ML_FIXTURES}/obj08/note.md"
    ml_note "platform case semantics: Obj08Case and obj08case are distinct IDs on this filesystem"
    end_case
}

run_obj_09() {
    begin_case OBJ-09 P1 I
    local root="${ML_STORES}/OBJ-09/store"
    local out="${ML_CASE_DIR}/OBJ-09"
    ml_make_markdown "${ML_FIXTURES}/obj09/note.md" "obj09 description" "# obj09"

    # Depth 11 is allowed: 3 time levels + 7 classify levels + the object.
    ml_run_ok "${root}" "${out}-depth11" create obj09-d11 --classify a/b/c/d/e/f/g \
        --from "${ML_FIXTURES}/obj09/note.md"
    local path
    path=$(json_field "${root}" obj09-d11 path)
    ml_expect "depth 11 path has 11 levels" "11" "$(printf '%s' "${path}" | awk -F/ '{print NF}')"

    # Depth 12 is rejected.
    ml_run_fail "${root}" "${out}-depth12" create obj09-d12 --classify a/b/c/d/e/f/g/h \
        --from "${ML_FIXTURES}/obj09/note.md"
    ml_expect_contains "depth 12 is rejected" "${out}-depth12.stderr" "exceeds maximum depth"
    ml_expect_contains "depth error states the limit" "${out}-depth12.stderr" "max 11"
    ml_expect "rejected object was not created" "1" "$(json_count "${root}")"
    end_case
}

run_obj_10() {
    begin_case OBJ-10 P0 I
    local root="${ML_STORES}/OBJ-10/store"
    local out="${ML_CASE_DIR}/OBJ-10"
    ml_make_markdown "${ML_FIXTURES}/obj10/note.md" "obj10 description" "# obj10"

    ml_run_ok "${root}" "${out}-create" create obj10 --classify work --tag alpha,beta \
        --from "${ML_FIXTURES}/obj10/note.md"

    # The metadata leaf is the lowercase SHA256 of the object ID, split into
    # three two-character levels followed by the full digest.
    local hash meta
    hash=$(printf '%s' obj10 | sha256sum | awk '{print $1}')
    meta="${root}/meta/${hash:0:2}/${hash:2:2}/${hash:4:2}/${hash}"
    ml_expect_file "hash metadata directory exists" "${meta}" dir
    ml_expect_file "metadata.json exists" "${meta}/metadata.json" file
    ml_expect_file "independent tags file exists" "${meta}/tags" file
    ml_expect_file "object lock lives in metadata" "${meta}/lock" file
    ml_expect_file "stat lock lives in metadata" "${meta}/stat.lock" file
    ml_expect_file "stat record lives in metadata" "${meta}/stat.json" file

    # metadata.json must not carry tags; the tags file is the only store.
    ml_expect "metadata.json has no tags field" "false" \
        "$(jq 'has("Tags") or has("tags")' "${meta}/metadata.json")"
    ml_expect "tags file holds the merged tags" "alpha
beta" "$(cat "${meta}/tags")"

    # Path and DataRef are relative to object/ and identical.
    local path ref
    path=$(json_field "${root}" obj10 path)
    ref=$(json_field "${root}" obj10 data_ref)
    ml_expect "DataRef equals Path" "${path}" "${ref}"
    ml_expect_file "payload lives under object/" "${root}/object/${path}" dir
    ml_expect_file "payload is not at the store root" "${root}/${path}" absent

    # No classify metadata tree is created.
    ml_expect_file "no meta/classify tree" "${root}/meta/classify" absent
    end_case
}

run_obj_11() {
    begin_case OBJ-11 P0 I
    local root="${ML_STORES}/OBJ-11/store"
    local out="${ML_CASE_DIR}/OBJ-11"
    ml_make_markdown "${ML_FIXTURES}/obj11/note.md" "obj11 description" "# obj11"

    ml_run_ok "${root}" "${out}-create" create obj11 --tag realtag --from "${ML_FIXTURES}/obj11/note.md"

    # User payload files that share internal names are ordinary visible data.
    local name
    for name in metadata.json stat.json .stat.json obj11.lock obj11.tags; do
        printf 'user payload %s\n' "${name}" > "${ML_FIXTURES}/obj11/${name}"
        ml_run_ok "${root}" "${out}-put-${name//./_}" put obj11 "${name}" \
            --from "${ML_FIXTURES}/obj11/${name}"
    done

    ml_run_ok "${root}" "${out}-show" show obj11
    ml_expect_contains "user metadata.json is visible" "${out}-show.stdout" "metadata.json"
    ml_expect_contains "user stat.json is visible" "${out}-show.stdout" "stat.json"
    ml_expect_contains "user .stat.json is visible" "${out}-show.stdout" ".stat.json"
    ml_expect_contains "user obj11.lock is visible" "${out}-show.stdout" "obj11.lock"
    ml_expect_contains "user obj11.tags is visible" "${out}-show.stdout" "obj11.tags"

    # Each user file reads back byte-exactly.
    for name in metadata.json stat.json .stat.json obj11.lock obj11.tags; do
        ml_run_ok "${root}" "${out}-get-${name//./_}" get obj11 "${name}"
        ml_expect_sha "user file ${name} round-trips" "${out}-get-${name//./_}.stdout" \
            "$(sha256sum "${ML_FIXTURES}/obj11/${name}" | awk '{print $1}')"
    done

    # The real Hash metadata is unaffected by the user files.
    local hash meta
    hash=$(printf '%s' obj11 | sha256sum | awk '{print $1}')
    meta="${root}/meta/${hash:0:2}/${hash:2:2}/${hash:4:2}/${hash}"
    ml_expect "real tags are unchanged" "realtag" "$(cat "${meta}/tags")"
    ml_expect "real metadata still has no tags field" "false" \
        "$(jq 'has("Tags") or has("tags")' "${meta}/metadata.json")"
    ml_expect "object is still active" "active" "$(json_field "${root}" obj11 status)"
    end_case
}

run_obj_12() {
    begin_case OBJ-12 P1 I
    local root="${ML_STORES}/OBJ-12/store"
    local out="${ML_CASE_DIR}/OBJ-12"
    ml_make_markdown "${ML_FIXTURES}/obj12/note.md" "obj12 description" "# obj12"
    printf 'nested marker\n' > "${ML_FIXTURES}/obj12/nested.md"

    ml_run_ok "${root}" "${out}-create" create obj12 --from "${ML_FIXTURES}/obj12/note.md"
    ml_run_ok "${root}" "${out}-put" put obj12 sub/obj12.md --from "${ML_FIXTURES}/obj12/nested.md"
    ml_run_ok "${root}" "${out}-put2" put obj12 deep/obj12/obj12.md \
        --from "${ML_FIXTURES}/obj12/nested.md"

    # Nested marker-like files never become separate objects.
    ml_expect "inventory still has one object" "1" "$(json_count "${root}")"
    ml_run_ok "${root}" "${out}-list" list --format json
    ml_expect_not_contains "nested path is not listed as an object" "${out}-list.stdout" "sub"
    ml_run_ok "${root}" "${out}-search" search obj12 --format json
    ml_expect "search finds exactly one object" "1" "$(jq 'length' "${out}-search.stdout")"

    # The nested content is readable as object data.
    ml_run_ok "${root}" "${out}-get" get obj12 sub/obj12.md
    ml_expect_sha "nested content is readable" "${out}-get.stdout" \
        "$(sha256sum "${ML_FIXTURES}/obj12/nested.md" | awk '{print $1}')"
    end_case
}

run_obj_13() {
    begin_case OBJ-13 P1 I
    local root="${ML_STORES}/OBJ-13/store"
    local out="${ML_CASE_DIR}/OBJ-13"
    ml_make_markdown "${ML_FIXTURES}/obj13/note.md" "obj13 description" "# obj13"

    ml_run_ok "${root}" "${out}-create" create obj13 --tag keep --from "${ML_FIXTURES}/obj13/note.md"
    local created_before updated_before path_before
    created_before=$(json_field "${root}" obj13 created_at)
    updated_before=$(json_field "${root}" obj13 updated_at)
    path_before=$(json_field "${root}" obj13 path)

    sleep 1.1
    ml_run_ok "${root}" "${out}-update" update obj13 --description "updated description"
    ml_expect "description is updated" "updated description" "$(json_field "${root}" obj13 description)"
    ml_expect "creation time is stable" "${created_before}" "$(json_field "${root}" obj13 created_at)"
    ml_expect "ID is stable" "obj13" "$(json_field "${root}" obj13 id)"
    ml_expect "path is stable" "${path_before}" "$(json_field "${root}" obj13 path)"
    ml_expect "tags are stable" "keep" "$(json_field "${root}" obj13 tags | jq -r 'join(",")')"

    # UpdatedAt must advance and must never be a zero value.
    local updated_after
    updated_after=$(json_field "${root}" obj13 updated_at)
    if [[ "${updated_after}" > "${updated_before}" ]]; then
        ml_expect "updated_at advances" "advanced" "advanced"
    else
        ml_expect "updated_at advances" "advanced" "${updated_before} -> ${updated_after}"
    fi
    ml_expect_not_contains "updated_at is not zero" "${out}-update.stdout" "0001-01-01"

    # An explicit empty description clears it.
    ml_run_ok "${root}" "${out}-clear" update obj13 --description ""
    ml_expect "explicit empty description clears the value" "" "$(json_field "${root}" obj13 description)"

    # Content is untouched by metadata updates.
    ml_run_ok "${root}" "${out}-get" get obj13 obj13.md
    ml_expect_sha "content is untouched" "${out}-get.stdout" \
        "$(sha256sum "${ML_FIXTURES}/obj13/note.md" | awk '{print $1}')"
    end_case
}

run_obj_14() {
    begin_case OBJ-14 P1 I
    local root="${ML_STORES}/OBJ-14/store"
    local out="${ML_CASE_DIR}/OBJ-14"
    ml_make_markdown "${ML_FIXTURES}/obj14/note.md" "obj14 description" "# obj14"

    ml_run_ok "${root}" "${out}-create" create obj14 --from "${ML_FIXTURES}/obj14/note.md"

    # Unknown object.
    ml_run_fail "${root}" "${out}-unknown" update obj14-missing --description x
    ml_expect_contains "unknown object is refused" "${out}-unknown.stderr" "object not found"

    # Deleted object.
    ml_run_ok "${root}" "${out}-delete" delete obj14
    ml_run_fail "${root}" "${out}-deleted" update obj14 --description x
    ml_expect_contains "deleted object is refused" "${out}-deleted.stderr" "not active"
    ml_expect "deleted status is preserved" "deleted" "$(json_field "${root}" obj14 status)"

    # Ceased object.
    ml_run_ok "${root}" "${out}-finalize" delete obj14
    ml_run_fail "${root}" "${out}-ceased" update obj14 --description x
    ml_expect_contains "ceased object is refused" "${out}-ceased.stderr" "not active"
    ml_expect "ceased status is preserved" "ceased" "$(json_field "${root}" obj14 status)"
    end_case
}

run_obj_15() {
    begin_case OBJ-15 P1 I
    local root="${ML_STORES}/OBJ-15/store"
    local out="${ML_CASE_DIR}/OBJ-15"
    ml_make_markdown "${ML_FIXTURES}/obj15/note.md" "obj15 description" "# obj15 body"

    ml_run_ok "${root}" "${out}-create" create obj15 --from "${ML_FIXTURES}/obj15/note.md"
    ml_run_ok "${root}" "${out}-show-bare" show obj15
    ml_expect_contains "metadata section is present" "${out}-show-bare.stdout" "ID:            obj15"
    ml_expect_contains "markdown section is present" "${out}-show-bare.stdout" "--- Markdown ---"
    ml_expect_contains "markdown body is shown" "${out}-show-bare.stdout" "# obj15 body"
    ml_expect_contains "folder section is present" "${out}-show-bare.stdout" "--- folder structure ---"
    ml_expect_contains "no additional files is reported" "${out}-show-bare.stdout" "no additional files"
    ml_expect_not_contains "hash internals are absent" "${out}-show-bare.stdout" "metadata.json"
    ml_expect_not_contains "lock internals are absent" "${out}-show-bare.stdout" "stat.lock"

    # Unicode nested extras appear in the tree.
    printf 'nested\n' > "${ML_FIXTURES}/obj15/说明.txt"
    ml_run_ok "${root}" "${out}-put" put obj15 "资料/说明.txt" --from "${ML_FIXTURES}/obj15/说明.txt"
    ml_run_ok "${root}" "${out}-show" show obj15
    ml_expect_contains "unicode directory appears" "${out}-show.stdout" "资料"
    ml_expect_contains "unicode file appears" "${out}-show.stdout" "说明.txt"
    ml_expect_contains "mandatory marker still appears" "${out}-show.stdout" "obj15.md"
    end_case
}

run_obj_16() {
    begin_case OBJ-16 P1 I
    local root="${ML_STORES}/OBJ-16/store"
    local out="${ML_CASE_DIR}/OBJ-16"

    # Empty store: both formats print an empty array.
    ml_run_ok "${root}" "${out}-empty-yaml" list
    ml_expect "empty yaml list is []" "[]" "$(tr -d '[:space:]' < "${out}-empty-yaml.stdout")"
    ml_run_ok "${root}" "${out}-empty-json" list --format json
    ml_expect "empty json list is []" "[]" "$(tr -d '[:space:]' < "${out}-empty-json.stdout")"
    ml_run_ok "${root}" "${out}-empty-search" search nothing
    ml_expect "empty search is []" "[]" "$(tr -d '[:space:]' < "${out}-empty-search.stdout")"

    # Populated store: JSON is parseable and uses snake_case fields.
    ml_make_markdown "${ML_FIXTURES}/obj16/note.md" "obj16 description" "# obj16"
    ml_run_ok "${root}" "${out}-create" create obj16 --tag t1 --from "${ML_FIXTURES}/obj16/note.md"
    ml_run_ok "${root}" "${out}-json" list --format json
    ml_expect "json list parses" "1" "$(jq 'length' "${out}-json.stdout")"
    local field
    for field in id name path description status tags created_at updated_at schema_version data_ref; do
        ml_expect "json exposes ${field}" "true" \
            "$(jq --arg f "${field}" '.[0] | has($f)' "${out}-json.stdout")"
    done
    ml_expect "json has no PascalCase keys" "false" \
        "$(jq '.[0] | has("ID") or has("Name") or has("Path")' "${out}-json.stdout")"

    # YAML is parseable through a YAML reader.
    ml_run_ok "${root}" "${out}-yaml" list
    ml_expect_contains "yaml list starts with a sequence" "${out}-yaml.stdout" "- id: obj16"
    ml_expect_contains "yaml list exposes snake_case keys" "${out}-yaml.stdout" "schema_version: 2"

    # Diagnostics stay on stderr and never contaminate stdout.
    ml_run_ok "${root}" "${out}-search" search obj16 --format json
    ml_expect "search json parses" "1" "$(jq 'length' "${out}-search.stdout")"
    end_case
}

CASES=(OBJ-01 OBJ-02 OBJ-03 OBJ-04 OBJ-05 OBJ-06 OBJ-07 OBJ-08 OBJ-09 \
       OBJ-10 OBJ-11 OBJ-12 OBJ-13 OBJ-14 OBJ-15 OBJ-16)
for case_id in "${CASES[@]}"; do
    if ! selected "${case_id}" "$@"; then
        continue
    fi
    case "${case_id}" in
        OBJ-01) run_obj_01 ;;
        OBJ-02) run_obj_02 ;;
        OBJ-03) run_obj_03 ;;
        OBJ-04) run_obj_04 ;;
        OBJ-05) run_obj_05 ;;
        OBJ-06) run_obj_06 ;;
        OBJ-07) run_obj_07 ;;
        OBJ-08) run_obj_08 ;;
        OBJ-09) run_obj_09 ;;
        OBJ-10) run_obj_10 ;;
        OBJ-11) run_obj_11 ;;
        OBJ-12) run_obj_12 ;;
        OBJ-13) run_obj_13 ;;
        OBJ-14) run_obj_14 ;;
        OBJ-15) run_obj_15 ;;
        OBJ-16) run_obj_16 ;;
    esac
done
