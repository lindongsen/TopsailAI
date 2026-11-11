#!/usr/bin/env bash
# cases-c-files: manual/live cases for the object file tool and archives.
#
# Scope: FILE-01..FILE-23 from tests/manual-live/files-archives.md.
# Every case runs against an isolated store under .tmp/manual-live/<run>/stores.
# No case reads or writes the live store.
#
# Usage:
#   ML_RUN_ID=<id> bash tests/manual-live/scripts/cases-c-files.sh [case ids...]

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

# json_field prints one field of one object from an include-deleted listing.
json_field() {
    local root="$1" id="$2" field="$3"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --include-deleted --format json 2>/dev/null \
        | jq -r --arg id "${id}" --arg f "${field}" '.[] | select(.id==$id) | .[$f]'
}

# json_count prints the number of objects in an include-deleted listing.
json_count() {
    local root="$1"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --include-deleted --format json 2>/dev/null \
        | jq 'length'
}

# sha_of prints the sha256 of a file.
sha_of() {
    sha256sum "$1" | awk '{print $1}'
}

# size_of prints the byte size of a file.
size_of() {
    wc -c < "$1" | tr -d ' '
}

# make_object creates one object with a markdown marker and a description.
make_object() {
    local root="$1" id="$2" out="$3"
    ml_make_markdown "${ML_FIXTURES}/c/${id}.md" "${id} fixture" "# ${id}"
    ml_run_ok "${root}" "${out}-create" create "${id}" --from "${ML_FIXTURES}/c/${id}.md"
}

run_file_01() {
    begin_case FILE-01 P0 I
    local root="${ML_STORES}/FILE-01/store"
    local out="${ML_CASE_DIR}/FILE-01"
    make_object "${root}" file01 "${out}"

    # Binary, NUL-containing, unicode and empty payloads must round-trip byte-exactly.
    python3 -c "open('${ML_FIXTURES}/c/bin.dat','wb').write(bytes(range(256))*8)"
    printf 'nul\0inside\n' > "${ML_FIXTURES}/c/nul.dat"
    printf 'unicode 中文 标签\n' > "${ML_FIXTURES}/c/uni.dat"
    : > "${ML_FIXTURES}/c/empty.dat"

    local name
    for name in bin.dat nul.dat uni.dat empty.dat; do
        ml_run_ok "${root}" "${out}-put-${name}" put file01 "${name}" \
            --from "${ML_FIXTURES}/c/${name}"
        ml_run_ok "${root}" "${out}-get-${name}" get file01 "${name}"
        ml_expect_sha "get returns ${name} byte-exactly" "${out}-get-${name}.stdout" \
            "$(sha_of "${ML_FIXTURES}/c/${name}")"
        ml_expect "get returns ${name} at full length" "$(size_of "${ML_FIXTURES}/c/${name}")" \
            "$(size_of "${out}-get-${name}.stdout")"
    done

    # A fresh process must read the same bytes, proving nothing is cached in memory.
    ml_run_ok "${root}" "${out}-get-again" get file01 bin.dat
    ml_expect_sha "binary survives a new process" "${out}-get-again.stdout" \
        "$(sha_of "${ML_FIXTURES}/c/bin.dat")"

    # The marker file itself is ordinary data and stays readable.
    ml_run_ok "${root}" "${out}-get-marker" get file01 file01.md
    ml_expect_sha "marker is readable" "${out}-get-marker.stdout" \
        "$(sha_of "${ML_FIXTURES}/c/file01.md")"
    end_case
}

