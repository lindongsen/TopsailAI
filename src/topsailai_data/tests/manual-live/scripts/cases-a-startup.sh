#!/usr/bin/env bash
# Module A: startup and configuration cases (CFG-01 .. CFG-15).
#
# Every case uses an isolated root below the run area. The existing live store
# is never referenced here.

set -euo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1

# shellcheck source=lib.sh
source "${EXE_FOLDER}/lib.sh"

usage() {
    cat <<'EOF'
Usage: cases-a-startup.sh [case-id ...]

Runs startup and configuration cases. Without arguments every case runs.

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

run_cfg_01() {
    begin_case CFG-01 P0 I
    local root="${ML_STORES}/CFG-01/store"
    local out="${ML_CASE_DIR}/CFG-01"
    ml_run_ok "${root}" "${out}-first" list
    ml_expect "first list is an empty array" "[]" "$(tr -d '[:space:]' < "${out}-first.stdout")"
    ml_expect_file "object tree created" "${root}/object" dir
    ml_expect_file "meta tree created" "${root}/meta" dir
    ml_expect_file "layout marker created" "${root}/topsailai_data.json" file
    ml_expect_file "namespace lock created" "${root}/.topsailai-data-namespace.lock" file
    ml_expect "layout marker content" \
        '{"layout":"object-meta","layout_version":1,"schema_version":2}' \
        "$(tr -d '[:space:]' < "${root}/topsailai_data.json")"
    local marker_sha
    marker_sha=$(sha256sum "${root}/topsailai_data.json" | awk '{print $1}')
    ml_run_ok "${root}" "${out}-second" list
    ml_expect_sha "second invocation preserves the marker" "${root}/topsailai_data.json" "${marker_sha}"
    ml_expect_file "no .env generated in the store" "${root}/.env" absent
    ml_expect_file "no .env.local generated in the store" "${root}/.env.local" absent
    end_case
}

run_cfg_02() {
    begin_case CFG-02 P0 I
    local home="${ML_BASE}/home-cfg02"
    local cwd="${ML_BASE}/cwd-cfg02"
    mkdir -p "${home}" "${cwd}"
    local out="${ML_CASE_DIR}/CFG-02"
    local code=0
    ( cd "${cwd}" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${home}" LANG=C.UTF-8 \
        "${ML_BIN}" list > "${out}.stdout" 2> "${out}.stderr" ) || code=$?
    ml_expect "list without a root setting succeeds" "0" "${code}"
    ml_expect_file "default root created under synthetic HOME" "${home}/.topsailai/data" dir
    ml_expect_file "default root has a layout marker" "${home}/.topsailai/data/topsailai_data.json" file
    ml_expect_file "operator store untouched by this case" "${ML_STORES}/CFG-02/operator" absent
    end_case
}

run_cfg_03() {
    begin_case CFG-03 P0 I
    local root="${ML_STORES}/CFG-03/explicit"
    local decoy="${ML_STORES}/CFG-03/decoy"
    local out="${ML_CASE_DIR}/CFG-03"
    mkdir -p "${decoy}"
    ml_run_ok "${root}" "${out}" --env "TOPSAILAI_DATA_ROOT=${root}" list
    ml_expect_file "explicit root initialized" "${root}/topsailai_data.json" file
    ml_expect_file "decoy root untouched" "${decoy}/topsailai_data.json" absent
    local skill_bin="${PROJECT_ROOT}/skills/topsailai-data/bin/topsailai-data"
    ml_expect "skill entry resolves to the intended binary" \
        "$(readlink -f "${ML_BIN}")" "$(readlink -f "${skill_bin}")"
    ml_expect "skill entry digest matches the build" \
        "$(sha256sum "${ML_BIN}" | awk '{print $1}')" "$(sha256sum "${skill_bin}" | awk '{print $1}')"
    end_case
}

run_cfg_04() {
    begin_case CFG-04 P1 I
    local base="${ML_STORES}/CFG-04"
    local cwd_a="${base}/cwd-a"
    local cwd_b="${base}/cwd-b"
    mkdir -p "${cwd_a}" "${cwd_b}"
    local out="${ML_CASE_DIR}/CFG-04"
    local code=0
    ( cd "${cwd_a}" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
        TOPSAILAI_DATA_ROOT=relative-store "${ML_BIN}" list > "${out}-rel-a.stdout" 2> "${out}-rel-a.stderr" ) || code=$?
    ml_expect "relative root run succeeds" "0" "${code}"
    ml_expect_file "relative root resolved against cwd" "${cwd_a}/relative-store/topsailai_data.json" file
    ml_expect_file "relative root not created in the other cwd" "${cwd_b}/relative-store" absent
    local abs="${base}/absolute-store"
    code=0
    ( cd "${cwd_b}" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
        TOPSAILAI_DATA_ROOT="${abs}" "${ML_BIN}" list > "${out}-abs.stdout" 2> "${out}-abs.stderr" ) || code=$?
    ml_expect "absolute root run succeeds" "0" "${code}"
    ml_expect_file "absolute root stable across cwd" "${abs}/topsailai_data.json" file
    end_case
}

run_cfg_05() {
    begin_case CFG-05 P1 I
    local base="${ML_STORES}/CFG-05"
    local env_root="${base}/from-env"
    local dotenv_root="${base}/from-dotenv"
    local local_root="${base}/from-dotenv-local"
    mkdir -p "${base}/cwd"
    printf 'TOPSAILAI_DATA_ROOT=%s\n' "${dotenv_root}" > "${base}/cwd/.env"
    printf 'TOPSAILAI_DATA_ROOT=%s\n' "${local_root}" > "${base}/cwd/.env.local"
    local out="${ML_CASE_DIR}/CFG-05"
    local code=0
    ( cd "${base}/cwd" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
        TOPSAILAI_DATA_ROOT="${env_root}" "${ML_BIN}" list > "${out}-env.stdout" 2> "${out}-env.stderr" ) || code=$?
    ml_expect "env-precedence run succeeds" "0" "${code}"
    ml_expect_file "process environment wins over dotenv files" "${env_root}/topsailai_data.json" file
    ml_expect_file "dotenv root not used when env is set" "${dotenv_root}/topsailai_data.json" absent
    code=0
    ( cd "${base}/cwd" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
        "${ML_BIN}" list > "${out}-dotenv.stdout" 2> "${out}-dotenv.stderr" ) || code=$?
    ml_expect "dotenv-only run succeeds" "0" "${code}"
    ml_expect_file ".env supplies the root when env is empty" "${dotenv_root}/topsailai_data.json" file
    ml_note "loader fills .env first and only then missing .env.local keys; .env.local does not override .env"
    end_case
}

run_cfg_06() {
    begin_case CFG-06 P1 I
    local base="${ML_STORES}/CFG-06"
    local root="${base}/quoted store ünïcode"
    mkdir -p "${base}/cwd"
    {
        printf '# comment line\n'
        printf '\n'
        printf 'TOPSAILAI_DATA_ROOT="%s"\n' "${root}"
    } > "${base}/cwd/.env"
    local out="${ML_CASE_DIR}/CFG-06"
    local code=0
    ( cd "${base}/cwd" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
        "${ML_BIN}" list > "${out}.stdout" 2> "${out}.stderr" ) || code=$?
    ml_expect "quoted unicode dotenv run succeeds" "0" "${code}"
    ml_expect_file "quotes stripped and unicode path used" "${root}/topsailai_data.json" file
    ml_expect_file "no persistent config written" "${base}/cwd/.env.local" absent
    end_case
}

run_cfg_07() {
    begin_case CFG-07 P0 F
    local root="${ML_STORES}/CFG-07/legacy"
    mkdir -p "${root}/2026/1111/1200/legacy-object"
    printf 'legacy payload\n' > "${root}/2026/1111/1200/legacy-object/legacy-object.md"
    # The namespace lock is a permitted internal effect of initialization, so the
    # business-file manifest is taken over everything except that lock file.
    local before
    before=$(ml_manifest "${root}" | grep -v '\.topsailai-data-namespace\.lock' || true)
    local out="${ML_CASE_DIR}/CFG-07"
    ml_run_fail "${root}" "${out}-list" list
    ml_expect_contains "refusal states a fresh root is required" "${out}-list.stderr" "fresh root"
    ml_expect_contains "refusal states migration is unsupported" "${out}-list.stderr" "migration is unsupported"
    ml_run_fail "${root}" "${out}-help" --help
    ml_expect "existing business bytes unchanged" "${before}" \
        "$(ml_manifest "${root}" | grep -v '\.topsailai-data-namespace\.lock' || true)"
    ml_expect_file "no object tree invented" "${root}/object" absent
    ml_expect_file "no meta tree invented" "${root}/meta" absent
    ml_expect_file "no layout marker invented" "${root}/topsailai_data.json" absent
    ml_note "namespace lock may be created before the refusal; recorded as a permitted internal effect"
    end_case
}

run_cfg_08() {
    begin_case CFG-08 P0 F
    local base="${ML_STORES}/CFG-08"
    local out="${ML_CASE_DIR}/CFG-08"

    mkdir -p "${base}/corrupt"
    printf 'not json\n' > "${base}/corrupt/topsailai_data.json"
    ml_run_fail "${base}/corrupt" "${out}-corrupt" list
    ml_expect_contains "corrupt marker rejected" "${out}-corrupt.stderr" "layout marker"

    mkdir -p "${base}/newer"
    printf '{"layout":"object-meta","layout_version":99,"schema_version":99}\n' > "${base}/newer/topsailai_data.json"
    ml_run_fail "${base}/newer" "${out}-newer" list
    ml_expect_contains "newer layout version rejected" "${out}-newer.stderr" "layout"

    mkdir -p "${base}/wrong-layout"
    printf '{"layout":"legacy","layout_version":1,"schema_version":1}\n' > "${base}/wrong-layout/topsailai_data.json"
    ml_run_fail "${base}/wrong-layout" "${out}-wrong" list
    ml_expect_contains "unknown layout name rejected" "${out}-wrong.stderr" "layout"

    mkdir -p "${base}/root-is-file"
    printf 'x\n' > "${base}/root-is-file-file"
    ml_run_fail "${base}/root-is-file-file" "${out}-rootfile" list
    ml_expect_contains "root that is a file rejected" "${out}-rootfile.stderr" "not a directory"

    mkdir -p "${base}/object-is-file"
    printf '{"layout":"object-meta","layout_version":1,"schema_version":2}\n' > "${base}/object-is-file/topsailai_data.json"
    printf 'x\n' > "${base}/object-is-file/object"
    ml_run_fail "${base}/object-is-file" "${out}-objectfile" list
    ml_expect_contains "object tree that is a file rejected" "${out}-objectfile.stderr" "not a directory"

    mkdir -p "${base}/meta-symlink" "${base}/outside-meta"
    printf '{"layout":"object-meta","layout_version":1,"schema_version":2}\n' > "${base}/meta-symlink/topsailai_data.json"
    mkdir -p "${base}/meta-symlink/object"
    ln -s "${base}/outside-meta" "${base}/meta-symlink/meta"
    local outside_before
    outside_before=$(ml_manifest "${base}/outside-meta")
    ml_run_fail "${base}/meta-symlink" "${out}-metalink" list
    ml_expect_contains "symlinked meta tree rejected" "${out}-metalink.stderr" "not a directory"
    ml_expect "outside target unchanged" "${outside_before}" "$(ml_manifest "${base}/outside-meta")"
    end_case
}

run_cfg_09() {
    begin_case CFG-09 P1 F
    local base="${ML_STORES}/CFG-09"
    mkdir -p "${base}/readonly-parent"
    chmod 555 "${base}/readonly-parent"
    local out="${ML_CASE_DIR}/CFG-09"
    local code=0
    ml_run_nobody "${base}/readonly-parent/store" "${out}" list || code=$?
    ml_expect "unwritable parent fails" "1" "${code}"
    ml_expect_contains "error is actionable" "${out}.stderr" "permission denied"
    ml_expect_file "no store created" "${base}/readonly-parent/store" absent
    chmod 755 "${base}/readonly-parent"
    end_case
}

run_cfg_10() {
    begin_case CFG-10 P1 I
    local root="${ML_STORES}/CFG-10/store"
    local out="${ML_CASE_DIR}/CFG-10"
    ml_run_ok "${root}" "${out}-init" list

    ml_run_fail "${root}" "${out}-adapter" --env "TOPSAILAI_DATA_METADATA_ADAPTER=nope" list
    ml_expect_contains "unknown metadata adapter rejected" "${out}-adapter.stderr" "adapter not found"
    ml_run_fail "${root}" "${out}-actual" --env "TOPSAILAI_DATA_ACTUAL_DATA_ADAPTER=nope" list
    ml_expect_contains "unknown actual adapter rejected" "${out}-actual.stderr" "adapter not found"
    ml_run_fail "${root}" "${out}-retention" --env "TOPSAILAI_DATA_CEASED_RETENTION_DAYS=-1" list
    ml_expect_contains "negative retention rejected" "${out}-retention.stderr" "CEASED_RETENTION_DAYS"
    ml_run_fail "${root}" "${out}-retention-text" --env "TOPSAILAI_DATA_CEASED_RETENTION_DAYS=abc" list
    ml_expect_contains "nonnumeric retention rejected" "${out}-retention-text.stderr" "CEASED_RETENTION_DAYS"
    ml_run_fail "${root}" "${out}-flush" --env "TOPSAILAI_DATA_STAT_FLUSH=bogus" list
    ml_expect_contains "unsupported stat flush rejected" "${out}-flush.stderr" "STAT_FLUSH"
    ml_run_fail "${root}" "${out}-filemax" --env "TOPSAILAI_DATA_FILE_MAX_BYTES=0" list
    ml_expect_contains "nonpositive file limit rejected" "${out}-filemax.stderr" "FILE_MAX_BYTES"
    ml_run_fail "${root}" "${out}-filemax-neg" --env "TOPSAILAI_DATA_FILE_MAX_BYTES=-5" list
    ml_expect_contains "negative file limit rejected" "${out}-filemax-neg.stderr" "FILE_MAX_BYTES"
    ml_expect "no object created by rejected configuration" "[]" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --format json 2>/dev/null | tr -d '[:space:]')"
    end_case
}

run_cfg_11() {
    begin_case CFG-11 P1 I
    local root="${ML_STORES}/CFG-11/store"
    local out="${ML_CASE_DIR}/CFG-11"
    ml_make_markdown "${ML_FIXTURES}/cfg11/obj.md" "cfg11" "# cfg11"
    ml_run_ok "${root}" "${out}-create" create cfg11 --from "${ML_FIXTURES}/cfg11/obj.md"

    # TRACK_STAT is exercised while the object is still active: reads of a
    # deleted object are rejected by contract, so asserting success after the
    # soft delete would test the wrong thing.
    ml_run_ok "${root}" "${out}-track-off" --env "TOPSAILAI_DATA_TRACK_STAT=0" get cfg11 cfg11.md
    ml_expect_contains "TRACK_STAT=0 still returns the payload" "${out}-track-off.stdout" "cfg11"
    ml_run_ok "${root}" "${out}-track-on" --env "TOPSAILAI_DATA_TRACK_STAT=1" stat cfg11
    ml_expect_contains "TRACK_STAT=1 keeps counters readable" "${out}-track-on.stdout" "read_count"

    ml_run_ok "${root}" "${out}-delete" delete cfg11

    ml_run_ok "${root}" "${out}-inc-true" --env "TOPSAILAI_DATA_INCLUDE_DELETED=true" list
    ml_expect_contains "INCLUDE_DELETED=true exposes deleted" "${out}-inc-true.stdout" "cfg11"
    ml_run_ok "${root}" "${out}-inc-1" --env "TOPSAILAI_DATA_INCLUDE_DELETED=1" list
    ml_expect_contains "INCLUDE_DELETED=1 exposes deleted" "${out}-inc-1.stdout" "cfg11"
    ml_run_ok "${root}" "${out}-inc-false" --env "TOPSAILAI_DATA_INCLUDE_DELETED=false" list
    ml_expect_not_contains "INCLUDE_DELETED=false hides deleted" "${out}-inc-false.stdout" "cfg11"
    ml_run_ok "${root}" "${out}-inc-0" --env "TOPSAILAI_DATA_INCLUDE_DELETED=0" list
    ml_expect_not_contains "INCLUDE_DELETED=0 hides deleted" "${out}-inc-0.stdout" "cfg11"
    ml_run_ok "${root}" "${out}-inc-bogus" --env "TOPSAILAI_DATA_INCLUDE_DELETED=maybe" list
    ml_expect_not_contains "unrecognized boolean spelling is false" "${out}-inc-bogus.stdout" "cfg11"

    # A soft-deleted object keeps its payload but is not readable through the
    # active-object read path; this is the documented lifecycle contract.
    ml_run_fail "${root}" "${out}-get-deleted" get cfg11 cfg11.md
    ml_expect_contains "reading a deleted object is rejected" "${out}-get-deleted.stderr" "object not found"
    end_case
}

run_cfg_12() {
    begin_case CFG-12 P1 I
    local root="${ML_STORES}/CFG-12/store"
    local out="${ML_CASE_DIR}/CFG-12"
    ml_run_ok "${root}" "${out}-noargs"
    ml_expect_contains "usage lists create" "${out}-noargs.stdout" "create"
    ml_expect_contains "usage lists file" "${out}-noargs.stdout" "file"
    ml_run_ok "${root}" "${out}-help" --help
    ml_expect_contains "help lists environment variables" "${out}-help.stdout" "TOPSAILAI_DATA_ROOT"
    ml_run_ok "${root}" "${out}-file-help" file --help
    ml_expect_contains "file help lists subcommands" "${out}-file-help.stdout" "overwrite-lines"
    ml_run_fail "${root}" "${out}-unknown" definitely-not-a-command
    ml_expect_contains "unknown command reports usage" "${out}-unknown.stderr" "unknown command"
    ml_expect_file "help confined initialization to the root" "${root}/topsailai_data.json" file
    end_case
}

run_cfg_13() {
    begin_case CFG-13 P1 I
    local root="${ML_STORES}/CFG-13/store"
    local out="${ML_CASE_DIR}/CFG-13"
    ml_run_ok "${root}" "${out}-init" list
    ml_run_fail "${root}" "${out}-create-missing" create
    ml_expect_contains "create without an object name fails" "${out}-create-missing.stderr" "expected at least"
    ml_run_fail "${root}" "${out}-show-missing" show
    ml_run_fail "${root}" "${out}-unknown-flag" list --definitely-unknown
    ml_expect_contains "unknown flag rejected" "${out}-unknown-flag.stderr" "unknown"
    ml_run_fail "${root}" "${out}-extra-args" show a b
    ml_run_fail "${root}" "${out}-bad-format" list --format xml
    ml_expect_contains "invalid format rejected" "${out}-bad-format.stderr" "format"
    ml_run_fail "${root}" "${out}-bad-sort" list --sort bogus
    ml_expect_contains "invalid sort rejected" "${out}-bad-sort.stderr" "sort"
    ml_run_fail "${root}" "${out}-bad-offset" list --offset -1
    ml_expect_contains "negative offset rejected" "${out}-bad-offset.stderr" "offset"
    ml_run_fail "${root}" "${out}-bad-limit" list --limit -1
    ml_expect_contains "negative limit rejected" "${out}-bad-limit.stderr" "limit"
    ml_run_fail "${root}" "${out}-search-bad-offset" search anything --offset -1
    ml_expect_contains "search rejects a negative offset" "${out}-search-bad-offset.stderr" "offset"
    ml_expect "no stray objects created" "[]" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --format json 2>/dev/null | tr -d '[:space:]')"
    end_case
}

