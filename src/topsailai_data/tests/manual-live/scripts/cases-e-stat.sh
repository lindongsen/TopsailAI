#!/usr/bin/env bash
# cases-e-stat: manual/live cases for object statistics and concurrency.
#
# Scope: STAT-01..STAT-08 from tests/manual-live/statistics-concurrency.md.
# Every case runs against an isolated store under .tmp/manual-live/<run>/stores.
# No case reads or writes the live store.
#
# Usage:
#   ML_RUN_ID=<id> bash tests/manual-live/scripts/cases-e-stat.sh [case ids...]

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

# stat_field prints one field value from the stat output of an object.
# The stat command itself never changes counters, so it is safe to call between
# assertions.
stat_field() {
    local root="$1" id="$2" field="$3"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" stat "${id}" 2>/dev/null \
        | awk -v f="${field}" '$1==f":"{print $2; exit}'
}

# stat_has_field reports whether the stat output contains a field at all.
# last_read_at is omitted until the first read, so presence must be asserted
# separately from its value.
stat_has_field() {
    local root="$1" id="$2" field="$3"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" stat "${id}" 2>/dev/null \
        | grep -q "^${field}:"
}

# stat_json prints the stat record as JSON.
stat_json() {
    local root="$1" id="$2"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" stat "${id}" --format json 2>/dev/null
}

# top_json prints a stat top ranking as JSON.
top_json() {
    local root="$1"
    shift
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" stat top --format json "$@" 2>/dev/null
}

# top_ids prints the ranked ids of a stat top result as one space-separated line.
top_ids() {
    local root="$1"
    shift
    top_json "${root}" "$@" | jq -r '.[].id' | tr '\n' ' ' | sed 's/ $//'
}

# stat_path prints the stat.json path of an object.
stat_path() {
    local root="$1" id="$2"
    printf '%s/stat.json' "$(ml_meta_dir "${root}" "${id}")"
}

# make_object creates one object with a description frontmatter fixture.
make_object() {
    local root="$1" id="$2" out="$3"
    ml_make_markdown "${out}/${id}.md" "stat fixture ${id}" "body ${id}"
    ml_run_ok "${root}" "${out}/create-${id}" create "${id}" --from "${out}/${id}.md"
}

# run_stat_01 pins the create write delta, the per-operation read delta and the
# stat record shape.
run_stat_01() {
    begin_case STAT-01 P1 I
    local root out
    root=$(ml_case_root stat01)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s1 "${out}"
    ml_expect "create counts one write" "1" "$(stat_field "${root}" s1 write_count)"
    ml_expect "create counts no read" "0" "$(stat_field "${root}" s1 read_count)"
    ml_expect "the statistics schema version is one" "1" \
        "$(stat_field "${root}" s1 schema_version)"
    ml_expect "create records a write timestamp" "yes" \
        "$(stat_has_field "${root}" s1 last_written_at && echo yes || echo no)"
    ml_expect "no read timestamp exists before the first read" "no" \
        "$(stat_has_field "${root}" s1 last_read_at && echo yes || echo no)"

    ml_run_ok "${root}" "${out}/show" show s1
    ml_expect "show counts one read" "1" "$(stat_field "${root}" s1 read_count)"
    ml_run_ok "${root}" "${out}/get" get s1 s1.md
    ml_expect "get counts one read" "2" "$(stat_field "${root}" s1 read_count)"
    ml_run_ok "${root}" "${out}/archive" get-archive s1
    ml_expect "get-archive counts one read" "3" "$(stat_field "${root}" s1 read_count)"
    ml_expect "the write counter is untouched by reads" "1" \
        "$(stat_field "${root}" s1 write_count)"

    local stamp
    stamp=$(stat_field "${root}" s1 last_read_at)
    ml_expect "the read timestamp is recorded" "yes" \
        "$([[ -n "${stamp}" ]] && echo yes || echo no)"
    ml_expect "the read timestamp parses as RFC3339" "yes" \
        "$(date -d "${stamp}" +%Y >/dev/null 2>&1 && echo yes || echo no)"

    ml_run_ok "${root}" "${out}/stat-json" stat s1 --format json
    ml_expect "the JSON record parses" "1" \
        "$(jq -r '.schema_version' "${out}/stat-json.stdout")"
    ml_expect "the JSON record carries the read count" "3" \
        "$(jq -r '.read_count' "${out}/stat-json.stdout")"
    ml_expect "the JSON record carries the write count" "1" \
        "$(jq -r '.write_count' "${out}/stat-json.stdout")"
    end_case
}

# run_stat_02 pins every successful write delta, including the duplicate tag
# variant, and proves reads stay untouched.
run_stat_02() {
    begin_case STAT-02 P1 I
    local root out
    root=$(ml_case_root stat02)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s2 "${out}"
    printf 'payload\n' > "${out}/payload.txt"
    ml_run_ok "${root}" "${out}/put" put s2 payload.txt --from "${out}/payload.txt"
    ml_expect "put counts one write" "2" "$(stat_field "${root}" s2 write_count)"

    ml_run_ok "${root}" "${out}/archive" get-archive s2
    ml_run_ok "${root}" "${out}/put-archive" put-archive s2 "${out}/archive.stdout"
    ml_expect "put-archive counts one write" "3" "$(stat_field "${root}" s2 write_count)"

    ml_run_ok "${root}" "${out}/update" update s2 --description "changed"
    ml_expect "update counts one write" "4" "$(stat_field "${root}" s2 write_count)"

    ml_run_ok "${root}" "${out}/tag" tag add s2 alpha
    ml_expect "tag add counts one write" "5" "$(stat_field "${root}" s2 write_count)"

    ml_run_ok "${root}" "${out}/tag-dup" tag add s2 alpha
    ml_expect "a duplicate tag add still counts one write" "6" \
        "$(stat_field "${root}" s2 write_count)"
    ml_note "a duplicate tag add is a no-op for tags but still increments write_count; the assertion pins the observed behaviour"

    ml_run_ok "${root}" "${out}/move" move s2 classify
    ml_expect "move counts one write" "7" "$(stat_field "${root}" s2 write_count)"

    ml_expect "no write operation counted a read" "1" \
        "$(stat_field "${root}" s2 read_count)"
    end_case
}