run_file_02() {
    begin_case FILE-02 P0 I
    local root="${ML_STORES}/FILE-02/store"
    local out="${ML_CASE_DIR}/FILE-02"
    make_object "${root}" file02 "${out}"
    printf 'sentinel\n' > "${ML_FIXTURES}/c/sentinel.txt"
    local sentinel_before
    sentinel_before=$(sha_of "${ML_FIXTURES}/c/sentinel.txt")

    # A nested destination is created on demand.
    ml_run_ok "${root}" "${out}-nested" put file02 deep/nested/note.txt \
        --from "${ML_FIXTURES}/c/sentinel.txt"
    ml_run_ok "${root}" "${out}-nested-get" get file02 deep/nested/note.txt
    ml_expect_sha "nested destination round-trips" "${out}-nested-get.stdout" "${sentinel_before}"

    # Unknown object and unknown file are refused.
    ml_run_fail "${root}" "${out}-no-object" put nosuchobj note.txt \
        --from "${ML_FIXTURES}/c/sentinel.txt"
    ml_expect_contains "unknown object is refused" "${out}-no-object.stderr" "object not found"
    ml_run_fail "${root}" "${out}-no-file" get file02 nosuch.txt
    ml_expect_contains "unknown file is refused" "${out}-no-file.stderr" "object not found"

    # Escaping the object root is refused and never reaches the host filesystem.
    ml_run_fail "${root}" "${out}-escape" put file02 ../escape.txt \
        --from "${ML_FIXTURES}/c/sentinel.txt"
    ml_expect_contains "escaping destination is refused" "${out}-escape.stderr" "invalid"
    ml_expect_file "no file escaped to the store root" "${root}/escape.txt" absent
    ml_expect_file "no file escaped to the run area" "${ML_BASE}/escape.txt" absent

    # Refusals must not create stray objects.
    ml_expect "no stray object was created" "1" "$(json_count "${root}")"
    ml_expect "source fixture is untouched" "${sentinel_before}" \
        "$(sha_of "${ML_FIXTURES}/c/sentinel.txt")"
    end_case
}

run_file_03() {
    begin_case FILE-03 P1 I
    local root="${ML_STORES}/FILE-03/store"
    local out="${ML_CASE_DIR}/FILE-03"
    make_object "${root}" file03 "${out}"

    # A byte-offset oracle: the payload is a known 26-byte alphabet.
    printf 'abcdefghijklmnopqrstuvwxyz' > "${ML_FIXTURES}/c/alpha.txt"
    ml_run_ok "${root}" "${out}-put" put file03 alpha.txt --from "${ML_FIXTURES}/c/alpha.txt"

    ml_run_ok "${root}" "${out}-whole" file read alpha.txt --object file03
    ml_expect "whole read returns the payload" "abcdefghijklmnopqrstuvwxyz" \
        "$(cat "${out}-whole.stdout")"

    ml_run_ok "${root}" "${out}-seek5" file read alpha.txt --object file03 --seek 5
    ml_expect "seek 5 starts at the sixth byte" "fghijklmnopqrstuvwxyz" \
        "$(cat "${out}-seek5.stdout")"

    ml_run_ok "${root}" "${out}-seek5size3" file read alpha.txt --object file03 --seek 5 --size 3
    ml_expect "seek plus size returns exactly three bytes" "fgh" \
        "$(cat "${out}-seek5size3.stdout")"

    ml_run_ok "${root}" "${out}-size4" file read alpha.txt --object file03 --size 4
    ml_expect "size alone reads from the start" "abcd" "$(cat "${out}-size4.stdout")"

    ml_run_ok "${root}" "${out}-seek0" file read alpha.txt --object file03 --seek 0
    ml_expect "seek 0 equals a whole read" "abcdefghijklmnopqrstuvwxyz" \
        "$(cat "${out}-seek0.stdout")"

    # A seek past the end yields nothing but is not an error.
    ml_run_ok "${root}" "${out}-seek99" file read alpha.txt --object file03 --seek 99
    ml_expect "seek past the end is empty" "0" "$(size_of "${out}-seek99.stdout")"

    # A negative seek counts from the end of the file rather than being refused.
    ml_run_ok "${root}" "${out}-negseek1" file read alpha.txt --object file03 --seek -1
    ml_expect "seek -1 reads the final byte" "z" "$(cat "${out}-negseek1.stdout")"

    ml_run_ok "${root}" "${out}-negseek5" file read alpha.txt --object file03 --seek -5
    ml_expect "seek -5 reads the final five bytes" "vwxyz" \
        "$(cat "${out}-negseek5.stdout")"

    # A size below -1 is the invalid value, not a negative seek.
    ml_run_fail "${root}" "${out}-badsize" file read alpha.txt --object file03 --size -2
    ml_expect_contains "size below -1 is refused" "${out}-badsize.stderr" "size"

    # The payload is unchanged by every read.
    ml_run_ok "${root}" "${out}-verify" get file03 alpha.txt
    ml_expect_sha "reads do not mutate the payload" "${out}-verify.stdout" \
        "$(sha_of "${ML_FIXTURES}/c/alpha.txt")"
    end_case
}