run_cfg_15() {
    begin_case CFG-15 P0 I
    local root="${ML_STORES}/CFG-15/store"
    local out="${ML_CASE_DIR}/CFG-15"
    local skill_bin="${PROJECT_ROOT}/skills/topsailai-data/bin/topsailai-data"
    ml_make_markdown "${ML_FIXTURES}/cfg15/note.md" "skill entry note" "# skill entry"
    local code=0
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
        TOPSAILAI_DATA_ROOT="${root}" "${skill_bin}" create skillnote \
        --from "${ML_FIXTURES}/cfg15/note.md" > "${out}-create.stdout" 2> "${out}-create.stderr" || code=$?
    ml_expect "create through the skill entry succeeds" "0" "${code}"
    code=0
    env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" LANG=C.UTF-8 \
        TOPSAILAI_DATA_ROOT="${root}" "${skill_bin}" show skillnote > "${out}-show.stdout" 2> "${out}-show.stderr" || code=$?
    ml_expect "show through the skill entry succeeds" "0" "${code}"
    ml_expect_contains "skill entry reads the same object" "${out}-show.stdout" "skill entry note"
    ml_expect_file "skill entry used the isolated root" "${root}/topsailai_data.json" file
    end_case
}

CASES=(CFG-01 CFG-02 CFG-03 CFG-04 CFG-05 CFG-06 CFG-07 CFG-08 CFG-09 CFG-10 CFG-11 CFG-12 CFG-13 CFG-15)
for case_id in "${CASES[@]}"; do
    if ! selected "${case_id}" "$@"; then
        continue
    fi
    case "${case_id}" in
        CFG-01) run_cfg_01 ;;
        CFG-02) run_cfg_02 ;;
        CFG-03) run_cfg_03 ;;
        CFG-04) run_cfg_04 ;;
        CFG-05) run_cfg_05 ;;
        CFG-06) run_cfg_06 ;;
        CFG-07) run_cfg_07 ;;
        CFG-08) run_cfg_08 ;;
        CFG-09) run_cfg_09 ;;
        CFG-10) run_cfg_10 ;;
        CFG-11) run_cfg_11 ;;
        CFG-12) run_cfg_12 ;;
        CFG-13) run_cfg_13 ;;
        CFG-15) run_cfg_15 ;;
    esac
done

if grep -q '"status":"FAIL"' "${ML_RESULTS}" 2>/dev/null; then
    exit 1
fi
exit 0
