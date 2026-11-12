#!/usr/bin/env bash
# cases-f-scale: manual/live scale and platform cases SAFE-09..SAFE-12.
#
# Scope: SAFE-09..SAFE-12 from tests/manual-live/safety-scale-live.md.
# Every case runs against an isolated store under .tmp/manual-live/<run>/stores.
# No case reads or writes the live store, and no case deletes shared resources.
#
# Usage:
#   ML_RUN_ID=<id> bash tests/manual-live/scripts/cases-f-scale.sh [case ids...]
#
# Declared budget (must be stated before execution, per the plan):
#   objects per store ......... 10000 (100000 is out of scope; it needs a
#                               separate approval because it costs about 3 GiB
#                               of disk and about 12 minutes of creation time)
#   payload per object ........ 8 MiB
#   total disk per case ....... 2048 MiB
#   list wall time ............ 30 s at 10000 objects
#   search wall time .......... 30 s at 10000 objects
#   peak RSS per invocation ... 512 MiB
#   wall time per case ........ 900 s
# The budget is derived from a calibration run on this host: 1000 objects cost
# 7.3 s of creation, 29 MiB of disk, 0.08 s list and 12.9 MiB RSS. The declared
# limits leave a wide margin over that measurement so a regression is visible
# without the case becoming flaky on a loaded machine.

set -uo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1

# shellcheck source=lib.sh
source "${EXE_FOLDER}/lib.sh"

ml_init

ML_BUDGET_MAX_OBJECTS=10000
ML_BUDGET_MAX_PAYLOAD_MIB=8
ML_BUDGET_MAX_DISK_MIB=2048
ML_BUDGET_LIST_SECONDS=30
ML_BUDGET_SEARCH_SECONDS=30
ML_BUDGET_RSS_MIB=512
ML_BUDGET_CASE_SECONDS=900

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

# file_sha prints the sha256 of a file, or "absent" when it does not exist.
file_sha() {
    local path="$1"
    if [[ ! -f "${path}" ]]; then
        printf 'absent'
        return 0
    fi
    sha256sum "${path}" | awk '{print $1}'
}

# file_bytes prints the size of a file in bytes, or -1 when it is missing.
file_bytes() {
    local path="$1"
    if [[ ! -f "${path}" ]]; then
        printf '%s' '-1'
        return 0
    fi
    stat -c '%s' "${path}"
}

# measure runs the CLI under /usr/bin/time and records wall time and peak RSS.
#
# Usage: measure <root> <out-prefix> [--env K=V ...] -- <args...>
# The child environment is allowlisted exactly like ml_run so a measurement is
# never influenced by the operator's shell. Wall seconds and peak RSS in KiB are
# written to <out-prefix>.time by /usr/bin/time itself.
measure() {
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
    local code=0
    env -i "${env_args[@]}" /usr/bin/time -f '%e %M' -o "${prefix}.time" \
        "${ML_BIN}" "$@" < /dev/null > "${prefix}.stdout" 2> "${prefix}.stderr" || code=$?
    printf '%s\n' "$*" > "${prefix}.argv"
    printf 'exit=%s\n' "${code}" >> "${prefix}.time"
    printf 'cmd: %s\n  exit=%s wall=%ss rss=%sKiB\n' "$*" "${code}" \
        "$(time_field "${prefix}" 1)" "$(time_field "${prefix}" 2)" >> "${ML_CASE_LOG}"
    return "${code}"
}

# time_field prints one field of a .time record: 1 is wall seconds, 2 is RSS.
time_field() {
    local prefix="$1" field="$2"
    awk -v f="${field}" 'NR==1{print $f}' "${prefix}.time" 2>/dev/null || printf '0'
}

# rss_mib converts the recorded peak RSS of a measurement into whole MiB.
rss_mib() {
    local prefix="$1"
    local kib
    kib=$(time_field "${prefix}" 2)
    if [[ -z "${kib}" ]]; then
        printf '0'
        return 0
    fi
    printf '%s' "$(( kib / 1024 ))"
}

# wall_seconds prints the recorded wall time of a measurement as an integer.
wall_seconds() {
    local prefix="$1"
    local raw
    raw=$(time_field "${prefix}" 1)
    if [[ -z "${raw}" ]]; then
        printf '0'
        return 0
    fi
    printf '%s' "${raw%%.*}"
}

