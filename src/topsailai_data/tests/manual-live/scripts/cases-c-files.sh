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


# obj_get prints one stored file through the CLI for intermediate assertions.
obj_get() {
    local root="$1" id="$2" name="$3"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" get "${id}" "${name}" 2>/dev/null
}

# obj_size prints the stored byte size of one file through the CLI.
obj_size() {
    local root="$1" id="$2" name="$3"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file size "${name}" --object "${id}" 2>/dev/null
}

run_file_09() {
    begin_case FILE-09 P1 I
    local root="${ML_STORES}/FILE-09/store"
    local out="${ML_CASE_DIR}/FILE-09"
    make_object "${root}" file09 "${out}"

    # A six-byte payload is the byte-model oracle for every write variant.
    printf 'abcdef' > "${ML_FIXTURES}/c/six.txt"
    ml_run_ok "${root}" "${out}-whole" file write six.txt --object file09 \
        --from "${ML_FIXTURES}/c/six.txt"
    ml_expect "whole write stores the payload" "abcdef" "$(obj_get "${root}" file09 six.txt)"
    ml_expect "whole write stores six bytes" "6" "$(obj_size "${root}" file09 six.txt)"

    # A positive seek overwrites from that byte offset and keeps the prefix.
    ml_run_ok "${root}" "${out}-seek3" file write six.txt --object file09 \
        --content 'ZZ' --seek 3
    ml_expect "seek 3 keeps the prefix and overwrites the tail" "abcZZf" \
        "$(obj_get "${root}" file09 six.txt)"

    # A negative seek counts from the end of the current six-byte content, so
    # offset 4 overwrites the fifth byte and leaves the rest untouched.
    ml_run_ok "${root}" "${out}-seekneg2" file write six.txt --object file09 \
        --content 'Q' --seek -2
    ml_expect "seek -2 overwrites the second-to-last byte" "abcZQf" \
        "$(obj_get "${root}" file09 six.txt)"

    # A seek before the start clamps to zero instead of failing.
    ml_run_ok "${root}" "${out}-seekneg99" file write six.txt --object file09 \
        --content 'X' --seek -99
    ml_expect "seek -99 clamps to the first byte" "XbcZQf" \
        "$(obj_get "${root}" file09 six.txt)"

    # A seek past the end appends rather than padding with holes.
    ml_run_ok "${root}" "${out}-seek99" file write six.txt --object file09 \
        --content 'Y' --seek 99
    ml_expect "seek past the end appends" "XbcZQfY" "$(obj_get "${root}" file09 six.txt)"
    ml_expect "seek past the end grows by the payload only" "7" \
        "$(obj_size "${root}" file09 six.txt)"

    # Append concatenates without touching the existing bytes.
    ml_run_ok "${root}" "${out}-append" file append six.txt --object file09 \
        --content 'TAIL'
    ml_expect "append concatenates" "XbcZQfYTAIL" "$(obj_get "${root}" file09 six.txt)"

    # A seek on a file that does not exist is refused instead of creating it.
    ml_run_fail "${root}" "${out}-seek-missing" file write absent.txt --object file09 \
        --content 'AB' --seek 5
    ml_expect_contains "seek on a missing file is refused" "${out}-seek-missing.stderr" \
        "object not found"
    ml_expect "the refused seek created no file" "false" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists absent.txt=absent.txt \
            --object file09 --format json 2>/dev/null | jq -r '."absent.txt"')"
    end_case
}

run_file_10() {
    begin_case FILE-10 P1 I
    local root="${ML_STORES}/FILE-10/store"
    local out="${ML_CASE_DIR}/FILE-10"
    make_object "${root}" file10 "${out}"

    printf 'FROMFILE' > "${ML_FIXTURES}/c/from.txt"
    printf 'STDINDATA' > "${ML_FIXTURES}/c/stdin.txt"

    # --from wins over --content when both are supplied.
    ml_run_ok "${root}" "${out}-from-wins" file write c.txt --object file10 \
        --from "${ML_FIXTURES}/c/from.txt" --content 'IGNORED'
    ml_expect "--from wins over --content" "FROMFILE" "$(obj_get "${root}" file10 c.txt)"

    # --from - also wins over --content, consuming stdin.
    ml_run_ok "${root}" "${out}-stdin-wins" --stdin "${ML_FIXTURES}/c/stdin.txt" \
        file write c.txt --object file10 --content 'IGNORED' --from -
    ml_expect "--from - wins over --content" "STDINDATA" "$(obj_get "${root}" file10 c.txt)"

    # An explicit empty --content wins over stdin and stores zero bytes.
    ml_run_ok "${root}" "${out}-empty-content" --stdin "${ML_FIXTURES}/c/stdin.txt" \
        file write c.txt --object file10 --content ''
    ml_expect "explicit empty --content wins over stdin" "0" \
        "$(obj_size "${root}" file10 c.txt)"

    # With no source flag the command reads stdin instead of hanging.
    ml_run_ok "${root}" "${out}-stdin-default" --stdin "${ML_FIXTURES}/c/stdin.txt" \
        file write c.txt --object file10
    ml_expect "no source flag reads stdin" "STDINDATA" "$(obj_get "${root}" file10 c.txt)"

    # With no source flag and no stdin the file becomes empty rather than blocking.
    ml_run_ok "${root}" "${out}-no-source" file write c.txt --object file10
    ml_expect "no source and no stdin stores zero bytes" "0" \
        "$(obj_size "${root}" file10 c.txt)"

    # The same precedence holds for append.
    ml_run_ok "${root}" "${out}-append-from" file append c.txt --object file10 \
        --from "${ML_FIXTURES}/c/from.txt" --content 'IGNORED'
    ml_expect "append honours --from over --content" "FROMFILE" \
        "$(obj_get "${root}" file10 c.txt)"

    # insert and overwrite-lines accept --content as well as --from.
    printf 'l1\nl2\n' > "${ML_FIXTURES}/c/two.txt"
    ml_run_ok "${root}" "${out}-lines" file write n.txt --object file10 \
        --from "${ML_FIXTURES}/c/two.txt"
    ml_run_ok "${root}" "${out}-insert-content" file insert n.txt 1 --object file10 \
        --content 'INS'
    ml_expect "insert accepts --content" "l1
INS
l2" "$(obj_get "${root}" file10 n.txt)"
    ml_run_ok "${root}" "${out}-ow-content" file overwrite-lines n.txt 2 --object file10 \
        --content 'OW'
    ml_expect "overwrite-lines accepts --content" "l1
OW
l2" "$(obj_get "${root}" file10 n.txt)"

    # put reads stdin both with an explicit --from - and with no --from at all.
    ml_run_ok "${root}" "${out}-put-stdin" --stdin "${ML_FIXTURES}/c/stdin.txt" \
        put file10 p1.txt --from -
    ml_expect "put --from - reads stdin" "STDINDATA" "$(obj_get "${root}" file10 p1.txt)"
    ml_run_ok "${root}" "${out}-put-default" --stdin "${ML_FIXTURES}/c/stdin.txt" \
        put file10 p2.txt
    ml_expect "put without --from reads stdin" "STDINDATA" "$(obj_get "${root}" file10 p2.txt)"
    end_case
}