# run_stat_03 pins the per-subcommand cardinality of the file tool, including
# the read-before-write behaviour of append, mkdirs, overwrite-lines and insert.
run_stat_03() {
    begin_case STAT-03 P1 I
    local root out
    root=$(ml_case_root stat03)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/s3.md" "stat three" $'line one\nline two\nline three'
    ml_run_ok "${root}" "${out}/create" create s3 --from "${out}/s3.md"
    ml_expect "the fixture starts with one write" "1" \
        "$(stat_field "${root}" s3 write_count)"

    ml_run_ok "${root}" "${out}/read" file read --object s3 s3.md
    ml_expect "file read counts one read" "1" "$(stat_field "${root}" s3 read_count)"
    ml_run_ok "${root}" "${out}/read-lines" file read-lines --object s3 s3.md
    ml_expect "file read-lines counts one read" "2" "$(stat_field "${root}" s3 read_count)"
    ml_run_ok "${root}" "${out}/read-around" file read-around --object s3 s3.md 2
    ml_expect "file read-around counts one read" "3" "$(stat_field "${root}" s3 read_count)"
    ml_run_ok "${root}" "${out}/read-context" file read-context --object s3 s3.md line
    ml_expect "file read-context counts one read" "4" "$(stat_field "${root}" s3 read_count)"
    ml_run_ok "${root}" "${out}/read-files" file read-files --object s3 s3.md s3.md
    ml_expect "file read-files counts one read per path" "6" \
        "$(stat_field "${root}" s3 read_count)"
    ml_run_ok "${root}" "${out}/size" file size --object s3 s3.md
    ml_expect "file size counts one read" "7" "$(stat_field "${root}" s3 read_count)"
    ml_run_ok "${root}" "${out}/exists" file exists name=s3.md --object s3
    ml_expect "file exists counts one read" "8" "$(stat_field "${root}" s3 read_count)"
    ml_run_ok "${root}" "${out}/list-dirs" file list-dirs --object s3 .
    ml_expect "file list-dirs counts one read" "9" "$(stat_field "${root}" s3 read_count)"

    printf 'written\n' > "${out}/w.txt"
    ml_run_ok "${root}" "${out}/write" file write --object s3 name=w.txt --from "${out}/w.txt"
    ml_expect "file write counts one write" "2" "$(stat_field "${root}" s3 write_count)"
    ml_expect "file write does not count a read" "9" \
        "$(stat_field "${root}" s3 read_count)"

    ml_run_ok "${root}" "${out}/append" file append --object s3 name=w.txt --from "${out}/w.txt"
    ml_expect "file append counts one write" "3" "$(stat_field "${root}" s3 write_count)"
    ml_expect "file append also counts one read" "10" \
        "$(stat_field "${root}" s3 read_count)"

    ml_run_ok "${root}" "${out}/mkdirs" file mkdirs --object s3 dir1
    ml_expect "file mkdirs counts one write" "4" "$(stat_field "${root}" s3 write_count)"
    ml_expect "file mkdirs also counts one read" "11" \
        "$(stat_field "${root}" s3 read_count)"

    ml_run_ok "${root}" "${out}/overwrite" file overwrite-lines --object s3 s3.md 2 --content ZZZ
    ml_expect "file overwrite-lines counts one write" "5" \
        "$(stat_field "${root}" s3 write_count)"
    ml_expect "file overwrite-lines also counts one read" "12" \
        "$(stat_field "${root}" s3 read_count)"

    ml_run_ok "${root}" "${out}/insert" file insert --object s3 s3.md 1 --content INS
    ml_expect "file insert counts one write" "6" "$(stat_field "${root}" s3 write_count)"
    ml_expect "file insert also counts one read" "13" \
        "$(stat_field "${root}" s3 read_count)"
    ml_note "append, mkdirs, overwrite-lines and insert read the current content before writing, so each adds one read and one write; file write is a pure write"
    end_case
}