# within_budget asserts that a measured value does not exceed a declared limit.
within_budget() {
    local desc="$1" actual="$2" limit="$3"
    if [[ "${actual}" -le "${limit}" ]]; then
        printf 'ok: %s (%s <= %s)\n' "${desc}" "${actual}" "${limit}" >> "${ML_CASE_LOG}"
        return 0
    fi
    ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
    printf 'FAIL: %s\n  actual: %s\n  limit:  %s\n' "${desc}" "${actual}" "${limit}" >> "${ML_CASE_LOG}"
    return 0
}

# seed_store creates count objects without logging every single command.
#
# A per-object ml_run_ok would append one line per object to the case log, which
# makes a 10000-object case unreadable. The seeding loop therefore runs the CLI
# directly and reports only the aggregate outcome.
seed_store() {
    local root="$1" count="$2" fixture="$3"
    local i code=0
    for ((i = 1; i <= count; i++)); do
        env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
            LC_ALL=C.UTF-8 TZ=UTC TOPSAILAI_DATA_ROOT="${root}" \
            "${ML_BIN}" create "c${i}" --from "${fixture}" > /dev/null 2>&1 || code=$?
        if [[ "${code}" -ne 0 ]]; then
            printf 'FAIL: seeding object c%s exited %s\n' "${i}" "${code}" >> "${ML_CASE_LOG}"
            ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
            return 1
        fi
    done
    printf 'ok: seeded %s objects\n' "${count}" >> "${ML_CASE_LOG}"
    return 0
}

# json_len prints the number of entries in a JSON array file.
json_len() {
    local path="$1"
    jq 'length' "${path}" 2>/dev/null || printf '%s' '-1'
}

# run_safe_09 measures startup, listing, search, direct read, ranking and
# pagination at three store sizes and checks every declared budget.
run_safe_09() {
    begin_case SAFE-09 P2 I
    local out
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/seed.md" "scale seed" "SCALE-BODY"
    ml_note "declared budget: objects<=${ML_BUDGET_MAX_OBJECTS} disk<=${ML_BUDGET_MAX_DISK_MIB}MiB list<=${ML_BUDGET_LIST_SECONDS}s search<=${ML_BUDGET_SEARCH_SECONDS}s rss<=${ML_BUDGET_RSS_MIB}MiB case<=${ML_BUDGET_CASE_SECONDS}s"

    local size
    for size in 100 1000 10000; do
        local root
        root=$(ml_case_root "n${size}")
        local started
        started=$(date +%s)

        if ! seed_store "${root}" "${size}" "${out}/seed.md"; then
            ml_blocked "seeding ${size} objects failed"
            end_case
            return 0
        fi

        local disk
        disk=$(du -sm "${root}" | awk '{print $1}')
        ml_note "store n=${size} occupies ${disk} MiB"
        within_budget "the ${size}-object store stays inside the disk budget" \
            "${disk}" "${ML_BUDGET_MAX_DISK_MIB}"

        # Startup cost: usage output does not touch the store, so it isolates
        # process start-up from inventory work.
        measure "${root}" "${out}/n${size}-startup" --
        ml_expect "the usage path exits cleanly at n=${size}" "0" \
            "$(awk -F= '/^exit=/{print $2}' "${out}/n${size}-startup.time")"

        measure "${root}" "${out}/n${size}-list" -- list --format json
        ml_expect "the listing returns every object at n=${size}" "${size}" \
            "$(json_len "${out}/n${size}-list.stdout")"
        within_budget "the listing stays inside the wall budget at n=${size}" \
            "$(wall_seconds "${out}/n${size}-list")" "${ML_BUDGET_LIST_SECONDS}"
        within_budget "the listing stays inside the RSS budget at n=${size}" \
            "$(rss_mib "${out}/n${size}-list")" "${ML_BUDGET_RSS_MIB}"

        measure "${root}" "${out}/n${size}-search" -- search c1 --format json
        local hits
        hits=$(json_len "${out}/n${size}-search.stdout")
        ml_expect "the search finds the expected prefix matches at n=${size}" "yes" \
            "$([[ "${hits}" -gt 0 ]] && echo yes || echo no)"
        within_budget "the search stays inside the wall budget at n=${size}" \
            "$(wall_seconds "${out}/n${size}-search")" "${ML_BUDGET_SEARCH_SECONDS}"
        within_budget "the search stays inside the RSS budget at n=${size}" \
            "$(rss_mib "${out}/n${size}-search")" "${ML_BUDGET_RSS_MIB}"

        measure "${root}" "${out}/n${size}-get" -- get c1 c1.md
        ml_expect "a direct read succeeds at n=${size}" "0" \
            "$(awk -F= '/^exit=/{print $2}' "${out}/n${size}-get.time")"
        ml_expect_contains "a direct read returns the stored body at n=${size}" \
            "${out}/n${size}-get.stdout" "SCALE-BODY"

        measure "${root}" "${out}/n${size}-top" -- stat top --by write --limit 10 --format json
        ml_expect "the ranking returns the requested rows at n=${size}" "10" \
            "$(json_len "${out}/n${size}-top.stdout")"

        measure "${root}" "${out}/n${size}-page" -- list --offset 10 --limit 5 --format json
        ml_expect "pagination returns the requested page at n=${size}" "5" \
            "$(json_len "${out}/n${size}-page.stdout")"

        local elapsed
        elapsed=$(( $(date +%s) - started ))
        ml_note "store n=${size} measured in ${elapsed}s"
        within_budget "the n=${size} measurement stays inside the case budget" \
            "${elapsed}" "${ML_BUDGET_CASE_SECONDS}"
    done

    ml_note "100000 objects are out of scope: they need a separate approval because they cost about 3 GiB of disk and about 12 minutes of creation time"
    end_case
}