run_file_11() {
    begin_case FILE-11 P0 I
    local root="${ML_STORES}/FILE-11/store"
    local out="${ML_CASE_DIR}/FILE-11"
    make_object "${root}" file11 "${out}"

    printf 'l1\nl2\nl3\nl4\n' > "${ML_FIXTURES}/c/four.txt"
    printf 'NEW2' > "${ML_FIXTURES}/c/new2.txt"
    printf 'R2\nR3' > "${ML_FIXTURES}/c/r23.txt"
    printf 'TAIL' > "${ML_FIXTURES}/c/tail.txt"
    printf 'INS' > "${ML_FIXTURES}/c/ins.txt"
    printf 'BEF' > "${ML_FIXTURES}/c/bef.txt"
    : > "${ML_FIXTURES}/c/empty.txt"

    # A single-line replacement keeps the surrounding lines intact.
    ml_run_ok "${root}" "${out}-seed" file write n.txt --object file11 \
        --from "${ML_FIXTURES}/c/four.txt"
    ml_run_ok "${root}" "${out}-single" file overwrite-lines n.txt 2 --object file11 \
        --from "${ML_FIXTURES}/c/new2.txt"
    ml_expect "single-line replacement keeps neighbours" "l1
NEW2
l3
l4" "$(obj_get "${root}" file11 n.txt)"
    ml_expect_contains "single-line replacement prints a unified diff" \
        "${out}-single.stdout" "--- before"
    ml_expect_contains "the diff names the target file" "${out}-single.stdout" "+++ n.txt"

    # A range replacement replaces every line in the inclusive range.
    ml_run_ok "${root}" "${out}-reseed" file write n.txt --object file11 \
        --from "${ML_FIXTURES}/c/four.txt"
    ml_run_ok "${root}" "${out}-range" file overwrite-lines n.txt 2 --object file11 \
        --from "${ML_FIXTURES}/c/r23.txt" --end 3
    ml_expect "range replacement replaces both lines" "l1
R2
R3
l4" "$(obj_get "${root}" file11 n.txt)"

    # --end -1 replaces through the end of the file.
    ml_run_ok "${root}" "${out}-reseed2" file write n.txt --object file11 \
        --from "${ML_FIXTURES}/c/four.txt"
    ml_run_ok "${root}" "${out}-toend" file overwrite-lines n.txt 2 --object file11 \
        --from "${ML_FIXTURES}/c/tail.txt" --end -1
    ml_expect "--end -1 replaces through the end" "l1
TAIL" "$(obj_get "${root}" file11 n.txt)"

    # An empty replacement deletes the addressed line.
    ml_run_ok "${root}" "${out}-reseed3" file write n.txt --object file11 \
        --from "${ML_FIXTURES}/c/four.txt"
    ml_run_ok "${root}" "${out}-delete-line" file overwrite-lines n.txt 2 --object file11 \
        --from "${ML_FIXTURES}/c/empty.txt"
    ml_expect "empty replacement deletes the line" "l1
l3
l4" "$(obj_get "${root}" file11 n.txt)"

    # insert defaults to after the addressed line.
    ml_run_ok "${root}" "${out}-reseed4" file write n.txt --object file11 \
        --from "${ML_FIXTURES}/c/four.txt"
    ml_run_ok "${root}" "${out}-insert-after" file insert n.txt 1 --object file11 \
        --from "${ML_FIXTURES}/c/ins.txt"
    ml_expect "insert defaults to after the line" "l1
INS
l2
l3
l4" "$(obj_get "${root}" file11 n.txt)"

    # --before inserts ahead of the addressed line.
    ml_run_ok "${root}" "${out}-reseed5" file write n.txt --object file11 \
        --from "${ML_FIXTURES}/c/four.txt"
    ml_run_ok "${root}" "${out}-insert-before" file insert n.txt 2 --object file11 \
        --from "${ML_FIXTURES}/c/bef.txt" --before
    ml_expect "--before inserts ahead of the line" "l1
BEF
l2
l3
l4" "$(obj_get "${root}" file11 n.txt)"

    # A line number past the end appends instead of failing.
    ml_run_ok "${root}" "${out}-reseed6" file write n.txt --object file11 \
        --from "${ML_FIXTURES}/c/four.txt"
    ml_run_ok "${root}" "${out}-insert-past" file insert n.txt 99 --object file11 \
        --from "${ML_FIXTURES}/c/ins.txt"
    ml_expect "insert past the end appends" "l1
l2
l3
l4
INS" "$(obj_get "${root}" file11 n.txt)"

    # Invalid boundaries are refused and leave the stored bytes untouched.
    ml_run_ok "${root}" "${out}-reseed7" file write n.txt --object file11 \
        --from "${ML_FIXTURES}/c/four.txt"
    local before after
    before=$(obj_get "${root}" file11 n.txt | sha256sum | awk '{print $1}')
    ml_run_fail "${root}" "${out}-bad-start0" file overwrite-lines n.txt 0 --object file11 \
        --content 'X'
    ml_expect_contains "start 0 is refused" "${out}-bad-start0.stderr" "must be >= 1"
    ml_run_fail "${root}" "${out}-bad-start99" file overwrite-lines n.txt 99 --object file11 \
        --content 'X'
    ml_expect_contains "start past the end is refused" "${out}-bad-start99.stderr" \
        "exceeds file length"
    ml_run_fail "${root}" "${out}-bad-range" file overwrite-lines n.txt 3 --object file11 \
        --content 'X' --end 2
    ml_expect_contains "reversed range is refused" "${out}-bad-range.stderr" \
        "start_num (3) > end_num (2)"
    ml_run_fail "${root}" "${out}-bad-insert0" file insert n.txt 0 --object file11 \
        --content 'X'
    ml_expect_contains "insert line 0 is refused" "${out}-bad-insert0.stderr" "must be >= 1"
    after=$(obj_get "${root}" file11 n.txt | sha256sum | awk '{print $1}')
    ml_expect "refused edits leave the file unchanged" "${before}" "${after}"
    end_case
}