# run_stat_04 proves tracking can be disabled without touching the record and
# that enumeration commands never count.
run_stat_04() {
    begin_case STAT-04 P0 I
    local root out
    root=$(ml_case_root stat04)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s4 "${out}"
    local record before after
    record=$(stat_path "${root}" s4)
    before=$(sha256sum "${record}" | awk '{print $1}')

    ml_run_ok "${root}" "${out}/get-off" --env TOPSAILAI_DATA_TRACK_STAT=0 -- get s4 s4.md
    after=$(sha256sum "${record}" | awk '{print $1}')
    ml_expect "a disabled read leaves the record byte-identical" "${before}" "${after}"

    printf 'payload\n' > "${out}/payload.txt"
    ml_run_ok "${root}" "${out}/put-off" --env TOPSAILAI_DATA_TRACK_STAT=0 -- \
        put s4 payload.txt --from "${out}/payload.txt"
    after=$(sha256sum "${record}" | awk '{print $1}')
    ml_expect "a disabled write leaves the record byte-identical" "${before}" "${after}"

    ml_run_ok "${root}" "${out}/update-off" --env TOPSAILAI_DATA_TRACK_STAT=0 -- \
        update s4 --description "changed"
    ml_run_ok "${root}" "${out}/tag-off" --env TOPSAILAI_DATA_TRACK_STAT=0 -- \
        tag add s4 alpha
    after=$(sha256sum "${record}" | awk '{print $1}')
    ml_expect "disabled metadata writes leave the record byte-identical" \
        "${before}" "${after}"

    ml_run_ok "${root}" "${out}/get-on" get s4 s4.md
    ml_expect "re-enabling tracking resumes counting from the preserved value" "1" \
        "$(stat_field "${root}" s4 read_count)"
    ml_expect "the preserved write count is still one" "1" \
        "$(stat_field "${root}" s4 write_count)"

    local reads writes
    reads=$(stat_field "${root}" s4 read_count)
    writes=$(stat_field "${root}" s4 write_count)
    ml_run_ok "${root}" "${out}/list" list
    ml_run_ok "${root}" "${out}/search" search s4
    ml_run_ok "${root}" "${out}/with-stat" list --with-stat
    ml_run_ok "${root}" "${out}/stat" stat s4
    ml_run_ok "${root}" "${out}/top" stat top
    ml_expect "enumeration and ranking never count a read" "${reads}" \
        "$(stat_field "${root}" s4 read_count)"
    ml_expect "enumeration and ranking never count a write" "${writes}" \
        "$(stat_field "${root}" s4 write_count)"

    ml_run_ok "${root}" "${out}/with-stat-json" list --with-stat --format json
    ml_expect "with-stat attaches the read count" "${reads}" \
        "$(jq -r '.[0].read_count' "${out}/with-stat-json.stdout")"
    ml_expect "with-stat attaches the write count" "${writes}" \
        "$(jq -r '.[0].write_count' "${out}/with-stat-json.stdout")"
    ml_run_ok "${root}" "${out}/plain-json" list --format json
    ml_expect "a plain listing carries no read count" "null" \
        "$(jq -r '.[0].read_count // "null"' "${out}/plain-json.stdout")"
    end_case
}

# run_stat_05 pins ranking order, tie breaking, missing timestamps, limits,
# status filters, both output formats and option rejection.
run_stat_05() {
    begin_case STAT-05 P1 I
    local root out
    root=$(ml_case_root stat05)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" t1 "${out}"
    make_object "${root}" t2 "${out}"
    make_object "${root}" t3 "${out}"
    ml_run_ok "${root}" "${out}/r1" get t1 t1.md
    ml_run_ok "${root}" "${out}/r2" get t1 t1.md
    ml_run_ok "${root}" "${out}/r3" get t2 t2.md

    ml_expect "read ranking is descending by count" "t1 t2 t3" \
        "$(top_ids "${root}" --by read --order desc)"
    ml_expect "read ranking is ascending by count" "t3 t2 t1" \
        "$(top_ids "${root}" --by read --order asc)"
    ml_expect "equal write counts break ties by descending id" "t3 t2 t1" \
        "$(top_ids "${root}" --by write --order desc)"
    ml_expect "equal write counts break ties by ascending id" "t1 t2 t3" \
        "$(top_ids "${root}" --by write --order asc)"
    ml_expect "an object without a read timestamp sorts last" "t2 t1 t3" \
        "$(top_ids "${root}" --by last_read --order desc)"

    ml_run_ok "${root}" "${out}/top-json" stat top --by read --format json
    ml_expect "the JSON ranking parses" "3" \
        "$(jq 'length' "${out}/top-json.stdout")"
    ml_expect "the JSON ranking carries ranks" "1" \
        "$(jq -r '.[0].rank' "${out}/top-json.stdout")"
    ml_expect "the JSON ranking carries the status" "active" \
        "$(jq -r '.[0].status' "${out}/top-json.stdout")"
    ml_expect "a missing read timestamp is null in JSON" "null" \
        "$(jq -r '.[]|select(.id=="t3")|.last_read_at // "null"' "${out}/top-json.stdout")"

    ml_run_ok "${root}" "${out}/limit0" stat top --by read --limit 0
    ml_expect "a zero limit prints an empty list" "[]" \
        "$(tr -d '[:space:]' < "${out}/limit0.stdout")"
    ml_run_ok "${root}" "${out}/limit1" stat top --by read --limit 1 --format json
    ml_expect "a limit of one prints one entry" "1" \
        "$(jq 'length' "${out}/limit1.stdout")"

    ml_run_ok "${root}" "${out}/status-active" stat top --status active --format json
    ml_expect "the active filter keeps every object" "3" \
        "$(jq 'length' "${out}/status-active.stdout")"
    ml_run_ok "${root}" "${out}/status-deleted" stat top --status deleted --format json
    ml_expect "the deleted filter keeps nothing yet" "0" \
        "$(jq 'length' "${out}/status-deleted.stdout")"

    ml_run_fail "${root}" "${out}/bad-by" stat top --by bogus
    ml_expect_contains "an unknown ranking key is rejected" "${out}/bad-by.stderr" \
        'invalid by "bogus"'
    ml_run_fail "${root}" "${out}/bad-order" stat top --order bogus
    ml_expect_contains "an unknown order is rejected" "${out}/bad-order.stderr" \
        'invalid order "bogus"'
    ml_run_fail "${root}" "${out}/bad-status" stat top --status creating
    ml_expect_contains "the creating status is rejected" "${out}/bad-status.stderr" \
        'invalid status "creating"'
    ml_run_fail "${root}" "${out}/bad-limit" stat top --limit -1
    ml_expect_contains "a negative limit is rejected" "${out}/bad-limit.stderr" \
        "limit must be non-negative"
    end_case
}