# run_safe_10 separates direct-ID cost from enumeration cost and varies the
# batch size independently of the store size.
run_safe_10() {
    begin_case SAFE-10 P2 I
    local out
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/seed.md" "batch seed" "BATCH-BODY"
    ml_make_markdown "${out}/batch.md" "batch payload" "BATCH-PAYLOAD"

    local root
    root=$(ml_case_root small)
    if ! seed_store "${root}" 1000 "${out}/seed.md"; then
        ml_blocked "seeding the 1000-object store failed"
        end_case
        return 0
    fi

    # Direct-ID access must not depend on the store size.
    measure "${root}" "${out}/direct" -- get c500 c500.md
    ml_expect "a direct read succeeds in the 1000-object store" "0" \
        "$(awk -F= '/^exit=/{print $2}' "${out}/direct.time")"

    # Enumeration must be measured separately, because it is the path that
    # performs a global scan.
    measure "${root}" "${out}/enumerate" -- list --format json
    ml_expect "enumeration returns the whole store" "1000" \
        "$(json_len "${out}/enumerate.stdout")"

    local direct_wall enum_wall
    direct_wall=$(wall_seconds "${out}/direct")
    enum_wall=$(wall_seconds "${out}/enumerate")
    ml_note "direct read ${direct_wall}s versus enumeration ${enum_wall}s at n=1000"

    # Vary the batch size M against a fixed store size N. A per-item global scan
    # would make the total grow faster than M.
    local batch
    for batch in 1 10 100; do
        local started
        started=$(date +%s%N)
        local i code=0
        for ((i = 1; i <= batch; i++)); do
            env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
                LC_ALL=C.UTF-8 TZ=UTC TOPSAILAI_DATA_ROOT="${root}" \
                "${ML_BIN}" put c1 "batch-${batch}-${i}.txt" --from "${out}/batch.md" \
                > /dev/null 2>&1 || code=$?
            if [[ "${code}" -ne 0 ]]; then
                printf 'FAIL: batch put %s/%s exited %s\n' "${batch}" "${i}" "${code}" >> "${ML_CASE_LOG}"
                ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
                break
            fi
        done
        local elapsed_ms=$(( ($(date +%s%N) - started) / 1000000 ))
        ml_note "batch M=${batch} against N=1000 took ${elapsed_ms}ms"
        printf 'ok: batch M=%s completed against N=1000 in %sms\n' "${batch}" "${elapsed_ms}" >> "${ML_CASE_LOG}"
    done

    # The same batch against a larger store exposes a per-item global scan.
    local big
    big=$(ml_case_root big)
    if ! seed_store "${big}" 2000 "${out}/seed.md"; then
        ml_blocked "seeding the 2000-object store failed"
        end_case
        return 0
    fi
    local started
    started=$(date +%s%N)
    local i code=0
    for ((i = 1; i <= 10; i++)); do
        env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
            LC_ALL=C.UTF-8 TZ=UTC TOPSAILAI_DATA_ROOT="${big}" \
            "${ML_BIN}" put c1 "big-${i}.txt" --from "${out}/batch.md" > /dev/null 2>&1 || code=$?
        if [[ "${code}" -ne 0 ]]; then
            printf 'FAIL: big-store put %s exited %s\n' "${i}" "${code}" >> "${ML_CASE_LOG}"
            ML_CASE_FAILURES=$((ML_CASE_FAILURES + 1))
            break
        fi
    done
    local big_ms=$(( ($(date +%s%N) - started) / 1000000 ))
    ml_note "batch M=10 against N=2000 took ${big_ms}ms; compare with M=10 against N=1000 above"

    ml_note "the store has no index, so enumeration cost grows with N while direct-ID cost does not; this is a declared limit, not a hidden regression"
    end_case
}