run_file_12() {
    begin_case FILE-12 P1 I
    local root="${ML_STORES}/FILE-12/store"
    local out="${ML_CASE_DIR}/FILE-12"
    make_object "${root}" file12 "${out}"

    printf 'aaa' > "${ML_FIXTURES}/c/three.txt"
    ml_run_ok "${root}" "${out}-seed" put file12 a.txt --from "${ML_FIXTURES}/c/three.txt"

    # exists reports one boolean per requested name=path pair.
    ml_run_ok "${root}" "${out}-exists" file exists a.txt=a.txt missing.txt=missing.txt \
        --object file12 --format json
    ml_expect "exists reports a present file" "true" \
        "$(jq -r '."a.txt"' "${out}-exists.stdout")"
    ml_expect "exists reports a missing file" "false" \
        "$(jq -r '."missing.txt"' "${out}-exists.stdout")"

    # The left side is the reported key, so an alias can be probed.
    ml_run_ok "${root}" "${out}-alias" file exists alias=a.txt --object file12 --format json
    ml_expect "exists accepts an alias key" "true" \
        "$(jq -r '."alias"' "${out}-alias.stdout")"

    # A bare path without name=path is refused.
    ml_run_fail "${root}" "${out}-malformed" file exists a.txt --object file12
    ml_expect_contains "malformed exists argument is refused" "${out}-malformed.stderr" \
        "expected name=path"

    # size prints the exact byte count.
    ml_run_ok "${root}" "${out}-size" file size a.txt --object file12
    ml_expect "size prints the byte count" "3" "$(cat "${out}-size.stdout")"

    # size on a missing file fails with a useful message.
    ml_run_fail "${root}" "${out}-size-missing" file size nope.txt --object file12
    ml_expect_contains "size on a missing file is refused" "${out}-size-missing.stderr" \
        "object not found"

    # size has no --format flag, so the option is rejected rather than ignored.
    ml_run_fail "${root}" "${out}-size-format" file size a.txt --object file12 --format json
    ml_expect_contains "size rejects an unknown flag" "${out}-size-format.stderr" \
        "unknown flag"
    end_case
}

run_file_13() {
    begin_case FILE-13 P1 I
    local root="${ML_STORES}/FILE-13/store"
    local out="${ML_CASE_DIR}/FILE-13"
    make_object "${root}" file13 "${out}"

    # mkdirs creates every missing level and reports success.
    ml_run_ok "${root}" "${out}-mkdirs" file mkdirs d1/d2/d3 --object file13
    ml_expect "mkdirs reports OK" "OK" "$(cat "${out}-mkdirs.stdout")"

    # Each created level is discoverable through list-dirs.
    ml_run_ok "${root}" "${out}-list-root" file list-dirs . --object file13 --format json
    ml_expect "the first level is listed at the root" "true" \
        "$(jq -r '."." | index("d1") != null' "${out}-list-root.stdout")"
    ml_run_ok "${root}" "${out}-list-d1" file list-dirs d1 --object file13 --format json
    ml_expect "the second level is listed under d1" "true" \
        "$(jq -r '."d1" | index("d2") != null' "${out}-list-d1.stdout")"
    ml_run_ok "${root}" "${out}-list-d2" file list-dirs d1/d2 --object file13 --format json
    ml_expect "the third level is listed under d1/d2" "true" \
        "$(jq -r '."d1/d2" | index("d3") != null' "${out}-list-d2.stdout")"

    # An existing AGENTS.md marker is never overwritten by mkdirs.
    printf 'CUSTOM-MARKER' > "${ML_FIXTURES}/c/agents.txt"
    ml_run_ok "${root}" "${out}-seed-agents" put file13 d1/AGENTS.md \
        --from "${ML_FIXTURES}/c/agents.txt"
    ml_run_ok "${root}" "${out}-mkdirs-again" file mkdirs d1/d2 --object file13
    ml_expect "mkdirs leaves an existing marker untouched" "CUSTOM-MARKER" \
        "$(obj_get "${root}" file13 d1/AGENTS.md)"

    # The root path is accepted in both spellings and lists the same entries.
    ml_run_ok "${root}" "${out}-list-slash" file list-dirs / --object file13 --format json
    ml_expect "the root slash spelling lists the same entries" \
        "$(jq -S -c '."."' "${out}-list-root.stdout")" \
        "$(jq -S -c '."/"' "${out}-list-slash.stdout")"

    # list-dirs reports only immediate children, never a recursive walk.
    ml_run_ok "${root}" "${out}-list-shallow" file list-dirs . --object file13 --format json
    ml_expect "list-dirs does not recurse into d2" "false" \
        "$(jq -r '."." | index("d2") != null' "${out}-list-shallow.stdout")"

    # A missing folder is reported per entry without failing the command.
    ml_run_ok "${root}" "${out}-list-missing" file list-dirs nope --object file13 --format json
    ml_expect_contains "a missing folder is reported per entry" "${out}-list-missing.stdout" \
        "does not exist"
    end_case
}

run_file_14() {
    begin_case FILE-14 P0 I
    local root="${ML_STORES}/FILE-14/store"
    local out="${ML_CASE_DIR}/FILE-14"
    make_object "${root}" file14 "${out}"

    printf 'aaa' > "${ML_FIXTURES}/c/three.txt"
    ml_run_ok "${root}" "${out}-seed" put file14 a.txt --from "${ML_FIXTURES}/c/three.txt"
    # Every file command refuses to run without an object id. exists validates
    # its name=path arguments before the object id, so it needs a well-formed
    # pair to reach the --object check.
    local sub
    for sub in read size list-dirs; do
        ml_run_fail "${root}" "${out}-no-object-${sub}" file "${sub}" a.txt
        ml_expect_contains "${sub} requires --object" "${out}-no-object-${sub}.stderr" \
            "--object <id> is required"
    done
    ml_run_fail "${root}" "${out}-no-object-exists" file exists a.txt=a.txt
    ml_expect_contains "exists requires --object" "${out}-no-object-exists.stderr" \
        "--object <id> is required"

    # An explicitly empty object id is refused the same way.
    ml_run_fail "${root}" "${out}-empty-object" file read a.txt --object ''
    ml_expect_contains "an empty object id is refused" "${out}-empty-object.stderr" \
        "--object <id> is required"

    # An unknown object id is refused and never falls back to the host filesystem.
    ml_run_fail "${root}" "${out}-ghost" file read a.txt --object ghost
    ml_expect_contains "an unknown object is refused" "${out}-ghost.stderr" "object not found"

    # A leading slash is object-relative, not an absolute host path.
    ml_run_ok "${root}" "${out}-slash" file read /a.txt --object file14
    ml_expect "a leading slash resolves inside the object" "aaa" \
        "$(cat "${out}-slash.stdout")"
    ml_run_fail "${root}" "${out}-host-abs" file read /etc/passwd --object file14
    ml_expect_contains "a host absolute path is not readable" "${out}-host-abs.stderr" \
        "object not found"

    # A traversal read is refused and never reaches the host filesystem.
    ml_run_fail "${root}" "${out}-traversal-read" file read ../escape --object file14
    ml_expect_contains "a traversal read is refused" "${out}-traversal-read.stderr" \
        "object not found"

    # A traversal write is normalised inside the object directory, never outside it.
    ml_run_ok "${root}" "${out}-traversal-write" file write ../escape --object file14 \
        --content 'X'
    ml_expect "a traversal write stays inside the object" "X" \
        "$(obj_get "${root}" file14 escape)"
    ml_expect_file "no file escaped to the store root" "${root}/escape" absent
    ml_expect_file "no file escaped to the run area" "${ML_BASE}/escape" absent
    ml_expect_file "no file escaped to the project root" "${PROJECT_ROOT}/escape" absent

    # put refuses the same traversal instead of normalising it.
    ml_run_fail "${root}" "${out}-put-traversal" put file14 ../bad.txt \
        --from "${ML_FIXTURES}/c/three.txt"
    ml_expect_contains "put refuses a traversal destination" "${out}-put-traversal.stderr" \
        "invalid path"
    ml_expect_file "put created no file outside the object" "${root}/bad.txt" absent
    ml_note "file write normalises ../escape to escape inside the object while put refuses the same path; both stay inside the object, but the two families disagree on the error contract"

    # The sentinel outside the store is untouched by every refusal above.
    ml_expect_sha "the sentinel outside the store is untouched" \
        "${ML_ARTIFACTS}/sentinel.txt" \
        "$(awk '{print $1}' "${ML_REPORTS}/sentinel.manifest")"
    end_case
}