# run_stat_06 proves a missing or corrupt record degrades to a zero record
# without crashing and that later updates still work.
run_stat_06() {
    begin_case STAT-06 P1 F
    local root out
    root=$(ml_case_root stat06)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s6 "${out}"
    local record
    record=$(stat_path "${root}" s6)

    rm -f "${record}"
    ml_run_ok "${root}" "${out}/stat-missing" stat s6
    ml_expect "a missing record reports schema version zero" "0" \
        "$(stat_field "${root}" s6 schema_version)"
    ml_expect "a missing record reports no reads" "0" \
        "$(stat_field "${root}" s6 read_count)"
    ml_expect "a missing record reports no writes" "0" \
        "$(stat_field "${root}" s6 write_count)"

    printf 'not json\n' > "${record}"
    ml_run_ok "${root}" "${out}/stat-corrupt" stat s6
    ml_expect "a corrupt record reports schema version zero" "0" \
        "$(stat_field "${root}" s6 schema_version)"
    ml_expect "a corrupt record reports no reads" "0" \
        "$(stat_field "${root}" s6 read_count)"

    ml_run_ok "${root}" "${out}/get" get s6 s6.md
    ml_expect_contains "a corrupt record produces a warning" "${out}/get.stderr" \
        "ignoring corrupt object stat"
    ml_expect "the read still succeeds and rebuilds the record" "1" \
        "$(stat_field "${root}" s6 read_count)"
    ml_expect "the rebuilt record uses schema version one" "1" \
        "$(stat_field "${root}" s6 schema_version)"

    ml_run_ok "${root}" "${out}/with-stat" list --with-stat --format json
    ml_expect "with-stat tolerates the rebuilt record" "1" \
        "$(jq -r '.[0].read_count' "${out}/with-stat.stdout")"
    end_case
}

# run_stat_07 pins the lifecycle interaction: freeze on delete, preservation
# across recover, and continued readability after finalization.
run_stat_07() {
    begin_case STAT-07 P1 I
    local root out
    root=$(ml_case_root stat07)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s7 "${out}"
    ml_run_ok "${root}" "${out}/get" get s7 s7.md
    local reads writes
    reads=$(stat_field "${root}" s7 read_count)
    writes=$(stat_field "${root}" s7 write_count)
    ml_expect "the fixture has one read" "1" "${reads}"
    ml_expect "the fixture has one write" "1" "${writes}"

    ml_run_ok "${root}" "${out}/delete" delete s7
    ml_expect "delete freezes the read counter" "${reads}" \
        "$(stat_field "${root}" s7 read_count)"
    ml_expect "delete freezes the write counter" "${writes}" \
        "$(stat_field "${root}" s7 write_count)"

    ml_run_ok "${root}" "${out}/recover" recover s7
    ml_expect "recover preserves the read counter" "${reads}" \
        "$(stat_field "${root}" s7 read_count)"
    ml_expect "recover preserves the write counter" "${writes}" \
        "$(stat_field "${root}" s7 write_count)"
    ml_note "recover itself is not counted; only the preserved counters are visible"

    ml_run_ok "${root}" "${out}/get-after" get s7 s7.md
    ml_expect "reads resume after recovery" "2" \
        "$(stat_field "${root}" s7 read_count)"

    ml_run_ok "${root}" "${out}/delete2" delete s7
    ml_run_ok "${root}" "${out}/finalize" delete s7
    ml_expect "finalization keeps the read counter" "2" \
        "$(stat_field "${root}" s7 read_count)"
    ml_run_ok "${root}" "${out}/stat-ceased" stat s7
    ml_expect "a ceased object still reports statistics" "2" \
        "$(stat_field "${root}" s7 read_count)"
    ml_run_ok "${root}" "${out}/top-ceased" stat top --status ceased --format json
    ml_expect "a ceased object appears in the ceased ranking" "s7" \
        "$(jq -r '.[0].id' "${out}/top-ceased.stdout")"
    end_case
}

# count_matching counts the given files whose content matches a pattern.
#
# A "grep | wc -l" pipeline cannot be used here: the harness runs under
# "set -euo pipefail", so grep returning 1 for "no match" aborts the whole
# script and silently truncates the case instead of reporting a failure.
count_matching() {
    local pattern="$1"
    shift
    local n=0 f
    for f in "$@"; do
        [[ -f "${f}" ]] || continue
        if grep -q -- "${pattern}" "${f}" 2>/dev/null; then
            n=$((n + 1))
        fi
    done
    printf '%s' "${n}"
}

# count_not_matching counts the given files whose content lacks a pattern.
count_not_matching() {
    local pattern="$1"
    shift
    local n=0 f
    for f in "$@"; do
        [[ -f "${f}" ]] || continue
        if ! grep -q -- "${pattern}" "${f}" 2>/dev/null; then
            n=$((n + 1))
        fi
    done
    printf '%s' "${n}"
}

