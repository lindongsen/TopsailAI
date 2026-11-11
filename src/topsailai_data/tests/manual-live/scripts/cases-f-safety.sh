#!/usr/bin/env bash
# cases-f-safety: manual/live safety cases SAFE-01..SAFE-08.
#
# Scope: SAFE-01..SAFE-08 from tests/manual-live/safety-scale-live.md.
# Every case runs against an isolated store under .tmp/manual-live/<run>/stores.
# No case reads or writes the live store, and no case deletes shared resources.
#
# Usage:
#   ML_RUN_ID=<id> bash tests/manual-live/scripts/cases-f-safety.sh [case ids...]

set -uo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1

# shellcheck source=lib.sh
source "${EXE_FOLDER}/lib.sh"

ml_init

# selected reports whether a case id was requested on the command line.
selected() {
    local case_id="$1"
    shift
    if [[ $# -eq 0 ]]; then
        return 0
    fi
    local item
    for item in "$@"; do
        if [[ "${item}" == "${case_id}" ]]; then
            return 0
        fi
    done
    return 1
}

# count_glob counts entries in a directory whose name matches a glob.
#
# A "compgen -G | wc -l" pipeline cannot be used here: the harness runs under
# "set -euo pipefail", so a glob with no match makes the pipeline fail and
# silently truncates the case instead of reporting a failure.
count_glob() {
    local dir="$1" pattern="$2"
    local n=0 f
    for f in "${dir}"/${pattern}; do
        [[ -e "${f}" ]] || continue
        n=$((n + 1))
    done
    printf '%s' "${n}"
}

# file_sha prints the sha256 of a file, or "absent" when it does not exist.
file_sha() {
    local path="$1"
    if [[ ! -f "${path}" ]]; then
        printf 'absent'
        return 0
    fi
    sha256sum "${path}" | awk '{print $1}'
}

# file_bytes prints the byte size of a file, or -1 when it does not exist.
file_bytes() {
    local path="$1"
    if [[ ! -f "${path}" ]]; then
        printf '%s' '-1'
        return 0
    fi
    wc -c < "${path}" | tr -d ' '
}

# payload_path prints the payload directory of an object, including deleted ones.
payload_path() {
    local root="$1" id="$2"
    local path
    path=$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --include-deleted --format json 2>/dev/null \
        | jq -r --arg id "${id}" '.[] | select(.id==$id) | .path' 2>/dev/null || true)
    if [[ -z "${path}" || "${path}" == "null" ]]; then
        return 1
    fi
    printf '%s/object/%s' "${root}" "${path}"
}
# show_field prints one "Field: value" value from the show output of an object.
#
# The full output is captured before parsing. Piping show directly into an awk
# that exits on the first match closes the pipe early, and the CLI then dies
# with SIGPIPE, which "pipefail" turns into a 141 exit for the whole case.
show_field() {
    local root="$1" id="$2" field="$3"
    local text
    text=$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" show "${id}" 2>/dev/null || true)
    printf '%s\n' "${text}" \
        | awk -v f="${field}:" '$1==f{$1="";sub(/^[[:space:]]+/,"");print;exit}'
}

# run_nobody_ok runs the CLI as nobody and fails the case on a non-zero exit.
run_nobody_ok() {
    local root="$1" prefix="$2"
    shift 2
    local code=0
    ml_run_nobody "${root}" "${prefix}" "$@" || code=$?
    if [[ "${code}" -ne 0 ]]; then
        ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
        printf 'FAIL: command expected success as nobody but exited %s: %s\n' "${code}" "$*" >> "${ML_CASE_LOG}"
        sed -n '1,20p' "${prefix}.stderr" >> "${ML_CASE_LOG}" || true
    fi
    return 0
}

# run_nobody_fail runs the CLI as nobody and fails the case on a zero exit.
run_nobody_fail() {
    local root="$1" prefix="$2"
    shift 2
    local code=0
    ml_run_nobody "${root}" "${prefix}" "$@" || code=$?
    if [[ "${code}" -eq 0 ]]; then
        ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
        printf 'FAIL: command expected failure as nobody but succeeded: %s\n' "$*" >> "${ML_CASE_LOG}"
    fi
    return 0
}

# corrupt_metadata rewrites the metadata record of an object with a jq filter.
corrupt_metadata() {
    local root="$1" id="$2" filter="$3"
    local md
    md=$(ml_meta_dir "${root}" "${id}")
    jq "${filter}" "${md}/metadata.json" > "${md}/metadata.json.new"
    mv "${md}/metadata.json.new" "${md}/metadata.json"
}

# restore_metadata puts a saved metadata record back in place.
restore_metadata() {
    local root="$1" id="$2" saved="$3"
    local md
    md=$(ml_meta_dir "${root}" "${id}")
    rm -rf "${md}/metadata.json"
    cp "${saved}" "${md}/metadata.json"
}

# run_safe_01 proves that a write cannot destroy its own source and that an
# interrupted write leaves the previous payload intact.
run_safe_01() {
    begin_case SAFE-01 P0 F
    local root out
    root=$(ml_case_root safe01)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/b.md" "safe01 fixture" "ORIGINAL"
    ml_run_ok "${root}" "${out}/create" create b --from "${out}/b.md"

    local pd
    pd=$(payload_path "${root}" b)
    ml_expect_file "the payload directory exists" "${pd}" dir
    local orig_sha
    orig_sha=$(file_sha "${pd}/b.md")

    ml_run_fail "${root}" "${out}/same" put b b.md --from "${pd}/b.md"
    ml_expect_contains "a same-path source is refused" "${out}/same.stderr" \
        "source and destination are the same file"
    ml_expect "the same-path refusal leaves the payload unchanged" "${orig_sha}" \
        "$(file_sha "${pd}/b.md")"

    ln -sfn "${pd}/b.md" "${out}/alias.md"
    ml_run_fail "${root}" "${out}/sym" put b b.md --from "${out}/alias.md"
    ml_expect_contains "a symlink alias is refused" "${out}/sym.stderr" \
        "source and destination are the same file"
    ml_expect "the symlink refusal leaves the payload unchanged" "${orig_sha}" \
        "$(file_sha "${pd}/b.md")"

    ln -f "${pd}/b.md" "${out}/hard.md"
    ml_run_fail "${root}" "${out}/hard" put b b.md --from "${out}/hard.md"
    ml_expect_contains "a hardlink alias is refused" "${out}/hard.stderr" \
        "source and destination are the same file"
    ml_expect "the hardlink refusal leaves the payload unchanged" "${orig_sha}" \
        "$(file_sha "${pd}/b.md")"

    # A FIFO blocks the writer after the temporary file is created, so the
    # interruption happens at a known point instead of racing a fast write.
    mkfifo "${out}/fifo"
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC \
        TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" put b b.md --from "${out}/fifo" \
        > "${out}/interrupt.stdout" 2> "${out}/interrupt.stderr" &
    local writer_pid=$!
    exec 8> "${out}/fifo"
    printf 'PARTIAL-DATA' >&8
    local waited=0
    while [[ "${waited}" -lt 500 ]]; do
        if [[ "$(count_glob "${pd}" '.topsailai-data-write-*')" -gt 0 ]]; then
            break
        fi
        sleep 0.01
        waited=$((waited + 1))
    done
    ml_expect "a reserved temporary file appears during the write" "yes" \
        "$([[ "$(count_glob "${pd}" '.topsailai-data-write-*')" -gt 0 ]] && echo yes || echo no)"

    kill -TERM "${writer_pid}" 2>/dev/null || true
    exec 8>&-
    local code=0
    wait "${writer_pid}" 2>/dev/null || code=$?
    ml_expect "the interrupted write exits non-zero" "yes" \
        "$([[ "${code}" -ne 0 ]] && echo yes || echo no)"
    ml_expect "the interrupted write leaves the old payload digest unchanged" "${orig_sha}" \
        "$(file_sha "${pd}/b.md")"
    ml_expect "the interrupted write leaves a reserved temporary file behind" "yes" \
        "$([[ "$(count_glob "${pd}" '.topsailai-data-write-*')" -gt 0 ]] && echo yes || echo no)"
    ml_note "reserved .topsailai-data-write-* files are removed recursively at object cleanup/GC boundaries after 24 hours, so an interrupted write leaves one until then"

    ml_run_ok "${root}" "${out}/after" get b b.md
    ml_expect_contains "reads still return the old payload after the interruption" \
        "${out}/after.stdout" "ORIGINAL"
    ml_run_ok "${root}" "${out}/show" show b
    ml_expect_not_contains "the folder tree hides the reserved temporary file" \
        "${out}/show.stdout" ".topsailai-data-write-"
    end_case
}

# run_safe_02 proves that a metadata publication fault is reported and that the
# already-written payload is not rolled back.
run_safe_02() {
    begin_case SAFE-02 P0 F
    local root out
    root=$(ml_case_root safe02)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/b.md" "safe02 fixture" "ORIGINAL"
    ml_run_ok "${root}" "${out}/create" create b --from "${out}/b.md"

    local pd md before
    pd=$(payload_path "${root}" b)
    md=$(ml_meta_dir "${root}" b)
    before=$(file_sha "${pd}/b.md")

    printf 'NEWCONTENT\n' > "${out}/new.txt"
    ml_chown_nobody "${root}"
    chmod 0555 "${md}"
    run_nobody_fail "${root}" "${out}/put" put b b.md --from "${out}/new.txt"
    chmod 0755 "${md}"

    ml_expect_contains "the publication fault is reported" "${out}/put.stderr" \
        "create temporary metadata record"
    ml_expect_contains "the publication fault names the permission problem" \
        "${out}/put.stderr" "permission denied"
    ml_expect "the already-written payload is not rolled back" "yes" \
        "$([[ "$(file_sha "${pd}/b.md")" != "${before}" ]] && echo yes || echo no)"
    ml_expect "the failed publication leaves no reserved temporary file" "0" \
        "$(count_glob "${pd}" '.topsailai-data-write-*')"
    ml_expect "the metadata record stays readable after the fault" "active" \
        "$(show_field "${root}" b Status)"
    ml_note "the actual data is written before metadata publication, so a publication fault leaves the new payload in place with no rollback promise"
    end_case
}

# run_safe_03 proves that a move publication fault keeps the source authoritative
# and reports the retained target copy.
run_safe_03() {
    begin_case SAFE-03 P0 F
    local root out
    root=$(ml_case_root safe03)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/m.md" "safe03 fixture" "MOVE-BODY"
    ml_run_ok "${root}" "${out}/create" create m --from "${out}/m.md"

    local pd md src_path
    pd=$(payload_path "${root}" m)
    md=$(ml_meta_dir "${root}" m)
    src_path=$(show_field "${root}" m Path)

    ml_chown_nobody "${root}"
    chmod 0555 "${md}"
    run_nobody_fail "${root}" "${out}/move" move m archive
    chmod 0755 "${md}"

    ml_expect_contains "the move publication fault is reported" "${out}/move.stderr" \
        "publish move metadata"
    ml_expect_contains "the move fault states that both copies are retained" \
        "${out}/move.stderr" "source and target retained"
    ml_expect_file "the source payload is retained" "${pd}" dir
    ml_expect_file "the target copy is retained for reconciliation" \
        "${root}/object/$(dirname "${src_path}")/archive/m" dir
    ml_expect "the metadata still points at the source path" "${src_path}" \
        "$(show_field "${root}" m Path)"
    ml_run_ok "${root}" "${out}/list" list --format json
    ml_expect "the listing still reports the source path" "${src_path}" \
        "$(jq -r '.[] | select(.id=="m") | .path' "${out}/list.stdout")"
    ml_note "a move publication fault leaves the target copy on disk; it must be reconciled or cleaned up explicitly"
    end_case
}

# run_safe_04 proves that a failed tag publication reports the exact state and
# never fabricates cross-file atomicity.
run_safe_04() {
    begin_case SAFE-04 P0 F
    local root out
    root=$(ml_case_root safe04)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/t.md" "safe04 fixture" "TAG-BODY"
    ml_run_ok "${root}" "${out}/create" create t --from "${out}/t.md"

    local md
    md=$(ml_meta_dir "${root}" t)

    ml_chown_nobody "${root}"
    chmod 0555 "${md}"
    run_nobody_fail "${root}" "${out}/tag" tag add t locked
    chmod 0755 "${md}"

    ml_expect_contains "the tag publication fault is reported" "${out}/tag.stderr" \
        "create temporary tags"
    ml_expect_contains "the tag fault names the permission problem" \
        "${out}/tag.stderr" "permission denied"
    ml_expect "the failed tag publication leaves an empty tag file" "0" \
        "$(file_bytes "${md}/tags")"
    ml_expect "the failed tag publication exposes no tag" "" \
        "$(show_field "${root}" t Tags)"
    ml_note "tags are published through a temporary file plus rename, so a failed publication leaves no partial tag"
    end_case
}

# run_safe_05 proves that an interior payload alias is refused by every
# single-file and move path while external sentinels stay untouched.
run_safe_05() {
    begin_case SAFE-05 P0 F
    local root out
    root=$(ml_case_root safe05)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/a.md" "safe05 fixture" "ALIAS-BODY"
    ml_run_ok "${root}" "${out}/create" create a --from "${out}/a.md"

    local pd src_path
    pd=$(payload_path "${root}" a)
    src_path=$(show_field "${root}" a Path)

    printf 'SENTINEL\n' > "${out}/outside.txt"
    ln -s "${out}/outside.txt" "${pd}/link.txt"

    ml_run_fail "${root}" "${out}/get" get a link.txt
    ml_expect_contains "a single-file read refuses the payload alias" "${out}/get.stderr" \
        "payload alias"
    ml_expect_contains "the refused read names an invalid path" "${out}/get.stderr" \
        "invalid path"

    ml_run_fail "${root}" "${out}/read" file read link.txt --object a
    ml_expect_contains "the file read command refuses the payload alias" \
        "${out}/read.stderr" "payload alias"

    ml_run_fail "${root}" "${out}/write" file write link.txt --object a --from "${out}/a.md"
    ml_expect_contains "the file write command refuses the payload alias" \
        "${out}/write.stderr" "payload alias"

    ml_run_fail "${root}" "${out}/move" move a archive
    ml_expect_contains "the move refuses to copy the payload alias" "${out}/move.stderr" \
        "unsafe copy source"
    ml_expect_contains "the refused move names an invalid path" "${out}/move.stderr" \
        "invalid path"

    ml_expect "the external sentinel is unchanged" "SENTINEL" "$(cat "${out}/outside.txt")"

    ml_run_ok "${root}" "${out}/archive" get-archive a
    tar -tvf "${out}/archive.stdout" > "${out}/archive.list" 2>/dev/null || true
    ml_expect_contains "the archive still contains the alias entry" "${out}/archive.list" "link.txt"
    ml_expect_contains "the archive stores the alias as a symlink entry" "${out}/archive.list" \
        "lrwxrwxrwx"
    ml_note "get-archive packages an interior symlink verbatim while get, file read, file write and move all refuse it; the archive read path and the single-file read path apply different safety policies"

    ml_run_ok "${root}" "${out}/show" show a
    ml_expect_contains "the folder tree lists the alias without expanding it" \
        "${out}/show.stdout" "link.txt"
    ml_expect "the metadata still points at the original path" "${src_path}" \
        "$(show_field "${root}" a Path)"
    end_case
}

# run_safe_06 proves that corrupt metadata produces a clear corruption result and
# that a listing never silently accepts a missing inventory.
run_safe_06() {
    begin_case SAFE-06 P1 F
    local root out
    root=$(ml_case_root safe06)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/b.md" "safe06 fixture" "CORRUPT-BODY"
    ml_run_ok "${root}" "${out}/create" create b --from "${out}/b.md"

    local md pd
    md=$(ml_meta_dir "${root}" b)
    pd=$(payload_path "${root}" b)
    cp "${md}/metadata.json" "${out}/orig.json"

    # Each variant must start from the pristine record. corrupt_metadata mutates
    # in place, so without a restore the object_id added by the first variant
    # would survive into every later one and mask its own expected message.
    restore_metadata "${root}" b "${out}/orig.json"
    corrupt_metadata "${root}" b '. + {object_id:"b"}'
    ml_run_fail "${root}" "${out}/unknown-id" show b
    ml_expect_contains "an unknown object_id field is rejected" "${out}/unknown-id.stderr" \
        'unknown field "object_id"'

    restore_metadata "${root}" b "${out}/orig.json"
    corrupt_metadata "${root}" b '. + {mystery_field:1}'
    ml_run_fail "${root}" "${out}/unknown-mystery" show b
    ml_expect_contains "an unknown field is rejected" "${out}/unknown-mystery.stderr" \
        'unknown field "mystery_field"'

    restore_metadata "${root}" b "${out}/orig.json"
    corrupt_metadata "${root}" b '. + {schema_version:2}'
    ml_run_fail "${root}" "${out}/unknown-schema" show b
    ml_expect_contains "an unknown schema_version field is rejected" \
        "${out}/unknown-schema.stderr" 'unknown field "schema_version"'

    restore_metadata "${root}" b "${out}/orig.json"
    corrupt_metadata "${root}" b '.Name="other"'
    ml_run_fail "${root}" "${out}/name" show b
    ml_expect_contains "a name that differs from the ID is rejected" "${out}/name.stderr" \
        "metadata name differs from ID"

    restore_metadata "${root}" b "${out}/orig.json"
    corrupt_metadata "${root}" b '.SchemaVersion=99'
    ml_run_fail "${root}" "${out}/schema" show b
    ml_expect_contains "an unsupported schema version is rejected" "${out}/schema.stderr" \
        "unsupported object schema 99"

    restore_metadata "${root}" b "${out}/orig.json"
    corrupt_metadata "${root}" b '.DataRef="2026/1111/1831/other"'
    ml_run_fail "${root}" "${out}/ref" show b
    ml_expect_contains "a reference that differs from the identity is rejected" \
        "${out}/ref.stderr" "metadata path and reference differ from object identity"

    restore_metadata "${root}" b "${out}/orig.json"
    corrupt_metadata "${root}" b '.Status="bogus"'
    ml_run_fail "${root}" "${out}/status" show b
    ml_expect_contains "an unknown status is rejected" "${out}/status.stderr" \
        'unknown object status "bogus"'

    restore_metadata "${root}" b "${out}/orig.json"
    corrupt_metadata "${root}" b '.Path="../escape"'
    ml_run_fail "${root}" "${out}/path" show b
    ml_expect_contains "an escaping metadata path is rejected" "${out}/path.stderr" \
        "object reference depth 2"

    restore_metadata "${root}" b "${out}/orig.json"
    head -c 40 "${out}/orig.json" > "${md}/metadata.json"
    ml_run_fail "${root}" "${out}/truncated" show b
    ml_expect_contains "a truncated record is rejected" "${out}/truncated.stderr" \
        "unexpected EOF"

    restore_metadata "${root}" b "${out}/orig.json"
    rm -f "${md}/metadata.json"
    ml_run_fail "${root}" "${out}/missing" show b
    ml_expect_contains "a missing record reports a missing object" "${out}/missing.stderr" \
        "object not found"

    restore_metadata "${root}" b "${out}/orig.json"
    rm -f "${md}/metadata.json"
    mkdir -p "${md}/metadata.json"
    ml_run_fail "${root}" "${out}/isdir" show b
    ml_expect_contains "a record that is a directory is rejected" "${out}/isdir.stderr" \
        "must be regular"
    rm -rf "${md}/metadata.json"
    cp "${out}/orig.json" "${md}/metadata.json"

    corrupt_metadata "${root}" b '. + {object_id:"b"}'
    ml_run_fail "${root}" "${out}/list" list
    ml_expect "a corrupt record makes the listing fail" "0" \
        "$(file_bytes "${out}/list.stdout")"
    ml_expect_contains "the listing failure names the corrupt leaf" "${out}/list.stderr" \
        "corrupted metadata"
    ml_run_fail "${root}" "${out}/search" search b
    ml_expect "a corrupt record makes the search fail" "0" \
        "$(file_bytes "${out}/search.stdout")"
    ml_note "a corrupt record fails the whole listing instead of being skipped, so a missing inventory is never silently accepted"

    restore_metadata "${root}" b "${out}/orig.json"
    ml_run_ok "${root}" "${out}/list-ok" list --format json
    ml_expect "the listing recovers once the record is restored" "b" \
        "$(jq -r '.[].id' "${out}/list-ok.stdout")"

    mv "${pd}" "${out}/payload.bak"
    ml_run_ok "${root}" "${out}/nopayload-show" show b
    ml_expect "the metadata still resolves without a payload" "active" \
        "$(show_field "${root}" b Status)"
    ml_run_fail "${root}" "${out}/nopayload-get" get b b.md
    ml_expect_contains "a read without a payload reports a missing file" \
        "${out}/nopayload-get.stderr" "object not found"
    ml_run_ok "${root}" "${out}/nopayload-list" list --format json
    ml_expect "the listing still reports the object without a payload" "b" \
        "$(jq -r '.[].id' "${out}/nopayload-list.stdout")"
    mv "${out}/payload.bak" "${pd}"
    end_case
}

# run_safe_07 proves that permission faults are real, actionable and never
# reported as success.
run_safe_07() {
    begin_case SAFE-07 P1 F
    local root out
    root=$(ml_case_root safe07)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/n.md" "safe07 fixture" "PERM-BODY"

    # Variant A: the store root, the payload root and the metadata root are all
    # read-only for the unprivileged user, so initialization cannot create the
    # metadata lock directory. Tightening only the root is not enough: the
    # subdirectories stay writable and the create would succeed.
    ml_run_ok "${root}" "${out}/init" list
    ml_chown_nobody "${root}"
    chmod 0555 "${root}" "${root}/object" "${root}/meta"
    run_nobody_fail "${root}" "${out}/create" create n --from "${out}/n.md"
    ml_expect_contains "a read-only store refuses creation" "${out}/create.stderr" \
        "create metadata lock directory"
    ml_expect_contains "the creation fault names the permission problem" \
        "${out}/create.stderr" "permission denied"
    run_nobody_ok "${root}" "${out}/list" list
    chmod 0755 "${root}" "${root}/object" "${root}/meta"

    # Variant B: only the target payload directory is read-only, so the failure
    # happens while creating the reserved temporary replacement file.
    local root_b out_b
    root_b=$(ml_case_root safe07b)
    out_b="${out}/variant-b"
    mkdir -p "${out_b}"
    ml_run_ok "${root_b}" "${out_b}/create" create p --from "${out}/n.md"
    local pd_b
    pd_b=$(payload_path "${root_b}" p)
    ml_chown_nobody "${root_b}"
    chmod 0555 "${pd_b}"
    run_nobody_fail "${root_b}" "${out_b}/put" put p extra.txt --from "${out}/n.md"
    chmod 0755 "${pd_b}"
    ml_expect_contains "a read-only payload directory refuses the write" \
        "${out_b}/put.stderr" "create temporary file"
    ml_expect_contains "the write fault names the permission problem" \
        "${out_b}/put.stderr" "permission denied"
    ml_note "a permission fault is proven by running as nobody against a read-only directory; tightening only the store root does not reproduce it because the subdirectories stay writable"
    end_case
}

# run_safe_08 proves that machine and binary output stays uncontaminated and that
# failures are reported only on stderr.
run_safe_08() {
    begin_case SAFE-08 P1 I
    local root out
    root=$(ml_case_root safe08)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/bin.md" "safe08 fixture" "BINARY-BODY"
    ml_run_ok "${root}" "${out}/create" create bin --from "${out}/bin.md"

    head -c 4096 /dev/urandom > "${out}/blob.bin"
    ml_run_ok "${root}" "${out}/put" put bin blob.bin --from "${out}/blob.bin"
    ml_run_ok "${root}" "${out}/get" get bin blob.bin

    ml_expect "the binary roundtrip preserves the digest" "$(file_sha "${out}/blob.bin")" \
        "$(file_sha "${out}/get.stdout")"
    ml_expect "a successful binary read writes nothing to stderr" "0" \
        "$(file_bytes "${out}/get.stderr")"

    ml_run_fail "${root}" "${out}/missing" get bin missing.txt
    ml_expect "a failed read writes nothing to stdout" "0" \
        "$(file_bytes "${out}/missing.stdout")"
    ml_expect_contains "the failure is reported on stderr" "${out}/missing.stderr" \
        "object not found"
    ml_expect_not_contains "the failure does not echo the stored payload" \
        "${out}/missing.stderr" "BINARY-BODY"
    ml_expect_not_contains "the failure does not echo the binary payload" \
        "${out}/missing.stderr" "$(head -c 16 "${out}/blob.bin" | base64)"
    end_case
}

CASES=(SAFE-01 SAFE-02 SAFE-03 SAFE-04 SAFE-05 SAFE-06 SAFE-07 SAFE-08)
for case_id in "${CASES[@]}"; do
    if ! selected "${case_id}" "$@"; then
        continue
    fi
    case "${case_id}" in
        SAFE-01) run_safe_01 ;;
        SAFE-02) run_safe_02 ;;
        SAFE-03) run_safe_03 ;;
        SAFE-04) run_safe_04 ;;
        SAFE-05) run_safe_05 ;;
        SAFE-06) run_safe_06 ;;
        SAFE-07) run_safe_07 ;;
        SAFE-08) run_safe_08 ;;
    esac
done

if grep -q '"status":"FAIL"' "${ML_RESULTS}" 2>/dev/null; then
    exit 1
fi
exit 0