run_file_15() {
    begin_case FILE-15 P1 I
    local root="${ML_STORES}/FILE-15/store"
    local out="${ML_CASE_DIR}/FILE-15"
    make_object "${root}" file15 "${out}"

    printf 'CROSS-FAMILY' > "${ML_FIXTURES}/c/cross.txt"

    # A file written through put is readable through the file tool.
    ml_run_ok "${root}" "${out}-put" put file15 cross.txt --from "${ML_FIXTURES}/c/cross.txt"
    ml_run_ok "${root}" "${out}-read" file read cross.txt --object file15
    ml_expect "file read sees a put-written file" "CROSS-FAMILY" \
        "$(cat "${out}-read.stdout")"
    ml_run_ok "${root}" "${out}-size" file size cross.txt --object file15
    ml_expect "file size agrees with the put payload" "12" "$(cat "${out}-size.stdout")"

    # A file written through the file tool is readable through get.
    ml_run_ok "${root}" "${out}-write" file write fw.txt --object file15 --content 'FILE-TOOL'
    ml_run_ok "${root}" "${out}-get" get file15 fw.txt
    ml_expect "get sees a file-tool-written file" "FILE-TOOL" "$(cat "${out}-get.stdout")"

    # Both families agree byte-for-byte on the same stored file.
    ml_run_ok "${root}" "${out}-get-cross" get file15 cross.txt
    ml_expect_sha "get and file read agree on the same bytes" "${out}-get-cross.stdout" \
        "$(sha_of "${ML_FIXTURES}/c/cross.txt")"

    # The marker file stays ordinary data through both families.
    ml_run_ok "${root}" "${out}-marker-get" get file15 file15.md
    ml_expect_sha "the marker is readable through get" "${out}-marker-get.stdout" \
        "$(sha_of "${ML_FIXTURES}/c/file15.md")"
    ml_run_ok "${root}" "${out}-marker-read" file read file15.md --object file15
    ml_expect_sha "the marker is readable through file read" "${out}-marker-read.stdout" \
        "$(sha_of "${ML_FIXTURES}/c/file15.md")"

    # Overwriting the marker through the file tool keeps the object discoverable.
    ml_run_ok "${root}" "${out}-marker-write" file write file15.md --object file15 \
        --content 'REWRITTEN MARKER'
    ml_expect "the object is still listed after a marker rewrite" "1" \
        "$(json_count "${root}")"
    ml_run_ok "${root}" "${out}-marker-after" get file15 file15.md
    ml_expect "the rewritten marker is stored" "REWRITTEN MARKER" \
        "$(cat "${out}-marker-after.stdout")"
    end_case
}

run_file_16() {
    begin_case FILE-16 P0 I
    local root="${ML_STORES}/FILE-16/store"
    local out="${ML_CASE_DIR}/FILE-16"
    make_object "${root}" file16 "${out}"

    # Populate the object with every user fixture name plus nested data.
    printf 'aaa' > "${ML_FIXTURES}/c/three.txt"
    python3 -c "open('${ML_FIXTURES}/c/bin16.dat','wb').write(bytes(range(256))*4)"
    ml_run_ok "${root}" "${out}-put-text" put file16 a.txt --from "${ML_FIXTURES}/c/three.txt"
    ml_run_ok "${root}" "${out}-put-bin" put file16 bin.dat --from "${ML_FIXTURES}/c/bin16.dat"
    ml_run_ok "${root}" "${out}-put-nested" put file16 deep/nested/note.txt \
        --from "${ML_FIXTURES}/c/three.txt"
    ml_run_ok "${root}" "${out}-put-metadata-name" put file16 metadata.json \
        --from "${ML_FIXTURES}/c/three.txt"
    ml_run_ok "${root}" "${out}-put-stat-name" put file16 stat.json \
        --from "${ML_FIXTURES}/c/three.txt"

    # The archive is a tar stream of the payload only.

    ml_run_ok "${root}" "${out}-archive" get-archive file16
    ml_expect "the archive is a readable tar" "0" \
        "$(tar -tf "${out}-archive.stdout" >/dev/null 2>&1; echo $?)"
    # Internal-only names (lock, stat.lock, tags) are never exported. The names
    # metadata.json and stat.json are user data here, so they are asserted
    # separately below rather than being counted as leaks.
    local leaked
    leaked=$(tar -tf "${out}-archive.stdout" | grep -c -E '(^|/)(stat\.lock|lock|tags)$' || true)
    ml_expect "the archive exports no internal-only metadata file" "0" "${leaked}"
    ml_expect "the archive exports no reserved temporary file" "0" \
        "$(tar -tf "${out}-archive.stdout" | grep -c 'topsailai-data-write' || true)"

    # The archive manifest matches the payload directory byte-for-byte.
    local payload
    payload=$(ml_payload_dir "${root}" file16)
    rm -rf "${ML_ARTIFACTS}/FILE-16-restore"
    mkdir -p "${ML_ARTIFACTS}/FILE-16-restore"
    tar -xf "${out}-archive.stdout" -C "${ML_ARTIFACTS}/FILE-16-restore"
    ml_manifest "${payload}" > "${ML_ARTIFACTS}/FILE-16-payload.manifest"
    ml_manifest "${ML_ARTIFACTS}/FILE-16-restore" > "${ML_ARTIFACTS}/FILE-16-restore.manifest"
    ml_expect "the restored manifest equals the payload manifest" "0" \
        "$(diff -q "${ML_ARTIFACTS}/FILE-16-payload.manifest" \
            "${ML_ARTIFACTS}/FILE-16-restore.manifest" >/dev/null 2>&1; echo $?)"

    # The restored copy keeps the binary payload byte-exactly.
    ml_expect_sha "the restored binary is byte-exact" \
        "${ML_ARTIFACTS}/FILE-16-restore/bin.dat" \
        "$(sha_of "${ML_FIXTURES}/c/bin16.dat")"

    # User files named like metadata stay ordinary data in the archive.
    ml_expect "the user metadata.json is exported as data" "true" \
        "$(tar -tf "${out}-archive.stdout" | grep -qx 'metadata.json' && echo true || echo false)"
    ml_expect "the user stat.json is exported as data" "true" \
        "$(tar -tf "${out}-archive.stdout" | grep -qx 'stat.json' && echo true || echo false)"
    end_case
}