run_file_04() {
    begin_case FILE-04 P1 I
    local root="${ML_STORES}/FILE-04/store"
    local out="${ML_CASE_DIR}/FILE-04"
    make_object "${root}" file04 "${out}"

    # A non-whitelisted extension is truncated at the configured byte limit.
    python3 -c "open('${ML_FIXTURES}/c/big.bin','wb').write(bytes(range(256))*200)"
    ml_run_ok "${root}" "${out}-put" put file04 big.bin --from "${ML_FIXTURES}/c/big.bin"

    ml_run_ok "${root}" "${out}-default" file read big.bin --object file04
    ml_expect_contains "default read appends the truncation marker" "${out}-default.stdout" \
        "(force to truncate)"
    ml_expect "default read is bounded by the limit plus the marker" "30024" \
        "$(size_of "${out}-default.stdout")"

    # A custom limit changes the bound and keeps the marker.
    ml_run_ok "${root}" "${out}-custom" --env TOPSAILAI_DATA_FILE_MAX_BYTES=100 \
        file read big.bin --object file04
    ml_expect_contains "custom limit keeps the marker" "${out}-custom.stdout" \
        "(force to truncate)"
    ml_expect "custom limit bounds the output" "124" "$(size_of "${out}-custom.stdout")"

    # A limit larger than the payload must not truncate or add a marker. The
    # decoded text length differs from the raw byte length because encoding
    # detection may expand bytes, so the contract asserted here is stability:
    # repeated reads of identical bytes must produce identical output.
    ml_run_ok "${root}" "${out}-large" --env TOPSAILAI_DATA_FILE_MAX_BYTES=100000 \
        file read big.bin --object file04
    ml_expect_not_contains "a large limit adds no marker" "${out}-large.stdout" \
        "(force to truncate)"
    local large_sha
    large_sha=$(sha_of "${out}-large.stdout")
    local run
    for run in 1 2 3; do
        ml_run_ok "${root}" "${out}-large-${run}" --env TOPSAILAI_DATA_FILE_MAX_BYTES=100000 \
            file read big.bin --object file04
        ml_expect_sha "repeated large reads are byte-identical (run ${run})" \
            "${out}-large-${run}.stdout" "${large_sha}"
    done

    # The default limit is stable too, so truncation cannot drift between runs.
    local default_sha
    default_sha=$(sha_of "${out}-default.stdout")
    for run in 1 2 3; do
        ml_run_ok "${root}" "${out}-default-${run}" file read big.bin --object file04
        ml_expect_sha "repeated default reads are byte-identical (run ${run})" \
            "${out}-default-${run}.stdout" "${default_sha}"
    done

    # get stays raw regardless of the limit.
    ml_run_ok "${root}" "${out}-raw" --env TOPSAILAI_DATA_FILE_MAX_BYTES=100 \
        get file04 big.bin
    ml_expect_sha "get ignores the read limit" "${out}-raw.stdout" \
        "$(sha_of "${ML_FIXTURES}/c/big.bin")"
    ml_expect "get returns the full payload" "51200" "$(size_of "${out}-raw.stdout")"

    # A whitelisted markdown file is never truncated.
    ml_run_ok "${root}" "${out}-md" file read file04.md --object file04
    ml_expect_not_contains "markdown is not truncated" "${out}-md.stdout" "(force to truncate)"
    end_case
}