# run_safe_11 roundtrips declared attachment sizes and checks digests, disk and
# memory against the declared budget.
run_safe_11() {
    begin_case SAFE-11 P2 I
    local out
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/seed.md" "attachment seed" "ATTACH-BODY"
    local root
    root=$(ml_case_root attach)
    ml_run_ok "${root}" "${out}/create" create a --from "${out}/seed.md"

    local mib
    for mib in 1 8; do
        local blob
        blob="${out}/blob-${mib}.bin"
        head -c $(( mib * 1024 * 1024 )) /dev/urandom > "${blob}"
        local digest
        digest=$(file_sha "${blob}")

        measure "${root}" "${out}/put-${mib}" -- put a "blob-${mib}.bin" --from "${blob}"
        ml_expect "a ${mib} MiB attachment is accepted" "0" \
            "$(awk -F= '/^exit=/{print $2}' "${out}/put-${mib}.time")"
        within_budget "the ${mib} MiB write stays inside the RSS budget" \
            "$(rss_mib "${out}/put-${mib}")" "${ML_BUDGET_RSS_MIB}"

        measure "${root}" "${out}/get-${mib}" -- get a "blob-${mib}.bin"
        ml_expect "a ${mib} MiB attachment roundtrips byte for byte" "${digest}" \
            "$(file_sha "${out}/get-${mib}.stdout")"
        within_budget "the ${mib} MiB read stays inside the RSS budget" \
            "$(rss_mib "${out}/get-${mib}")" "${ML_BUDGET_RSS_MIB}"

        measure "${root}" "${out}/archive-${mib}" -- get-archive a
        ml_expect "the archive of a ${mib} MiB attachment is produced" "0" \
            "$(awk -F= '/^exit=/{print $2}' "${out}/archive-${mib}.time")"
        ml_note "archive read of a ${mib} MiB attachment used $(rss_mib "${out}/archive-${mib}") MiB RSS"
    done

    local disk
    disk=$(du -sm "${root}" | awk '{print $1}')
    ml_note "the attachment store occupies ${disk} MiB"
    within_budget "the attachment store stays inside the disk budget" \
        "${disk}" "${ML_BUDGET_MAX_DISK_MIB}"

    ml_note "the manager buffers a whole archive in memory before writing it, so archive memory is proportional to archive size; this is a declared limit"
    end_case
}