run_file_17() {
    begin_case FILE-17 P0 I
    local root="${ML_STORES}/FILE-17/store"
    local out="${ML_CASE_DIR}/FILE-17"
    make_object "${root}" file17 "${out}"

    printf 'orig-extra' > "${ML_FIXTURES}/c/extra.txt"
    ml_run_ok "${root}" "${out}-seed" put file17 extra.txt --from "${ML_FIXTURES}/c/extra.txt"
    local marker_before
    marker_before=$(obj_get "${root}" file17 file17.md | sha256sum | awk '{print $1}')

    # An archive without the marker preserves the existing marker byte-exactly.
    mkdir -p "${ML_FIXTURES}/c/nomark"
    printf 'newpayload' > "${ML_FIXTURES}/c/nomark/new.txt"
    tar -cf "${ML_FIXTURES}/c/nomark.tar" -C "${ML_FIXTURES}/c/nomark" new.txt
    ml_run_ok "${root}" "${out}-nomark" put-archive file17 "${ML_FIXTURES}/c/nomark.tar"
    ml_expect "an archive without the marker keeps the marker" "${marker_before}" \
        "$(obj_get "${root}" file17 file17.md | sha256sum | awk '{print $1}')"
    ml_expect "the archive payload is stored" "true" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists new.txt=new.txt \
            --object file17 --format json 2>/dev/null | jq -r '."new.txt"')"

    # The archive replaces the whole payload, so a file absent from it is gone.
    ml_expect "a file absent from the archive is removed" "false" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists extra.txt=extra.txt \
            --object file17 --format json 2>/dev/null | jq -r '."extra.txt"')"
    ml_note "put-archive replaces the payload wholesale: files not present in the archive are removed, while the marker is preserved when the archive omits it"

    # An archive containing the marker replaces it.
    mkdir -p "${ML_FIXTURES}/c/withmark"
    printf -- '---\ndescription: replaced\n---\n\n# REPLACED\n' \
        > "${ML_FIXTURES}/c/withmark/file17.md"
    tar -cf "${ML_FIXTURES}/c/withmark.tar" -C "${ML_FIXTURES}/c/withmark" file17.md
    ml_run_ok "${root}" "${out}-withmark" put-archive file17 "${ML_FIXTURES}/c/withmark.tar"
    ml_expect_contains "an archive marker replaces the stored marker" "${out}-withmark.stdout" \
        "wrote archive"
    ml_run_ok "${root}" "${out}-marker-after" get file17 file17.md
    ml_expect_contains "the replacement marker content is stored" "${out}-marker-after.stdout" \
        "# REPLACED"
    ml_expect "the previous archive payload is cleared" "false" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists new.txt=new.txt \
            --object file17 --format json 2>/dev/null | jq -r '."new.txt"')"

    # The object stays active and discoverable after both replacements.
    ml_expect "the object stays active after archive replacement" "active" \
        "$(json_field "${root}" file17 status)"
    ml_expect "the object stays listed after archive replacement" "1" "$(json_count "${root}")"
    end_case
}

run_file_18() {
    begin_case FILE-18 P1 F
    local root="${ML_STORES}/FILE-18/store"
    local out="${ML_CASE_DIR}/FILE-18"
    make_object "${root}" file18 "${out}"

    printf 'keepme' > "${ML_FIXTURES}/c/keep.txt"
    ml_run_ok "${root}" "${out}-seed" put file18 keep.txt --from "${ML_FIXTURES}/c/keep.txt"

    # A non-tar payload is refused. Archive replacement is not transactional, so
    # the payload is already cleared when the read fails; only the marker stays.
    printf 'not a tar archive\n' > "${ML_FIXTURES}/c/malformed.tar"
    ml_run_fail "${root}" "${out}-malformed" put-archive file18 "${ML_FIXTURES}/c/malformed.tar"
    ml_expect_contains "a malformed archive is refused" "${out}-malformed.stderr" "tar header"
    ml_expect "a malformed archive clears the previous payload" "false" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists keep.txt=keep.txt \
            --object file18 --format json 2>/dev/null | jq -r '.["keep.txt"]')"
    ml_expect "a malformed archive keeps the marker" "true" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists file18.md=file18.md \
            --object file18 --format json 2>/dev/null | jq -r '.["file18.md"]')"
    ml_note "archive replacement clears the payload before parsing, so a refused archive still loses the previous payload; this is the documented non-transactional behaviour"

    # A truncated archive is refused once the header cannot be completed.
    mkdir -p "${ML_FIXTURES}/c/trunc"
    printf 'partial-entry' > "${ML_FIXTURES}/c/trunc/partial.txt"
    tar -cf "${ML_FIXTURES}/c/trunc-full.tar" -C "${ML_FIXTURES}/c/trunc" partial.txt
    head -c 300 "${ML_FIXTURES}/c/trunc-full.tar" > "${ML_FIXTURES}/c/trunc.tar"
    ml_run_fail "${root}" "${out}-truncated" put-archive file18 "${ML_FIXTURES}/c/trunc.tar"
    ml_expect_contains "a truncated archive is refused" "${out}-truncated.stderr" "unexpected EOF"
    ml_expect "a truncated archive leaves no partial entry" "false" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists partial.txt=partial.txt \
            --object file18 --format json 2>/dev/null | jq -r '.["partial.txt"]')"

    # An empty archive is accepted and clears the payload except the marker.
    tar -cf "${ML_FIXTURES}/c/empty.tar" --files-from /dev/null
    ml_run_ok "${root}" "${out}-empty" put-archive file18 "${ML_FIXTURES}/c/empty.tar"
    ml_expect "an empty archive keeps the marker" "true" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists file18.md=file18.md \
            --object file18 --format json 2>/dev/null | jq -r '."file18.md"')"
    ml_expect "an empty archive clears the previous payload" "false" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists keep.txt=keep.txt \
            --object file18 --format json 2>/dev/null | jq -r '."keep.txt"')"

    # The object survives every failure above in a usable state.
    ml_expect "the object is still active after archive failures" "active" \
        "$(json_field "${root}" file18 status)"
    ml_run_ok "${root}" "${out}-still-usable" file write after.txt --object file18 \
        --content 'AFTER'
    ml_expect "the object accepts writes after archive failures" "AFTER" \
        "$(obj_get "${root}" file18 after.txt)"
    end_case
}