run_file_05() {
    begin_case FILE-05 P1 I
    local root="${ML_STORES}/FILE-05/store"
    local out="${ML_CASE_DIR}/FILE-05"
    make_object "${root}" file05 "${out}"
    printf 'l1\nl2\nl3\nl4\nl5\n' > "${ML_FIXTURES}/c/lines.txt"
    ml_run_ok "${root}" "${out}-put" put file05 lines.txt --from "${ML_FIXTURES}/c/lines.txt"

    # Numbering is one-based and rendered as "N-content".
    ml_run_ok "${root}" "${out}-start1" file read-lines lines.txt --object file05 --start 1
    ml_expect "start 1 prints the first numbered line" "1-l1" "$(cat "${out}-start1.stdout")"

    ml_run_ok "${root}" "${out}-start3" file read-lines lines.txt --object file05 --start 3
    ml_expect "start 3 prints from the third line" "3-l3" "$(cat "${out}-start3.stdout")"

    # An omitted end reads only the start line.
    ml_run_ok "${root}" "${out}-noend" file read-lines lines.txt --object file05 --start 2
    ml_expect "omitted end reads one line" "2-l2" "$(cat "${out}-noend.stdout")"

    # --end 0 behaves like an omitted end.
    ml_run_ok "${root}" "${out}-end0" file read-lines lines.txt --object file05 --start 2 --end 0
    ml_expect "end 0 reads one line" "2-l2" "$(cat "${out}-end0.stdout")"

    # --end -1 reads through the end of the file.
    ml_run_ok "${root}" "${out}-end-1" file read-lines lines.txt --object file05 --start 2 --end -1
    ml_expect "end -1 reads through the end" "2-l2
3-l3
4-l4
5-l5" "$(cat "${out}-end-1.stdout")"

    # A positive end is inclusive.
    ml_run_ok "${root}" "${out}-range" file read-lines lines.txt --object file05 --start 2 --end 4
    ml_expect "positive end is inclusive" "2-l2
3-l3
4-l4" "$(cat "${out}-range.stdout")"

    # --start 0 is normalized to the first line.
    ml_run_ok "${root}" "${out}-start0" file read-lines lines.txt --object file05 --start 0
    ml_expect "start 0 normalizes to line one" "1-l1" "$(cat "${out}-start0.stdout")"

    # A start past the end yields nothing without failing.
    ml_run_ok "${root}" "${out}-beyond" file read-lines lines.txt --object file05 --start 99
    ml_expect "start past the end is empty" "0" "$(size_of "${out}-beyond.stdout")"

    # An inverted range is refused.
    ml_run_fail "${root}" "${out}-inverted" file read-lines lines.txt --object file05 \
        --start 4 --end 2
    ml_expect_contains "inverted range is refused" "${out}-inverted.stderr" "invalid line range"

    # A missing file is refused.
    ml_run_fail "${root}" "${out}-missing" file read-lines nosuch.txt --object file05
    ml_expect_contains "missing file is refused" "${out}-missing.stderr" "object not found"
    end_case
}