# run_stat_08 proves the namespace lock serializes CLI processes and that no
# read event is lost once the readers are allowed to retry.
#
# The namespace lock is a non-blocking exclusive flock taken during adapter
# initialization, so a competing process fails fast instead of queueing. The
# case proves that deterministically by holding the lock itself, then proves
# convergence with a bounded retry loop.
run_stat_08() {
    begin_case STAT-08 P0 I
    local root out
    root=$(ml_case_root stat08)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s8 "${out}"
    ml_expect "the fixture starts with no reads" "0" \
        "$(stat_field "${root}" s8 read_count)"

    # Hold the namespace lock from this shell so the fail-fast path is
    # deterministic instead of depending on a race between CLI processes.
    local holder_pid
    (
        exec 9>"${root}/.topsailai-data-namespace.lock"
        flock -x 9
        printf 'ready\n' > "${out}/holder.ready"
        sleep 5
    ) &
    holder_pid=$!

    local waited=0
    while [[ ! -f "${out}/holder.ready" && "${waited}" -lt 200 ]]; do
        sleep 0.02
        waited=$((waited + 1))
    done
    ml_expect "the lock holder acquired the namespace lock" "yes" \
        "$([[ -f "${out}/holder.ready" ]] && echo yes || echo no)"

    ml_run_fail "${root}" "${out}/blocked-get" get s8 s8.md
    ml_expect_contains "a read fails fast while the namespace lock is held" \
        "${out}/blocked-get.stderr" "namespace lock"
    ml_expect_contains "the fail-fast error names the lock holder" \
        "${out}/blocked-get.stderr" "object is locked by another process"
    ml_run_fail "${root}" "${out}/blocked-list" list
    ml_expect_contains "a listing fails fast while the namespace lock is held" \
        "${out}/blocked-list.stderr" "namespace lock"
    # The counter can only be read after the lock is released: "stat" itself
    # initializes the adapter and therefore needs the same namespace lock, so
    # reading it while the holder is active would return nothing.
    wait "${holder_pid}" || true
    ml_expect "the blocked read counted nothing" "0" \
        "$(stat_field "${root}" s8 read_count)"
    ml_run_ok "${root}" "${out}/after-release" get s8 s8.md
    ml_expect "reads resume once the lock is released" "1" \
        "$(stat_field "${root}" s8 read_count)"
    ml_note "the namespace lock is a non-blocking exclusive flock, so a competing CLI process fails fast instead of queueing; this is recorded as designed behaviour, not a defect"

    # Reset the counter so the convergence assertion measures only the burst.
    local record
    record=$(stat_path "${root}" s8)
    rm -f "${record}"

    local -a pids=()
    local i
    for i in $(seq 1 48); do
        (
            local try
            for try in $(seq 1 100); do
                if TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" get s8 s8.md \
                    > "${out}/r-${i}.stdout" 2> "${out}/r-${i}.stderr"; then
                    printf '0' > "${out}/r-${i}.code"
                    exit 0
                fi
                sleep 0.02
            done
            printf '1' > "${out}/r-${i}.code"
        ) &
        pids+=("$!")
    done
    local pid
    for pid in "${pids[@]}"; do
        wait "${pid}" || true
    done

    local ok failed
    ok=$(count_matching '^0$' "${out}"/r-*.code)
    failed=$(count_matching '^1$' "${out}"/r-*.code)
    ml_expect "every retried reader eventually succeeds" "48" "${ok}"
    ml_expect "no retried reader is left failed" "0" "${failed}"
    ml_expect "the read counter converges to exactly 48" "48" \
        "$(stat_field "${root}" s8 read_count)"

    local bad
    bad=$(count_not_matching 'body s8' "${out}"/r-*.stdout)
    ml_expect "every reader received the full payload" "0" "${bad}"

    ml_run_ok "${root}" "${out}/stat-json" stat s8 --format json
    ml_expect "the record is still valid JSON" "1" \
        "$(jq -r '.schema_version' "${out}/stat-json.stdout")"
    ml_expect "the record keeps the exact read count" "48" \
        "$(jq -r '.read_count' "${out}/stat-json.stdout")"
    end_case
}

# hold_lock takes an exclusive flock on a path from a background subshell and
# waits until the lock is provably held.
#
# The holder stays alive until release_lock removes the ready file, so the
# caller never depends on a sleep duration and never leaves a stray process
# behind. The PID is returned through the global HOLDER_PID instead of stdout:
# a command substitution runs the function in a subshell, and the subshell exit
# kills the background holder it started, which silently releases the lock.
hold_lock() {
    local lock_path="$1" ready="$2"
    rm -f "${ready}"
    (
        exec 9>"${lock_path}"
        flock -x 9
        : > "${ready}"
        # A subshell is not a function, so "local" is invalid here and would
        # abort the holder under "set -e" right after the ready file appears.
        waited=0
        while [[ -e "${ready}" && "${waited}" -lt 3000 ]]; do
            sleep 0.01
            waited=$((waited + 1))
        done
    ) &
    HOLDER_PID=$!
    if ! ml_wait_for_file "${ready}" 10; then
        kill "${HOLDER_PID}" 2>/dev/null || true
        wait "${HOLDER_PID}" 2>/dev/null || true
        HOLDER_PID=""
        return 1
    fi
    return 0
}

# release_lock drops a held lock and reaps the holder process.
release_lock() {
    local ready="$1" pid="$2"
    rm -f "${ready}"
    wait "${pid}" 2>/dev/null || true
}

# run_stat_09 proves concurrent writers on distinct files all land and are all
# counted exactly once.
run_stat_09() {
    begin_case STAT-09 P0 I
    local root out
    root=$(ml_case_root stat09)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s9 "${out}"
    ml_expect "the fixture records one write" "1" \
        "$(stat_field "${root}" s9 write_count)"

    local i
    for i in $(seq 1 12); do
        printf 'payload %s\n' "${i}" > "${out}/f${i}.txt"
    done

    local -a pids=()
    for i in $(seq 1 12); do
        (
            local try
            for try in $(seq 1 100); do
                if TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" put s9 "f${i}.txt" \
                    --from "${out}/f${i}.txt" \
                    > "${out}/w-${i}.stdout" 2> "${out}/w-${i}.stderr"; then
                    printf '0' > "${out}/w-${i}.code"
                    exit 0
                fi
                sleep 0.02
            done
            printf '1' > "${out}/w-${i}.code"
        ) &
        pids+=("$!")
    done
    local pid
    for pid in "${pids[@]}"; do
        wait "${pid}" || true
    done

    ml_expect "every concurrent writer succeeds" "12" \
        "$(count_matching '^0$' "${out}"/w-*.code)"
    ml_expect "no concurrent writer is left failed" "0" \
        "$(count_matching '^1$' "${out}"/w-*.code)"
    ml_expect "the write counter counts the create plus every put" "13" \
        "$(stat_field "${root}" s9 write_count)"
    ml_expect "concurrent writes do not count reads" "0" \
        "$(stat_field "${root}" s9 read_count)"

    local bad=0
    for i in $(seq 1 12); do
        if ! TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" get s9 "f${i}.txt" 2>/dev/null \
            | grep -qx "payload ${i}"; then
            bad=$((bad + 1))
        fi
    done
    ml_expect "every concurrent write landed intact" "0" "${bad}"
    end_case
}