run_file_19() {
    begin_case FILE-19 P0 F
    local root="${ML_STORES}/FILE-19/store"
    local out="${ML_CASE_DIR}/FILE-19"
    make_object "${root}" file19 "${out}"

    printf 'keepme' > "${ML_FIXTURES}/c/keep.txt"
    ml_run_ok "${root}" "${out}-seed" put file19 keep.txt --from "${ML_FIXTURES}/c/keep.txt"
    local sentinel_before
    sentinel_before=$(awk '{print $1}' "${ML_REPORTS}/sentinel.manifest")

    # A traversal entry is refused and never writes outside the object.
    mkdir -p "${ML_FIXTURES}/c/trav"
    printf 'evil' > "${ML_FIXTURES}/c/trav/evil.txt"
    tar -cf "${ML_FIXTURES}/c/trav.tar" -C "${ML_FIXTURES}/c/trav" \
        --transform 's,^evil.txt,../../escaped.txt,' evil.txt
    ml_run_fail "${root}" "${out}-traversal" put-archive file19 "${ML_FIXTURES}/c/trav.tar"
    ml_expect_contains "a traversal entry is refused" "${out}-traversal.stderr" \
        "traverses outside object directory"
    ml_expect_file "no traversal file reached the store root" "${root}/escaped.txt" absent
    ml_expect_file "no traversal file reached the run area" "${ML_BASE}/escaped.txt" absent
    ml_expect_file "no traversal file reached the project root" \
        "${PROJECT_ROOT}/escaped.txt" absent

    # An absolute entry is refused and never writes to the host path.
    mkdir -p "${ML_FIXTURES}/c/abs"
    printf 'abs' > "${ML_FIXTURES}/c/abs/abs.txt"
    tar -cf "${ML_FIXTURES}/c/abs.tar" -C "${ML_FIXTURES}/c/abs" \
        --transform 's,^abs.txt,/tmp/manual-live-absolute.txt,' abs.txt
    ml_run_fail "${root}" "${out}-absolute" put-archive file19 "${ML_FIXTURES}/c/abs.tar"
    ml_expect_contains "an absolute entry is refused" "${out}-absolute.stderr" "is absolute"
    ml_expect_file "no absolute entry reached the host path" \
        "/tmp/manual-live-absolute.txt" absent

    # A symbolic-link entry is refused as an unsupported type.
    mkdir -p "${ML_FIXTURES}/c/link"
    printf 'target' > "${ML_FIXTURES}/c/link/target.txt"
    ln -sf target.txt "${ML_FIXTURES}/c/link/link.txt"
    tar -cf "${ML_FIXTURES}/c/link.tar" -C "${ML_FIXTURES}/c/link" target.txt link.txt
    ml_run_fail "${root}" "${out}-link" put-archive file19 "${ML_FIXTURES}/c/link.tar"
    ml_expect_contains "a symlink entry is refused" "${out}-link.stderr" \
        "unsupported tar entry type"
    ml_expect_file "no symlink was created in the payload" \
        "$(ml_payload_dir "${root}" file19)/link.txt" absent

    # A FIFO entry is refused as an unsupported type.
    mkdir -p "${ML_FIXTURES}/c/fifo"
    printf 'x' > "${ML_FIXTURES}/c/fifo/x.txt"
    mkfifo "${ML_FIXTURES}/c/fifo/fifo.txt"
    tar -cf "${ML_FIXTURES}/c/fifo.tar" -C "${ML_FIXTURES}/c/fifo" x.txt fifo.txt
    ml_run_fail "${root}" "${out}-fifo" put-archive file19 "${ML_FIXTURES}/c/fifo.tar"
    ml_expect_contains "a fifo entry is refused" "${out}-fifo.stderr" \
        "unsupported tar entry type"

    # A character-device entry is refused as an unsupported type.
    python3 - "${ML_FIXTURES}/c/dev.tar" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1], 'w') as archive:
    info = tarfile.TarInfo('devnode')
    info.type = tarfile.CHRTYPE
    info.devmajor = 1
    info.devminor = 3
    archive.addfile(info)
PY
    ml_run_fail "${root}" "${out}-device" put-archive file19 "${ML_FIXTURES}/c/dev.tar"
    ml_expect_contains "a device entry is refused" "${out}-device.stderr" \
        "unsupported tar entry type"

    # Every refusal above leaves the sentinel outside the store untouched.
    ml_expect "the sentinel outside the store is untouched" "${sentinel_before}" \
        "$(sha_of "${ML_ARTIFACTS}/sentinel.txt")"
    ml_note "hostile archives are rejected per entry; earlier entries in the same archive may already be applied because archive replacement is not transactional"
    end_case
}

run_file_20() {
    begin_case FILE-20 P0 F
    local root="${ML_STORES}/FILE-20/store"
    local out="${ML_CASE_DIR}/FILE-20"
    make_object "${root}" file20 "${out}"

    printf 'DESTDATA' > "${ML_FIXTURES}/c/dest.txt"
    ml_run_ok "${root}" "${out}-seed" put file20 dest.txt --from "${ML_FIXTURES}/c/dest.txt"
    local payload
    payload=$(ml_payload_dir "${root}" file20)
    local dest="${payload}/dest.txt"
    local dest_sha
    dest_sha=$(sha_of "${dest}")

    # put refuses the destination itself as the source.
    ml_run_fail "${root}" "${out}-same" put file20 dest.txt --from "${dest}"
    ml_expect_contains "put refuses the destination as source" "${out}-same.stderr" \
        "same file"
    ml_expect "the destination is unchanged after the refusal" "${dest_sha}" "$(sha_of "${dest}")"

    # A symlink alias of the destination is refused too.
    ln -sf "${dest}" "${ML_FIXTURES}/c/alias.txt"
    ml_run_fail "${root}" "${out}-symlink" put file20 dest.txt --from "${ML_FIXTURES}/c/alias.txt"
    ml_expect_contains "put refuses a symlink alias" "${out}-symlink.stderr" "same file"
    ml_expect "the destination survives the symlink refusal" "${dest_sha}" "$(sha_of "${dest}")"

    # A hard-link alias of the destination is refused too.
    ln -f "${dest}" "${ML_FIXTURES}/c/hard.txt"
    ml_run_fail "${root}" "${out}-hardlink" put file20 dest.txt --from "${ML_FIXTURES}/c/hard.txt"
    ml_expect_contains "put refuses a hard-link alias" "${out}-hardlink.stderr" "same file"
    ml_expect "the destination survives the hard-link refusal" "${dest_sha}" "$(sha_of "${dest}")"

    # The object status is unchanged by every refusal.
    ml_expect "the object stays active after refusals" "active" \
        "$(json_field "${root}" file20 status)"
    ml_run_ok "${root}" "${out}-read" get file20 dest.txt
    ml_expect "the stored bytes are still readable" "DESTDATA" "$(cat "${out}-read.stdout")"

    # The file tool family does not implement the same guard; record the gap.
    ml_run_ok "${root}" "${out}-file-write-same" file write dest.txt --object file20 \
        --from "${dest}"
    ml_note "file write/append/insert/overwrite-lines accept the destination as their own source and duplicate the content, so the same-file guard covers put only; this is a real asymmetry, not a test defect"
    end_case
}