run_file_06() {
    begin_case FILE-06 P1 I
    local root="${ML_STORES}/FILE-06/store"
    local out="${ML_CASE_DIR}/FILE-06"
    make_object "${root}" file06 "${out}"
    printf 'l1\nl2\nl3\nl4\nl5\n' > "${ML_FIXTURES}/c/lines.txt"
    ml_run_ok "${root}" "${out}-put" put file06 lines.txt --from "${ML_FIXTURES}/c/lines.txt"

    # read-around marks the target with a colon and context with a hyphen.
    ml_run_ok "${root}" "${out}-around" file read-around lines.txt 3 --object file06 --context 1
    ml_expect "read-around marks the target line" "2-l2
3:l3
4-l4" "$(cat "${out}-around.stdout")"

    # Context is clipped at the start of the file.
    ml_run_ok "${root}" "${out}-clip" file read-around lines.txt 1 --object file06 --context 2
    ml_expect "read-around clips at the file start" "1:l1
2-l2
3-l3" "$(cat "${out}-clip.stdout")"

    # Context is clipped at the end of the file.
    ml_run_ok "${root}" "${out}-clipend" file read-around lines.txt 5 --object file06 --context 2
    ml_expect "read-around clips at the file end" "3-l3
4-l4
5:l5" "$(cat "${out}-clipend.stdout")"

    # read-context is case-insensitive by default.
    ml_run_ok "${root}" "${out}-insens" file read-context lines.txt 'L3' --object file06 --context 1
    ml_expect "read-context is case-insensitive by default" "2-l2
3:l3
4-l4" "$(cat "${out}-insens.stdout")"

    # --case-sensitive narrows the match.
    ml_run_ok "${root}" "${out}-sens" file read-context lines.txt 'L3' --object file06 \
        --case-sensitive
    ml_expect "case-sensitive match finds nothing" "0" "$(size_of "${out}-sens.stdout")"

    ml_run_ok "${root}" "${out}-sens-hit" file read-context lines.txt 'l3' --object file06 \
        --case-sensitive --context 0
    ml_expect "case-sensitive match finds the exact line" "3:l3" "$(cat "${out}-sens-hit.stdout")"

    # Omitting --context prints the whole file with the match marked, so the
    # narrow single-line form must be requested explicitly with --context 0.
    ml_run_ok "${root}" "${out}-default-ctx" file read-context lines.txt 'l3' --object file06
    # The output has no trailing newline, so wc -l undercounts; awk counts records.
    ml_expect "omitted context prints every line" "5" \
        "$(awk 'END{print NR}' "${out}-default-ctx.stdout")"
    ml_expect_contains "omitted context still marks the match" "${out}-default-ctx.stdout" "3:l3"
    # A regex pattern is supported.
    ml_run_ok "${root}" "${out}-regex" file read-context lines.txt 'l[24]' --object file06 \
        --context 0
    ml_expect "regex matches both lines" "2:l2
4:l4" "$(cat "${out}-regex.stdout")"

    # A line number past the end is refused.
    ml_run_fail "${root}" "${out}-beyond" file read-around lines.txt 99 --object file06
    ml_expect_contains "read-around rejects an out-of-range line" "${out}-beyond.stderr" \
        "out of range"
    end_case
}

run_file_07() {
    begin_case FILE-07 P1 I
    local root="${ML_STORES}/FILE-07/store"
    local out="${ML_CASE_DIR}/FILE-07"
    make_object "${root}" file07 "${out}"
    printf 'l1\nl2\n' > "${ML_FIXTURES}/c/small.txt"
    : > "${ML_FIXTURES}/c/empty.txt"
    ml_run_ok "${root}" "${out}-put" put file07 small.txt --from "${ML_FIXTURES}/c/small.txt"
    ml_run_ok "${root}" "${out}-put-empty" put file07 empty.txt --from "${ML_FIXTURES}/c/empty.txt"
    local before
    before=$(sha_of "${ML_FIXTURES}/c/small.txt")

    # An invalid regex is refused with a clear message.
    ml_run_fail "${root}" "${out}-regex" file read-context small.txt '[' --object file07
    ml_expect_contains "invalid regex is refused" "${out}-regex.stderr" "invalid regular expression"

    # A negative context is accepted and behaves like zero: only the target line
    # is printed. It is not an error, so the assertion checks the output shape.
    ml_run_ok "${root}" "${out}-ctx" file read-around small.txt 1 --object file07 --context -1
    ml_expect "negative context prints only the target line" "1:l1" \
        "$(cat "${out}-ctx.stdout")"

    # Line zero is refused as a non-positive line number.
    ml_run_fail "${root}" "${out}-line0" file read-around small.txt 0 --object file07
    ml_expect_contains "line zero is refused" "${out}-line0.stderr" "positive line number"

    # An empty file yields empty output for every reader instead of panicking.
    ml_run_ok "${root}" "${out}-read" file read empty.txt --object file07
    ml_expect "empty file reads as empty" "0" "$(size_of "${out}-read.stdout")"
    ml_run_ok "${root}" "${out}-lines" file read-lines empty.txt --object file07 --start 1
    ml_expect "empty file has no lines" "0" "$(size_of "${out}-lines.stdout")"
    ml_run_ok "${root}" "${out}-size" file size empty.txt --object file07
    ml_expect "empty file size is zero" "0" "$(cat "${out}-size.stdout")"

    # No failure path mutated the payload.
    ml_run_ok "${root}" "${out}-verify" get file07 small.txt
    ml_expect_sha "failures do not mutate data" "${out}-verify.stdout" "${before}"
    end_case
}