# run_stat_10 proves a concurrent duplicate create has exactly one winner.
run_stat_10() {
    begin_case STAT-10 P0 I
    local root out
    root=$(ml_case_root stat10)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/dup.md" "duplicate create fixture" "body dup"

    local -a pids=()
    local i
    for i in $(seq 1 6); do
        (
            local try
            for try in $(seq 1 100); do
                if TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" create dup \
                    --from "${out}/dup.md" \
                    > "${out}/c-${i}.stdout" 2> "${out}/c-${i}.stderr"; then
                    printf '0' > "${out}/c-${i}.code"
                    exit 0
                fi
                sleep 0.02
            done
            printf '1' > "${out}/c-${i}.code"
        ) &
        pids+=("$!")
    done
    local pid
    for pid in "${pids[@]}"; do
        wait "${pid}" || true
    done

    ml_expect "exactly one concurrent create wins" "1" \
        "$(count_matching '^0$' "${out}"/c-*.code)"
    ml_expect "the losing creates fail" "5" \
        "$(count_matching '^1$' "${out}"/c-*.code)"

    local losers=0 f base
    for f in "${out}"/c-*.code; do
        [[ -f "${f}" ]] || continue
        if grep -qx '1' "${f}"; then
            base="${f%.code}"
            if grep -qF 'object already exists' "${base}.stderr" 2>/dev/null \
                || grep -qF 'namespace lock' "${base}.stderr" 2>/dev/null; then
                losers=$((losers + 1))
            fi
        fi
    done
    ml_expect "every losing create reports a duplicate or lock conflict" "5" "${losers}"

    ml_run_ok "${root}" "${out}/list" list --format json
    ml_expect "the store holds exactly one object" "1" \
        "$(jq 'length' "${out}/list.stdout")"
    ml_expect "the surviving object is active" "active" \
        "$(jq -r '.[0].status' "${out}/list.stdout")"
    end_case
}

# run_stat_11 proves the hash object lock rejects every write while leaving
# reads available.
run_stat_11() {
    begin_case STAT-11 P0 I
    local root out
    root=$(ml_case_root stat11)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s11 "${out}"
    local lock_path
    lock_path="$(ml_meta_dir "${root}" s11)/lock"
    ml_expect_file "the object lock file exists" "${lock_path}" file

    hold_lock "${lock_path}" "${out}/holder.ready"
    ml_expect "the object lock holder started" "yes" \
        "$([[ -n "${HOLDER_PID}" ]] && echo yes || echo no)"

    printf 'x\n' > "${out}/x.txt"
    ml_run_fail "${root}" "${out}/put" put s11 x.txt --from "${out}/x.txt"
    ml_expect_contains "put is rejected while the object lock is held" \
        "${out}/put.stderr" "acquire metadata lock"
    ml_run_fail "${root}" "${out}/update" update s11 --description changed
    ml_expect_contains "update is rejected while the object lock is held" \
        "${out}/update.stderr" "acquire metadata lock"
    ml_run_fail "${root}" "${out}/tag" tag add s11 locked
    ml_expect_contains "tag add is rejected while the object lock is held" \
        "${out}/tag.stderr" "acquire metadata lock"
    ml_run_fail "${root}" "${out}/move" move s11 moved
    ml_expect_contains "move is rejected while the object lock is held" \
        "${out}/move.stderr" "acquire metadata lock"
    ml_run_fail "${root}" "${out}/delete" delete s11
    ml_expect_contains "delete is rejected while the object lock is held" \
        "${out}/delete.stderr" "acquire metadata lock"
    ml_run_fail "${root}" "${out}/file-write" file write name=s11.md --object s11 \
        --from "${out}/x.txt"
    ml_expect_contains "file write is rejected while the object lock is held" \
        "${out}/file-write.stderr" "acquire metadata lock"

    ml_run_ok "${root}" "${out}/get" get s11 s11.md
    ml_expect_contains "reads stay available while the object lock is held" \
        "${out}/get.stdout" "body s11"

    release_lock "${out}/holder.ready" "${HOLDER_PID}"

    ml_run_ok "${root}" "${out}/put-after" put s11 x.txt --from "${out}/x.txt"
    ml_run_ok "${root}" "${out}/get-after" get s11 x.txt
    ml_expect_contains "writes resume once the object lock is released" \
        "${out}/get-after.stdout" "x"
    end_case
}