run_file_21() {
    begin_case FILE-21 P0 F
    local root="${ML_STORES}/FILE-21/store"
    local out="${ML_CASE_DIR}/FILE-21"
    make_object "${root}" file21 "${out}"

    printf 'keepme' > "${ML_FIXTURES}/c/keep.txt"
    ml_run_ok "${root}" "${out}-seed" put file21 keep.txt --from "${ML_FIXTURES}/c/keep.txt"
    local payload
    payload=$(ml_payload_dir "${root}" file21)

    # An archive stored inside the object is refused before extraction.
    mkdir -p "${ML_FIXTURES}/c/inside"
    printf 'x' > "${ML_FIXTURES}/c/inside/x.txt"
    tar -cf "${payload}/inside.tar" -C "${ML_FIXTURES}/c/inside" x.txt
    ml_run_fail "${root}" "${out}-inside" put-archive file21 "${payload}/inside.tar"
    ml_expect_contains "an archive inside the object is refused" "${out}-inside.stderr" \
        "overlaps object data"
    ml_expect "the payload survives the inside-archive refusal" "keepme" \
        "$(obj_get "${root}" file21 keep.txt)"

    # A symlink alias into the object is refused too.
    ln -sf "${payload}/inside.tar" "${ML_FIXTURES}/c/alias.tar"
    ml_run_fail "${root}" "${out}-symlink" put-archive file21 "${ML_FIXTURES}/c/alias.tar"
    ml_expect_contains "a symlink alias into the object is refused" "${out}-symlink.stderr" \
        "overlaps object data"

    # A hard-link alias into the object is refused too.
    ln -f "${payload}/inside.tar" "${ML_FIXTURES}/c/hard.tar"
    ml_run_fail "${root}" "${out}-hardlink" put-archive file21 "${ML_FIXTURES}/c/hard.tar"
    ml_expect_contains "a hard-link alias into the object is refused" "${out}-hardlink.stderr" \
        "overlaps object data"

    # recover --from refuses the same overlap and keeps the deleted status.
    ml_run_ok "${root}" "${out}-delete" delete file21
    ml_expect "the object is deleted before the recover attempt" "deleted" \
        "$(json_field "${root}" file21 status)"
    ml_run_fail "${root}" "${out}-recover-inside" recover file21 --from "${payload}/inside.tar"
    ml_expect_contains "recover refuses an overlapping archive" "${out}-recover-inside.stderr" \
        "overlaps object data"
    ml_expect "the object stays deleted after the refusal" "deleted" \
        "$(json_field "${root}" file21 status)"

    # An archive outside the object is accepted and restores the object.
    tar -cf "${ML_FIXTURES}/c/outside.tar" -C "${ML_FIXTURES}/c/inside" x.txt
    ml_run_ok "${root}" "${out}-recover-outside" recover file21 \
        --from "${ML_FIXTURES}/c/outside.tar"
    ml_expect "an external archive restores the object" "active" \
        "$(json_field "${root}" file21 status)"
    ml_expect "the restored payload comes from the archive" "true" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists x.txt=x.txt \
            --object file21 --format json 2>/dev/null | jq -r '."x.txt"')"
    end_case
}

run_file_22() {
    begin_case FILE-22 P0 F
    local root="${ML_STORES}/FILE-22/store"
    local out="${ML_CASE_DIR}/FILE-22"
    make_object "${root}" file22 "${out}"

    printf 'ordinary' > "${ML_FIXTURES}/c/ordinary.txt"
    ml_run_ok "${root}" "${out}-seed" put file22 ordinary.txt \
        --from "${ML_FIXTURES}/c/ordinary.txt"
    local payload
    payload=$(ml_payload_dir "${root}" file22)

    # Fresh and expired reserved files plus an ordinary control are planted.
    printf 'fresh' > "${payload}/.topsailai-data-write-fresh"
    printf 'expired' > "${payload}/.topsailai-data-write-expired"
    touch -d '3 days ago' "${payload}/.topsailai-data-write-expired"
    mkdir -p "${payload}/nested"
    printf 'expired-nested' > "${payload}/nested/.topsailai-data-write-expired"
    touch -d '3 days ago' "${payload}/nested/.topsailai-data-write-expired"
    printf 'nested-ordinary' > "${payload}/nested/keep.txt"

    # Reserved files are invisible to show, exists, list-dirs and archives.
    ml_run_ok "${root}" "${out}-show" show file22
    ml_expect_not_contains "show hides reserved temporary files" "${out}-show.stdout" \
        "topsailai-data-write"
    ml_run_ok "${root}" "${out}-exists" file exists \
        .topsailai-data-write-fresh=.topsailai-data-write-fresh \
        ordinary.txt=ordinary.txt --object file22 --format json
    ml_expect "exists reports a reserved file as absent" "false" \
        "$(jq -r '.[".topsailai-data-write-fresh"]' "${out}-exists.stdout")"
    ml_expect "exists still reports ordinary data" "true" \
        "$(jq -r '.["ordinary.txt"]' "${out}-exists.stdout")"
    ml_run_ok "${root}" "${out}-list-dirs" file list-dirs . --object file22 --format json
    ml_expect "list-dirs hides reserved temporary files" "false" \
        "$(jq -r '."." | map(select(startswith(".topsailai-data-write-"))) | length > 0' \
            "${out}-list-dirs.stdout")"
    ml_run_ok "${root}" "${out}-archive" get-archive file22
    ml_expect "the archive hides reserved temporary files" "0" \
        "$(tar -tf "${out}-archive.stdout" | grep -c 'topsailai-data-write' || true)"

    # A write cleans only expired reserved files in the target directory.
    ml_run_ok "${root}" "${out}-write" file write ordinary.txt --object file22 \
        --content 'ORDINARY2'
    ml_expect_file "the expired reserved file is removed" \
        "${payload}/.topsailai-data-write-expired" absent
    ml_expect_file "the fresh reserved file is preserved" \
        "${payload}/.topsailai-data-write-fresh" present
    ml_expect_file "the ordinary control file is preserved" "${payload}/ordinary.txt" present

    # A nested write cleans only expired reserved files in that directory.
    ml_run_ok "${root}" "${out}-nested-write" file write nested/keep.txt --object file22 \
        --content 'KEEP2'
    ml_expect_file "the nested expired reserved file is removed" \
        "${payload}/nested/.topsailai-data-write-expired" absent
    ml_expect_file "the nested ordinary file is preserved" "${payload}/nested/keep.txt" present

    # A directory symlink is never traversed by the cleanup walk.
    mkdir -p "${ML_ARTIFACTS}/FILE-22-outside"
    printf 'outside-expired' > "${ML_ARTIFACTS}/FILE-22-outside/.topsailai-data-write-expired"
    touch -d '3 days ago' "${ML_ARTIFACTS}/FILE-22-outside/.topsailai-data-write-expired"
    ln -sfn "${ML_ARTIFACTS}/FILE-22-outside" "${payload}/linkdir"
    mkdir -p "${ML_FIXTURES}/c/cleanup"
    printf 'x' > "${ML_FIXTURES}/c/cleanup/x.txt"
    tar -cf "${ML_FIXTURES}/c/cleanup.tar" -C "${ML_FIXTURES}/c/cleanup" x.txt
    ml_run_ok "${root}" "${out}-archive-cleanup" put-archive file22 \
        "${ML_FIXTURES}/c/cleanup.tar"
    ml_expect_file "the cleanup walk does not follow a directory symlink" \
        "${ML_ARTIFACTS}/FILE-22-outside/.topsailai-data-write-expired" present

    # Move copies no reserved temporary file into the new payload.
    printf 'fresh2' > "${payload}/.topsailai-data-write-fresh2"
    ml_run_ok "${root}" "${out}-move" move file22 archive
    local moved
    moved=$(ml_payload_dir "${root}" file22)
    ml_expect "the moved payload carries no reserved temporary file" "0" \
        "$(find "${moved}" -name '.topsailai-data-write-*' 2>/dev/null | wc -l | tr -d ' ')"
    ml_expect "the moved payload keeps ordinary data" "true" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists x.txt=x.txt \
            --object file22 --format json 2>/dev/null | jq -r '."x.txt"')"
    end_case
}