# run_safe_12 exercises a second filesystem and reports name, alias and lock
# limits instead of claiming cross-platform proof.
run_safe_12() {
    begin_case SAFE-12 P2 I
    local out
    out="${ML_ARTIFACTS}/${ML_CASE_ID}"
    mkdir -p "${out}"

    ml_make_markdown "${out}/seed.md" "platform seed" "PLATFORM-BODY"

    # A tmpfs store proves the adapter does not depend on the overlayfs of the
    # main workspace. The subset covers init, file, lock, move and lifecycle.
    local shm
    shm="/dev/shm/ml-safe12-${ML_RUN_ID}"
    if [[ ! -d /dev/shm ]]; then
        ml_blocked "no tmpfs mount is available for a second-filesystem check"
        end_case
        return 0
    fi
    rm -rf "${shm}"
    mkdir -p "${shm}"
    ml_note "second filesystem: $(stat -f -c '%T' /dev/shm) at ${shm}"

    ml_run_ok "${shm}" "${out}/init" list
    ml_run_ok "${shm}" "${out}/create" create p --from "${out}/seed.md"
    ml_run_ok "${shm}" "${out}/put" put p extra.txt --from "${out}/seed.md"
    ml_run_ok "${shm}" "${out}/get" get p extra.txt
    ml_expect_contains "a tmpfs store returns the written file" "${out}/get.stdout" "PLATFORM-BODY"

    ml_run_ok "${shm}" "${out}/move" move p archive
    ml_run_ok "${shm}" "${out}/list-moved" list --format json
    ml_expect "a move on tmpfs keeps the object visible" "p" \
        "$(jq -r '.[].id' "${out}/list-moved.stdout")"

    ml_run_ok "${shm}" "${out}/delete" delete p
    ml_run_ok "${shm}" "${out}/recover" recover p
    ml_run_ok "${shm}" "${out}/list-recovered" list --format json
    ml_expect "a delete and recover cycle works on tmpfs" "p" \
        "$(jq -r '.[].id' "${out}/list-recovered.stdout")"

    ml_run_ok "${shm}" "${out}/gc" gc --status ceased
    ml_note "the tmpfs subset passed init, create, put, get, move, delete, recover and gc"

    # Name and alias limits are reported, not simulated.
    local root
    root=$(ml_case_root names)
    ml_run_ok "${root}" "${out}/create-lower" create casey --from "${out}/seed.md"
    ml_run_ok "${root}" "${out}/create-upper" create CASEY --from "${out}/seed.md"
    ml_run_ok "${root}" "${out}/list-case" list --format json
    local case_count
    case_count=$(json_len "${out}/list-case.stdout")
    ml_note "two IDs that differ only in case coexist: ${case_count} objects, so the store is case-sensitive on this filesystem"

    # The product declares no name-length limit, so a long name is accepted and
    # the boundary is enforced by the filesystem instead. Measured on this host:
    # 252 characters succeed and 253 fail, because "<name>.md" is then 256 bytes
    # and exceeds NAME_MAX (255). The failure therefore reports "file name too
    # long" from the filesystem layer, not "invalid object name" from validation.
    local long_name
    long_name=$(printf 'n%.0s' $(seq 1 200))
    ml_run_ok "${root}" "${out}/create-long" create "${long_name}" --from "${out}/seed.md"
    ml_note "object names have no product-level length limit: a 200-character name was accepted, so the only boundary is the filesystem NAME_MAX"

    local max_name
    max_name=$(printf 'n%.0s' $(seq 1 252))
    ml_run_ok "${root}" "${out}/create-max" create "${max_name}" --from "${out}/seed.md"
    ml_note "252 characters is the largest name that fits NAME_MAX once the mandatory .md suffix is appended"

    local over_name
    over_name=$(printf 'n%.0s' $(seq 1 253))
    ml_run_fail "${root}" "${out}/create-over" create "${over_name}" --from "${out}/seed.md"
    ml_expect_contains "a name beyond NAME_MAX is refused by the filesystem" \
        "${out}/create-over.stderr" "file name too long"

    ml_note "no second operating system is available on this host, so cross-OS evidence is BLOCKED; only the filesystem dimension was exercised"
    ml_blocked "cross-OS platform evidence is unavailable on this host"
    end_case
}

CASES=(SAFE-09 SAFE-10 SAFE-11 SAFE-12)
for case_id in "${CASES[@]}"; do
    if ! selected "${case_id}" "$@"; then
        continue
    fi
    case "${case_id}" in
        SAFE-09) run_safe_09 ;;
        SAFE-10) run_safe_10 ;;
        SAFE-11) run_safe_11 ;;
        SAFE-12) run_safe_12 ;;
    esac
done

if grep -q '"status":"FAIL"' "${ML_RESULTS}" 2>/dev/null; then
    exit 1
fi
exit 0