# run_stat_12 proves TOPSAILAI_DATA_READ_LOCK makes reads take the object lock.
run_stat_12() {
    begin_case STAT-12 P1 I
    local root out
    root=$(ml_case_root stat12)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s12 "${out}"
    local lock_path
    lock_path="$(ml_meta_dir "${root}" s12)/lock"

    hold_lock "${lock_path}" "${out}/holder.ready"
    ml_expect "the object lock holder started" "yes" \
        "$([[ -n "${HOLDER_PID}" ]] && echo yes || echo no)"

    ml_run_fail "${root}" "${out}/read-lock" --env TOPSAILAI_DATA_READ_LOCK=1 \
        get s12 s12.md
    ml_expect_contains "READ_LOCK=1 makes reads take the object lock" \
        "${out}/read-lock.stderr" "acquire metadata lock"
    ml_run_ok "${root}" "${out}/no-read-lock" --env TOPSAILAI_DATA_READ_LOCK=0 \
        get s12 s12.md
    ml_expect_contains "READ_LOCK=0 keeps reads lock free" \
        "${out}/no-read-lock.stdout" "body s12"

    release_lock "${out}/holder.ready" "${HOLDER_PID}"

    ml_run_ok "${root}" "${out}/read-lock-after" --env TOPSAILAI_DATA_READ_LOCK=1 \
        get s12 s12.md
    ml_expect_contains "READ_LOCK=1 reads succeed once the lock is free" \
        "${out}/read-lock-after.stdout" "body s12"
    end_case
}

# run_stat_13 proves the namespace lock is taken before any object work, so a
# rejected command publishes nothing.
run_stat_13() {
    begin_case STAT-13 P1 I
    local root out
    root=$(ml_case_root stat13)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_run_ok "${root}" "${out}/init" list
    local ns_lock="${root}/.topsailai-data-namespace.lock"
    ml_expect_file "the namespace lock file exists" "${ns_lock}" file

    hold_lock "${ns_lock}" "${out}/holder.ready"
    ml_expect "the namespace lock holder started" "yes" \
        "$([[ -n "${HOLDER_PID}" ]] && echo yes || echo no)"

    ml_make_markdown "${out}/n13.md" "namespace fixture" "body n13"
    ml_run_fail "${root}" "${out}/create" create n13 --from "${out}/n13.md"
    ml_expect_contains "create is rejected while the namespace lock is held" \
        "${out}/create.stderr" "namespace lock"
    ml_expect_file "the rejected create publishes no metadata" \
        "$(ml_meta_dir "${root}" n13)" absent

    release_lock "${out}/holder.ready" "${HOLDER_PID}"

    ml_run_ok "${root}" "${out}/create-after" create n13 --from "${out}/n13.md"
    ml_expect_file "the create succeeds after the namespace lock is released" \
        "$(ml_meta_dir "${root}" n13)" dir
    end_case
}

# run_stat_14 proves a reader never observes a partially written payload while
# writers replace the same file.
run_stat_14() {
    begin_case STAT-14 P1 I
    local root out
    root=$(ml_case_root stat14)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s14 "${out}"

    local i
    for i in $(seq 1 6); do
        {
            local n
            for n in $(seq 1 200); do
                printf 'value-%s line-%s\n' "${i}" "${n}"
            done
        } > "${out}/v${i}.txt"
    done

    local -a pids=()
    for i in $(seq 1 6); do
        (
            local try
            for try in $(seq 1 100); do
                if TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" put s14 shared.txt \
                    --from "${out}/v${i}.txt" \
                    > "${out}/w-${i}.stdout" 2> "${out}/w-${i}.stderr"; then
                    printf '0' > "${out}/w-${i}.code"
                    exit 0
                fi
                sleep 0.02
            done
            printf '1' > "${out}/w-${i}.code"
        ) &
        pids+=("$!")
    done
    for i in $(seq 1 12); do
        (
            local try
            for try in $(seq 1 100); do
                if TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" get s14 shared.txt \
                    > "${out}/r-${i}.stdout" 2> "${out}/r-${i}.stderr"; then
                    printf '0' > "${out}/r-${i}.code"
                    exit 0
                fi
                sleep 0.02
            done
            printf '1' > "${out}/r-${i}.code"
        ) &
        pids+=("$!")
    done
    local pid
    for pid in "${pids[@]}"; do
        wait "${pid}" || true
    done

    ml_expect "every racing writer succeeds" "6" \
        "$(count_matching '^0$' "${out}"/w-*.code)"
    ml_expect "every racing reader succeeds" "12" \
        "$(count_matching '^0$' "${out}"/r-*.code)"

    local -a allowed=()
    for i in $(seq 1 6); do
        allowed+=("$(sha256sum "${out}/v${i}.txt" | awk '{print $1}')")
    done
    local partial=0 f digest hit
    for f in "${out}"/r-*.stdout; do
        [[ -f "${f}" ]] || continue
        digest=$(sha256sum "${f}" | awk '{print $1}')
        hit=0
        local a
        for a in "${allowed[@]}"; do
            if [[ "${a}" == "${digest}" ]]; then
                hit=1
                break
            fi
        done
        if [[ "${hit}" -eq 0 ]]; then
            partial=$((partial + 1))
        fi
    done
    ml_expect "no reader observed a partial payload" "0" "${partial}"

    ml_run_ok "${root}" "${out}/final" get s14 shared.txt
    local final_digest final_ok=0
    final_digest=$(sha256sum "${out}/final.stdout" | awk '{print $1}')
    local a2
    for a2 in "${allowed[@]}"; do
        if [[ "${a2}" == "${final_digest}" ]]; then
            final_ok=1
            break
        fi
    done
    ml_expect "the final payload is one complete written version" "1" "${final_ok}"
    end_case
}