run_file_23() {
    begin_case FILE-23 P1 I
    local root="${ML_STORES}/FILE-23/store"
    local out="${ML_CASE_DIR}/FILE-23"
    make_object "${root}" file23 "${out}"

    # An empty directory entry is accepted but cannot be represented on disk.
    mkdir -p "${ML_FIXTURES}/c/emptydir/emptydir"
    printf 'x' > "${ML_FIXTURES}/c/emptydir/x.txt"
    tar -cf "${ML_FIXTURES}/c/emptydir.tar" -C "${ML_FIXTURES}/c/emptydir" x.txt emptydir
    ml_run_ok "${root}" "${out}-emptydir" put-archive file23 "${ML_FIXTURES}/c/emptydir.tar"
    ml_run_ok "${root}" "${out}-emptydir-list" file list-dirs . --object file23 --format json
    ml_expect "an empty directory entry is not materialised" "false" \
        "$(jq -r '."." | index("emptydir") != null' "${out}-emptydir-list.stdout")"
    ml_note "empty tar directory entries are accepted but not materialised, so an empty directory cannot round-trip; this is a documented format limitation rather than silent payload loss"

    # Unicode names round-trip byte-exactly.
    mkdir -p "${ML_FIXTURES}/c/uni"
    printf 'unicode-payload' > "${ML_FIXTURES}/c/uni/中文文件.txt"
    tar -cf "${ML_FIXTURES}/c/uni.tar" -C "${ML_FIXTURES}/c/uni" 中文文件.txt
    ml_run_ok "${root}" "${out}-unicode" put-archive file23 "${ML_FIXTURES}/c/uni.tar"
    ml_expect "a unicode filename round-trips" "unicode-payload" \
        "$(obj_get "${root}" file23 中文文件.txt)"

    # A long filename round-trips.
    local long_name
    long_name=$(python3 -c "print('n' * 200 + '.txt')")
    mkdir -p "${ML_FIXTURES}/c/long"
    printf 'long-payload' > "${ML_FIXTURES}/c/long/${long_name}"
    tar -cf "${ML_FIXTURES}/c/long.tar" -C "${ML_FIXTURES}/c/long" "${long_name}"
    ml_run_ok "${root}" "${out}-long" put-archive file23 "${ML_FIXTURES}/c/long.tar"
    ml_expect "a 200-character filename round-trips" "long-payload" \
        "$(obj_get "${root}" file23 "${long_name}")"

    # Duplicate entries resolve to the last occurrence.
    mkdir -p "${ML_FIXTURES}/c/dup1" "${ML_FIXTURES}/c/dup2"
    printf 'FIRST' > "${ML_FIXTURES}/c/dup1/dup.txt"
    printf 'SECOND' > "${ML_FIXTURES}/c/dup2/dup.txt"
    tar -cf "${ML_FIXTURES}/c/dup.tar" -C "${ML_FIXTURES}/c/dup1" dup.txt
    tar -rf "${ML_FIXTURES}/c/dup.tar" -C "${ML_FIXTURES}/c/dup2" dup.txt
    ml_run_ok "${root}" "${out}-dup" put-archive file23 "${ML_FIXTURES}/c/dup.tar"
    ml_expect "a duplicate entry resolves to the last occurrence" "SECOND" \
        "$(obj_get "${root}" file23 dup.txt)"

    # The archive round-trips the surviving payload byte-exactly.
    ml_run_ok "${root}" "${out}-archive" get-archive file23
    rm -rf "${ML_ARTIFACTS}/FILE-23-restore"
    mkdir -p "${ML_ARTIFACTS}/FILE-23-restore"
    tar -xf "${out}-archive.stdout" -C "${ML_ARTIFACTS}/FILE-23-restore"
    ml_manifest "${ML_ARTIFACTS}/FILE-23-restore" > "${ML_ARTIFACTS}/FILE-23-restore.manifest"
    ml_manifest "$(ml_payload_dir "${root}" file23)" > "${ML_ARTIFACTS}/FILE-23-payload.manifest"
    ml_expect "the archive round-trips the surviving payload" "0" \
        "$(diff -q "${ML_ARTIFACTS}/FILE-23-payload.manifest" \
            "${ML_ARTIFACTS}/FILE-23-restore.manifest" >/dev/null 2>&1; echo $?)"
    end_case
}

CASES=(FILE-01 FILE-02 FILE-03 FILE-04 FILE-05 FILE-06 FILE-07 FILE-08 FILE-09 FILE-10 FILE-11 FILE-12 FILE-13 FILE-14 FILE-15 FILE-16 FILE-17 FILE-18 FILE-19 FILE-20 FILE-21 FILE-22 FILE-23)
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
        FILE-09) run_file_09 ;;
        FILE-10) run_file_10 ;;
        FILE-11) run_file_11 ;;
        FILE-12) run_file_12 ;;
        FILE-13) run_file_13 ;;
        FILE-14) run_file_14 ;;
        FILE-15) run_file_15 ;;
        FILE-16) run_file_16 ;;
        FILE-17) run_file_17 ;;
        FILE-18) run_file_18 ;;
        FILE-19) run_file_19 ;;
        FILE-20) run_file_20 ;;
        FILE-21) run_file_21 ;;
        FILE-22) run_file_22 ;;
        FILE-23) run_file_23 ;;
    esac
done

if grep -q '"status":"FAIL"' "${ML_RESULTS}" 2>/dev/null; then
    exit 1
fi
exit 0