run_file_08() {
    begin_case FILE-08 P1 I
    local root="${ML_STORES}/FILE-08/store"
    local out="${ML_CASE_DIR}/FILE-08"
    make_object "${root}" file08 "${out}"
    printf 'aaa\n' > "${ML_FIXTURES}/c/a.txt"
    printf 'bbb\n' > "${ML_FIXTURES}/c/b.txt"
    : > "${ML_FIXTURES}/c/empty.txt"
    ml_run_ok "${root}" "${out}-put-a" put file08 a.txt --from "${ML_FIXTURES}/c/a.txt"
    ml_run_ok "${root}" "${out}-put-b" put file08 b.txt --from "${ML_FIXTURES}/c/b.txt"
    ml_run_ok "${root}" "${out}-put-empty" put file08 empty.txt --from "${ML_FIXTURES}/c/empty.txt"

    # A mixed batch keeps per-item results instead of hiding the whole batch.
    ml_run_ok "${root}" "${out}-json" file read-files a.txt missing.txt empty.txt \
        --object file08 --format json
    # Command substitution strips trailing newlines, so the exact byte content is
    # checked through jq -j written to a file instead of a shell variable.
    jq -j '.["a.txt"]' "${out}-json.stdout" > "${out}-a-content"
    ml_expect "present file content keeps its trailing newline" "4" \
        "$(size_of "${out}-a-content")"
    ml_expect "present file content is returned" "aaa" \
        "$(jq -r '.["a.txt"]' "${out}-json.stdout")"
    ml_expect "empty file content is empty" "" "$(jq -r '.["empty.txt"]' "${out}-json.stdout")"
    ml_expect_contains "missing file keeps its own error" "${out}-json.stdout" "object not found"
    ml_expect "the batch still returns every requested key" "3" \
        "$(jq 'keys|length' "${out}-json.stdout")"

    # YAML output carries the same per-item results.
    ml_run_ok "${root}" "${out}-yaml" file read-files a.txt missing.txt --object file08
    ml_expect_contains "yaml keeps the present file" "${out}-yaml.stdout" "aaa"
    ml_expect_contains "yaml keeps the missing error" "${out}-yaml.stdout" "object not found"

    # A batch of only missing files still succeeds with per-item errors.
    ml_run_ok "${root}" "${out}-allmissing" file read-files nope1.txt nope2.txt \
        --object file08 --format json
    ml_expect "all-missing batch returns both keys" "2" \
        "$(jq 'keys|length' "${out}-allmissing.stdout")"
    ml_expect "all-missing batch reports errors per item" "2" \
        "$(jq '[.[]|select(test("object not found"))]|length' "${out}-allmissing.stdout")"

    # An empty request is refused rather than silently returning nothing.
    ml_run_fail "${root}" "${out}-none" file read-files --object file08
    ml_expect_contains "empty batch is refused" "${out}-none.stderr" "expected at least 1"
    end_case
}

CASES=(FILE-01 FILE-02 FILE-03 FILE-04 FILE-05 FILE-06 FILE-07 FILE-08)
for case_id in "${CASES[@]}"; do
    if ! selected "${case_id}" "$@"; then
        continue
    fi
    case "${case_id}" in
        FILE-01) run_file_01 ;;
        FILE-02) run_file_02 ;;
        FILE-03) run_file_03 ;;
        FILE-04) run_file_04 ;;
        FILE-05) run_file_05 ;;
        FILE-06) run_file_06 ;;
        FILE-07) run_file_07 ;;
        FILE-08) run_file_08 ;;
    esac
done

if grep -q '"status":"FAIL"' "${ML_RESULTS}" 2>/dev/null; then
    exit 1
fi
exit 0