# run_stat_15 proves an interrupted read leaves the store usable and the payload
# intact, and that the interrupted process is gone.
run_stat_15() {
    begin_case STAT-15 P1 I
    local root out
    root=$(ml_case_root stat15)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s15 "${out}"
    head -c 20000000 /dev/urandom > "${out}/big.bin"
    local big_sha
    big_sha=$(sha256sum "${out}/big.bin" | awk '{print $1}')
    ml_run_ok "${root}" "${out}/put" put s15 big.bin --from "${out}/big.bin"

    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" get-archive s15 \
        > "${out}/archive.tar" 2> "${out}/archive.stderr" &
    local pid=$!
    sleep 0.05
    kill -TERM "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true

    local alive=0
    if kill -0 "${pid}" 2>/dev/null; then
        alive=1
        kill -KILL "${pid}" 2>/dev/null || true
    fi
    ml_expect "the interrupted process is gone" "0" "${alive}"

    ml_run_ok "${root}" "${out}/list" list --format json
    ml_expect "the store still lists the object" "s15" \
        "$(jq -r '.[0].id' "${out}/list.stdout")"

    ml_run_ok "${root}" "${out}/get" get s15 big.bin
    ml_expect_sha "the payload is unchanged after the interruption" \
        "${out}/get.stdout" "${big_sha}"
    end_case
}

# run_stat_16 records the STAT_FLUSH contract, including the fact that the async
# mode currently performs the same synchronous write as the sync mode.
run_stat_16() {
    begin_case STAT-16 P2 I
    local root out
    root=$(ml_case_root stat16)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s16 "${out}"

    ml_run_ok "${root}" "${out}/sync" --env TOPSAILAI_DATA_STAT_FLUSH=sync \
        get s16 s16.md
    ml_run_ok "${root}" "${out}/async" --env TOPSAILAI_DATA_STAT_FLUSH=async \
        get s16 s16.md
    ml_run_fail "${root}" "${out}/bogus" --env TOPSAILAI_DATA_STAT_FLUSH=bogus \
        get s16 s16.md
    ml_expect_contains "an invalid STAT_FLUSH value is rejected" \
        "${out}/bogus.stderr" "must be sync or async"

    ml_expect "both accepted flush modes count the read" "2" \
        "$(stat_field "${root}" s16 read_count)"
    ml_note "STAT_FLUSH=async currently performs the same synchronous best-effort write as sync; this is recorded as a known limitation, not a defect"
    end_case
}

# run_stat_17 proves stat ranking stays consistent while writes are in flight.
run_stat_17() {
    begin_case STAT-17 P2 I
    local root out
    root=$(ml_case_root stat17)
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    make_object "${root}" s17 "${out}"

    local i
    for i in $(seq 1 8); do
        printf 'payload %s\n' "${i}" > "${out}/f${i}.txt"
    done

    local -a pids=()
    for i in $(seq 1 8); do
        (
            local try
            for try in $(seq 1 100); do
                if TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" put s17 "f${i}.txt" \
                    --from "${out}/f${i}.txt" \
                    > "${out}/w-${i}.stdout" 2> "${out}/w-${i}.stderr"; then
                    printf '0' > "${out}/w-${i}.code"
                    exit 0
                fi
                sleep 0.02
            done
            printf '1' > "${out}/w-${i}.code"
        ) &
        pids+=("$!")
    done
    for i in $(seq 1 8); do
        (
            local try
            for try in $(seq 1 100); do
                if TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" stat top --by write \
                    --format json > "${out}/t-${i}.stdout" 2> "${out}/t-${i}.stderr"; then
                    printf '0' > "${out}/t-${i}.code"
                    exit 0
                fi
                sleep 0.02
            done
            printf '1' > "${out}/t-${i}.code"
        ) &
        pids+=("$!")
    done
    local pid
    for pid in "${pids[@]}"; do
        wait "${pid}" || true
    done

    ml_expect "every concurrent writer succeeds" "8" \
        "$(count_matching '^0$' "${out}"/w-*.code)"
    ml_expect "every concurrent ranking succeeds" "8" \
        "$(count_matching '^0$' "${out}"/t-*.code)"

    local invalid=0 f
    for f in "${out}"/t-*.stdout; do
        [[ -f "${f}" ]] || continue
        if ! jq -e 'type == "array"' "${f}" > /dev/null 2>&1; then
            invalid=$((invalid + 1))
        fi
    done
    ml_expect "every ranking result is a valid JSON array" "0" "${invalid}"

    ml_run_ok "${root}" "${out}/final" stat top --by write --format json
    ml_expect "the final ranking is valid JSON" "array" \
        "$(jq -r 'type' "${out}/final.stdout")"
    ml_expect "the final ranking reports the exact write count" "9" \
        "$(jq -r '.[0].write_count' "${out}/final.stdout")"
    end_case
}

CASES=(STAT-01 STAT-02 STAT-03 STAT-04 STAT-05 STAT-06 STAT-07 STAT-08
    STAT-09 STAT-10 STAT-11 STAT-12 STAT-13 STAT-14 STAT-15 STAT-16 STAT-17)
for case_id in "${CASES[@]}"; do
    if ! selected "${case_id}" "$@"; then
        continue
    fi
    case "${case_id}" in
        STAT-01) run_stat_01 ;;
        STAT-02) run_stat_02 ;;
        STAT-03) run_stat_03 ;;
        STAT-04) run_stat_04 ;;
        STAT-05) run_stat_05 ;;
        STAT-06) run_stat_06 ;;
        STAT-07) run_stat_07 ;;
        STAT-08) run_stat_08 ;;
        STAT-09) run_stat_09 ;;
        STAT-10) run_stat_10 ;;
        STAT-11) run_stat_11 ;;
        STAT-12) run_stat_12 ;;
        STAT-13) run_stat_13 ;;
        STAT-14) run_stat_14 ;;
        STAT-15) run_stat_15 ;;
        STAT-16) run_stat_16 ;;
        STAT-17) run_stat_17 ;;
    esac
done

if grep -q '"status":"FAIL"' "${ML_RESULTS}" 2>/dev/null; then
    exit 1
fi
exit 0
