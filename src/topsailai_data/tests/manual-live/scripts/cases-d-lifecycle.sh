#!/usr/bin/env bash
# cases-d-lifecycle: manual/live cases for the object lifecycle and recovery.
#
# Scope: LIFE-01..LIFE-08 from tests/manual-live/lifecycle-recovery.md.
# Every case runs against an isolated store under .tmp/manual-live/<run>/stores.
# No case reads or writes the live store.
#
# Usage:
#   ML_RUN_ID=<id> bash tests/manual-live/scripts/cases-d-lifecycle.sh [case ids...]

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

# json_ids prints the sorted ids of an include-deleted listing as one
# space-separated line with no trailing separator.
json_ids() {
    local root="$1"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --include-deleted --format json 2>/dev/null \
        | jq -r '.[].id' | sort | tr '\n' ' ' | sed 's/ $//'
}

# sha_of prints the sha256 of a file.
sha_of() {
    sha256sum "$1" | awk '{print $1}'
}

# status_of prints the status from an include-deleted listing. Creating objects
# are hidden from every listing, so this returns an empty string for them.
status_of() {
    json_field "$1" "$2" status
}

# status_of_show prints the status from the show output, which resolves every
# status including creating.
status_of_show() {
    local root="$1" id="$2"
    TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" show "${id}" 2>/dev/null \
        | awk '/^Status:/{print $2; exit}'
}

# payload_of prints the payload directory for a recorded object path.
payload_of() {
    printf '%s/object/%s' "$1" "$2"
}

# make_creating_fixture builds a tar whose symlink entry is rejected only after
# the creating metadata record is published. That is the only public path that
# leaves a real creating object behind, because create publishes metadata before
# it writes the payload.
make_creating_fixture() {
    local dir="$1" name="$2"
    mkdir -p "${dir}/tree"
    ml_make_markdown "${dir}/tree/${name}.md" "creating fixture"
    ln -sf /etc/passwd "${dir}/tree/evil"
    tar -cf "${dir}/${name}.tar" -C "${dir}/tree" . 2>/dev/null
}

# business_state prints the observable business state of a store: the sorted
# listing plus every payload digest. It is used to prove that a dry run or a
# rejected command changed nothing.
business_state() {
    local root="$1"
    {
        TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --include-deleted --format json 2>/dev/null \
            | jq -S 'sort_by(.id) | map({id,status,path,tags,description})'
        ml_manifest "${root}/object" 2>/dev/null || true
    }
}

# run_life_01 proves that a soft delete keeps the payload, tags and statistics
# while hiding the object from normal discovery.
run_life_01() {
    begin_case LIFE-01 P0 I
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-01"

    ml_make_markdown "${ML_FIXTURES}/d/life01.md" "lifecycle one"
    ml_run_ok "${root}" "${out}-create" create o1 --tag alpha,beta --from "${ML_FIXTURES}/d/life01.md"
    ml_run_ok "${root}" "${out}-create-ctrl" create ctrl --from "${ML_FIXTURES}/d/life01.md"

    local path meta payload
    path=$(json_field "${root}" o1 path)
    meta=$(ml_meta_dir "${root}" o1)
    payload=$(payload_of "${root}" "${path}")

    ml_run_ok "${root}" "${out}-read" get o1 o1.md
    local payload_sha tags_sha stat_sha
    payload_sha=$(sha_of "${payload}/o1.md")
    tags_sha=$(sha_of "${meta}/tags")
    stat_sha=$(sha_of "${meta}/stat.json")

    ml_run_ok "${root}" "${out}-delete" delete o1
    ml_expect_contains "delete reports the soft delete" "${out}-delete.stdout" "deleted object o1"

    ml_expect "the object becomes deleted" "deleted" "$(status_of "${root}" o1)"
    ml_expect "the payload is retained" "${payload_sha}" "$(sha_of "${payload}/o1.md")"
    ml_expect "the tags are retained" "${tags_sha}" "$(sha_of "${meta}/tags")"
    ml_expect "the statistics are retained" "${stat_sha}" "$(sha_of "${meta}/stat.json")"

    ml_run_ok "${root}" "${out}-list" list --format json
    ml_expect "normal list hides the deleted object" "ctrl" \
        "$(jq -r '.[].id' "${out}-list.stdout" | tr '\n' ' ' | sed 's/ $//')"
    ml_run_ok "${root}" "${out}-search" search o1 --format json
    ml_expect "normal search hides the deleted object" "0" "$(jq 'length' "${out}-search.stdout")"
    ml_run_ok "${root}" "${out}-list-inc" list --include-deleted --format json
    ml_expect "include-deleted exposes the deleted object" "ctrl o1" \
        "$(jq -r '.[].id' "${out}-list-inc.stdout" | sort | tr '\n' ' ' | sed 's/ $//')"
    ml_expect "the control object is untouched" "active" "$(status_of "${root}" ctrl)"
    end_case
}

# run_life_02 proves that recovery needs no source and preserves identity,
# content, tags and counters.
run_life_02() {
    begin_case LIFE-02 P0 I
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-02"

    ml_make_markdown "${ML_FIXTURES}/d/life02.md" "lifecycle two"
    ml_run_ok "${root}" "${out}-create" create o2 --tag keepme --from "${ML_FIXTURES}/d/life02.md"
    ml_run_ok "${root}" "${out}-read" get o2 o2.md

    local created_before tags_before content_before reads_before
    created_before=$(json_field "${root}" o2 created_at)
    tags_before=$(json_field "${root}" o2 tags | tr -d '\n ')
    content_before=$(sha_of "${ML_FIXTURES}/d/life02.md")
    reads_before=$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" stat o2 --format json 2>/dev/null | jq '.read_count')

    ml_run_ok "${root}" "${out}-delete" delete o2
    ml_run_ok "${root}" "${out}-recover" recover o2
    ml_expect_contains "recover reports the restore" "${out}-recover.stdout" "recovered object o2"

    ml_expect "recovery restores the active status" "active" "$(status_of "${root}" o2)"
    ml_expect "recovery preserves the creation time" "${created_before}" \
        "$(json_field "${root}" o2 created_at)"
    ml_expect "recovery preserves the tags" "${tags_before}" \
        "$(json_field "${root}" o2 tags | tr -d '\n ')"

    # Recovery itself must not count as a read, so the counter is unchanged
    # until the next real read happens.
    local reads_after_recover
    reads_after_recover=$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" stat o2 --format json 2>/dev/null | jq '.read_count')
    ml_expect "recovery preserves the read counter" "${reads_before}" "${reads_after_recover}"

    ml_run_ok "${root}" "${out}-read-after" get o2 o2.md
    ml_expect "recovery preserves the content" "${content_before}" "$(sha_of "${out}-read-after.stdout")"
    ml_expect "counters resume after recovery" "$((reads_after_recover + 1))" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" stat o2 --format json 2>/dev/null | jq '.read_count')"
    end_case
}

# run_life_03 proves that finalization removes the payload but keeps the ceased
# metadata, tags and lock until an explicit purge.
run_life_03() {
    begin_case LIFE-03 P0 I
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-03"

    ml_make_markdown "${ML_FIXTURES}/d/life03.md" "lifecycle three"
    ml_run_ok "${root}" "${out}-create" create o3 --tag ceasetag --from "${ML_FIXTURES}/d/life03.md"
    ml_run_ok "${root}" "${out}-create-ctrl" create ctrl --from "${ML_FIXTURES}/d/life03.md"

    local path meta payload
    path=$(json_field "${root}" o3 path)
    meta=$(ml_meta_dir "${root}" o3)
    payload=$(payload_of "${root}" "${path}")

    ml_run_ok "${root}" "${out}-delete1" delete o3
    ml_run_ok "${root}" "${out}-delete2" delete o3
    ml_expect_contains "the second delete finalizes the object" "${out}-delete2.stdout" "deleted object o3"

    ml_expect "finalization reaches the ceased status" "ceased" "$(status_of "${root}" o3)"
    ml_expect_file "finalization removes the payload directory" "${payload}" absent
    ml_expect_file "the ceased metadata record is retained" "${meta}/metadata.json" file
    ml_expect_file "the ceased tags are retained" "${meta}/tags" file
    ml_expect_file "the ceased lock is retained" "${meta}/lock" file
    ml_expect "the control object is untouched" "active" "$(status_of "${root}" ctrl)"
    ml_expect "the control payload survives" "true" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" file exists ctrl.md=ctrl.md --object ctrl --format json 2>/dev/null | jq -r '.["ctrl.md"]')"
    end_case
}

# run_life_04 expands the complete state-operation matrix. Every state is built
# through a public path, and every rejected operation must leave the state and
# the payload untouched.
run_life_04() {
    begin_case LIFE-04 P0 I
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-04"

    ml_make_markdown "${ML_FIXTURES}/d/life04.md" "lifecycle four"
    make_creating_fixture "${ML_FIXTURES}/d/cre" cre

    ml_run_ok "${root}" "${out}-create-act" create act --from "${ML_FIXTURES}/d/life04.md"
    ml_run_ok "${root}" "${out}-create-del" create del --from "${ML_FIXTURES}/d/life04.md"
    ml_run_ok "${root}" "${out}-create-cea" create cea --from "${ML_FIXTURES}/d/life04.md"
    ml_run_fail "${root}" "${out}-create-cre" create cre --from "${ML_FIXTURES}/d/cre/cre.tar"
    ml_run_ok "${root}" "${out}-delete-del" delete del
    ml_run_ok "${root}" "${out}-delete-cea1" delete cea
    ml_run_ok "${root}" "${out}-delete-cea2" delete cea

    ml_expect "the active fixture is active" "active" "$(status_of "${root}" act)"
    ml_expect "the deleted fixture is deleted" "deleted" "$(status_of "${root}" del)"
    ml_expect "the ceased fixture is ceased" "ceased" "$(status_of "${root}" cea)"
    ml_expect "the creating fixture is creating" "creating" "$(status_of_show "${root}" cre)"

    # Discovery: creating is hidden from every listing, deleted and ceased need
    # the include-deleted flag.
    ml_run_ok "${root}" "${out}-list" list --format json
    ml_expect "normal list shows only the active object" "act" \
        "$(jq -r '.[].id' "${out}-list.stdout" | tr '\n' ' ' | sed 's/ $//')"
    ml_run_ok "${root}" "${out}-list-inc" list --include-deleted --format json
    ml_expect "include-deleted adds deleted and ceased but not creating" "act cea del" \
        "$(jq -r '.[].id' "${out}-list-inc.stdout" | sort | tr '\n' ' ' | sed 's/ $//')"
    ml_run_ok "${root}" "${out}-search-cre" search cre --include-deleted --format json
    ml_expect "search never returns a creating object" "0" "$(jq 'length' "${out}-search-cre.stdout")"

    # show resolves every status, but only active objects expose actual data.
    local state
    for state in act del cea cre; do
        ml_run_ok "${root}" "${out}-show-${state}" show "${state}"
    done
    ml_expect_contains "show renders active markdown" "${out}-show-act.stdout" "--- Markdown ---"
    ml_expect_contains "show withholds deleted actual data" "${out}-show-del.stdout" \
        "--- Actual data unavailable for deleted object ---"
    ml_expect_contains "show withholds ceased actual data" "${out}-show-cea.stdout" \
        "--- Actual data unavailable for ceased object ---"
    ml_expect_not_contains "show does not render creating markdown" "${out}-show-cre.stdout" \
        "--- Markdown ---"

    # Actual reads: only active objects are readable.
    ml_run_ok "${root}" "${out}-get-act" get act act.md
    for state in del cea cre; do
        ml_run_fail "${root}" "${out}-get-${state}" get "${state}" "${state}.md"
        ml_expect_contains "get refuses the ${state} state" "${out}-get-${state}.stderr" "object not found"
        ml_run_fail "${root}" "${out}-archive-${state}" get-archive "${state}"
        ml_expect_contains "get-archive refuses the ${state} state" "${out}-archive-${state}.stderr" \
            "object not found"
        ml_run_fail "${root}" "${out}-fileread-${state}" file read "${state}.md" --object "${state}"
        ml_expect_contains "file read refuses the ${state} state" "${out}-fileread-${state}.stderr" \
            "object not found"
    done
    # file exists is a metadata probe: it answers false instead of failing.
    for state in del cea cre; do
        ml_run_ok "${root}" "${out}-exists-${state}" file exists "${state}.md=${state}.md" \
            --object "${state}" --format json
        ml_expect "file exists reports ${state} data as absent" "false" \
            "$(jq -r --arg k "${state}.md" '.[$k]' "${out}-exists-${state}.stdout")"
    done

    # Writes: only active objects accept them.
    for state in del cea cre; do
        ml_run_fail "${root}" "${out}-put-${state}" put "${state}" x.txt --from "${ML_FIXTURES}/d/life04.md"
        ml_expect_contains "put refuses the ${state} state" "${out}-put-${state}.stderr" "not active"
        ml_run_fail "${root}" "${out}-update-${state}" update "${state}" --description changed
        ml_expect_contains "update refuses the ${state} state" "${out}-update-${state}.stderr" "not active"
        ml_run_fail "${root}" "${out}-tag-${state}" tag add "${state}" newtag
        ml_expect_contains "tag refuses the ${state} state" "${out}-tag-${state}.stderr" "not active"
        ml_run_fail "${root}" "${out}-move-${state}" move "${state}" cls
        ml_expect_contains "move refuses the ${state} state" "${out}-move-${state}.stderr" "not active"
    done

    # Lifecycle transitions: only the documented source state is accepted.
    ml_run_fail "${root}" "${out}-delete-act-recover" recover act
    ml_expect_contains "recover refuses an active object" "${out}-delete-act-recover.stderr" \
        "already active"
    ml_run_fail "${root}" "${out}-delete-cre" delete cre
    ml_expect_contains "delete refuses a creating object" "${out}-delete-cre.stderr" "creating"
    ml_run_fail "${root}" "${out}-recover-cre" recover cre
    ml_expect_contains "recover refuses a creating object" "${out}-recover-cre.stderr" "still being created"
    ml_run_fail "${root}" "${out}-recover-cea" recover cea
    ml_expect_contains "recover refuses a ceased object" "${out}-recover-cea.stderr" "has ceased"
    ml_run_fail "${root}" "${out}-delete-cea" delete cea
    ml_expect_contains "delete refuses an already ceased object" "${out}-delete-cea.stderr" "already ceased"

    # Every rejection above must have preserved the state and the payload.
    ml_expect "the active state survived the rejections" "active" "$(status_of "${root}" act)"
    ml_expect "the deleted state survived the rejections" "deleted" "$(status_of "${root}" del)"
    ml_expect "the ceased state survived the rejections" "ceased" "$(status_of "${root}" cea)"
    ml_expect "the creating state survived the rejections" "creating" "$(status_of_show "${root}" cre)"
    ml_run_ok "${root}" "${out}-get-act-final" get act act.md
    ml_expect "the active payload survived the rejections" \
        "$(sha_of "${ML_FIXTURES}/d/life04.md")" "$(sha_of "${out}-get-act-final.stdout")"
    end_case
}

# run_life_05 proves that a default GC dry run mutates nothing and that the real
# run removes creating objects, finalizes deleted objects and removes expired
# ceased objects.
run_life_05() {
    begin_case LIFE-05 P0 F
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-05"

    ml_make_markdown "${ML_FIXTURES}/d/life05.md" "lifecycle five"
    make_creating_fixture "${ML_FIXTURES}/d/cre5" cre5

    ml_run_ok "${root}" "${out}-create-act" create act --from "${ML_FIXTURES}/d/life05.md"
    ml_run_ok "${root}" "${out}-create-del" create del --from "${ML_FIXTURES}/d/life05.md"
    ml_run_ok "${root}" "${out}-create-cea" create cea --from "${ML_FIXTURES}/d/life05.md"
    ml_run_fail "${root}" "${out}-create-cre" create cre5 --from "${ML_FIXTURES}/d/cre5/cre5.tar"
    ml_run_ok "${root}" "${out}-delete-del" delete del
    ml_run_ok "${root}" "${out}-delete-cea1" delete cea
    ml_run_ok "${root}" "${out}-delete-cea2" delete cea

    business_state "${root}" > "${out}-state-before.txt"
    ml_run_ok "${root}" "${out}-dry" gc --dry-run
    ml_expect_contains "the dry run announces creating cleanup" "${out}-dry.stdout" \
        "would clean up creating object cre5"
    business_state "${root}" > "${out}-state-after-dry.txt"
    ml_expect "the dry run mutates nothing" "identical" \
        "$(cmp -s "${out}-state-before.txt" "${out}-state-after-dry.txt" && echo identical || echo different)"

    # The default run removes the creating remnant, finalizes the deleted object
    # and keeps the freshly ceased object inside the default retention window.
    # DESIGN.md 12.7 describes the default sweep as creating plus ceased only, so
    # the deleted finalization observed here is recorded as a documentation
    # deviation rather than silently accepted.
    ml_run_ok "${root}" "${out}-gc" gc
    ml_expect_contains "the default GC finalizes the deleted object" "${out}-gc.stdout" \
        "finalized deleted object del"
    ml_note "DESIGN.md 12.7 says the default GC scans creating and ceased only, but the observed default run also finalizes deleted objects; the assertion follows the observed behaviour"
    ml_expect "the default GC removes the creating object" "act cea del" "$(json_ids "${root}")"
    ml_expect "the default GC keeps the freshly ceased object" "ceased" "$(status_of "${root}" cea)"
    ml_expect "the default GC finalizes the deleted object to ceased" "ceased" "$(status_of "${root}" del)"
    ml_expect "the default GC keeps the active object" "active" "$(status_of "${root}" act)"

    # A zero retention window is the fixed oracle for an expired ceased object.
    ml_run_ok "${root}" "${out}-gc-expired" --env TOPSAILAI_DATA_CEASED_RETENTION_DAYS=0 gc
    ml_expect "an expired ceased object is removed" "act" "$(json_ids "${root}")"
    ml_expect "the active object survives every GC run" "active" "$(status_of "${root}" act)"
    end_case
}

# run_life_06 proves that a targeted GC touches only the selected state.
run_life_06() {
    begin_case LIFE-06 P0 I
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-06"

    ml_make_markdown "${ML_FIXTURES}/d/life06.md" "lifecycle six"
    make_creating_fixture "${ML_FIXTURES}/d/cre6" cre6

    ml_run_ok "${root}" "${out}-create-act" create act --from "${ML_FIXTURES}/d/life06.md"
    ml_run_ok "${root}" "${out}-create-del" create del --from "${ML_FIXTURES}/d/life06.md"
    ml_run_ok "${root}" "${out}-create-cea" create cea --from "${ML_FIXTURES}/d/life06.md"
    ml_run_fail "${root}" "${out}-create-cre" create cre6 --from "${ML_FIXTURES}/d/cre6/cre6.tar"
    ml_run_ok "${root}" "${out}-delete-del" delete del
    ml_run_ok "${root}" "${out}-delete-cea1" delete cea
    ml_run_ok "${root}" "${out}-delete-cea2" delete cea

    ml_run_ok "${root}" "${out}-gc-creating" gc --status creating
    ml_expect_contains "the creating sweep reports the object" "${out}-gc-creating.stdout" \
        "cleaned up creating object cre6"
    ml_expect "the creating sweep leaves the other states alone" "act cea del" "$(json_ids "${root}")"
    ml_expect "the creating sweep keeps the deleted object" "deleted" "$(status_of "${root}" del)"
    ml_expect "the creating sweep keeps the ceased object" "ceased" "$(status_of "${root}" cea)"

    ml_run_ok "${root}" "${out}-gc-deleted" gc --status deleted
    ml_expect_contains "the deleted sweep finalizes the object" "${out}-gc-deleted.stdout" \
        "finalized deleted object del"
    ml_expect "finalization moves the object to ceased" "ceased" "$(status_of "${root}" del)"
    ml_expect "finalization keeps the ceased metadata" "act cea del" "$(json_ids "${root}")"

    # An explicit ceased sweep ignores the retention window entirely.
    ml_run_ok "${root}" "${out}-gc-ceased" --env TOPSAILAI_DATA_CEASED_RETENTION_DAYS=30 gc --status ceased
    ml_expect "the explicit ceased sweep ignores retention" "act" "$(json_ids "${root}")"
    ml_expect "the active control survives every targeted sweep" "active" "$(status_of "${root}" act)"
    end_case
}

# run_life_07 pins the retention contract against a fixed oracle instead of
# waiting for real days or moving the system clock.
run_life_07() {
    begin_case LIFE-07 P1 F
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-07"

    ml_make_markdown "${ML_FIXTURES}/d/life07.md" "lifecycle seven"
    ml_run_ok "${root}" "${out}-create" create cea --from "${ML_FIXTURES}/d/life07.md"
    ml_run_ok "${root}" "${out}-delete1" delete cea
    ml_run_ok "${root}" "${out}-delete2" delete cea
    ml_expect "the retention fixture is ceased" "ceased" "$(status_of "${root}" cea)"

    # A freshly ceased object is inside every positive window.
    local days
    for days in 1 30; do
        ml_run_ok "${root}" "${out}-gc-${days}" --env "TOPSAILAI_DATA_CEASED_RETENTION_DAYS=${days}" gc
        ml_expect "retention ${days} keeps a fresh ceased object" "cea" "$(json_ids "${root}")"
    done

    # Zero days is the boundary that makes the object immediately expired.
    ml_run_ok "${root}" "${out}-gc-0" --env TOPSAILAI_DATA_CEASED_RETENTION_DAYS=0 gc
    ml_expect "retention 0 removes the ceased object" "" "$(json_ids "${root}")"
    ml_expect_file "retention 0 purges the metadata record" "$(ml_meta_dir "${root}" cea)" absent
    end_case
}

# run_life_08 proves that invalid options and unknown ids fail clearly and never
# sweep unrelated objects.
run_life_08() {
    begin_case LIFE-08 P1 I
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-08"

    ml_make_markdown "${ML_FIXTURES}/d/life08.md" "lifecycle eight"
    ml_run_ok "${root}" "${out}-create" create act --from "${ML_FIXTURES}/d/life08.md"
    ml_run_ok "${root}" "${out}-create-del" create del --from "${ML_FIXTURES}/d/life08.md"
    ml_run_ok "${root}" "${out}-delete" delete del

    business_state "${root}" > "${out}-state-before.txt"

    ml_run_fail "${root}" "${out}-gc-bogus" gc --status bogus
    ml_expect_contains "an invalid status is rejected" "${out}-gc-bogus.stderr" 'invalid status "bogus"'
    ml_run_fail "${root}" "${out}-retention-negative" --env TOPSAILAI_DATA_CEASED_RETENTION_DAYS=-1 gc
    ml_expect_contains "a negative retention is rejected" "${out}-retention-negative.stderr" \
        "must be non-negative"
    ml_expect_not_contains "a negative retention has no nil wrap verb" "${out}-retention-negative.stderr" "%!"
    ml_run_fail "${root}" "${out}-retention-text" --env TOPSAILAI_DATA_CEASED_RETENTION_DAYS=abc gc
    ml_expect_contains "a non-numeric retention is rejected" "${out}-retention-text.stderr" \
        "CEASED_RETENTION_DAYS"
    ml_run_fail "${root}" "${out}-delete-unknown" delete nope
    ml_expect_contains "deleting an unknown id is rejected" "${out}-delete-unknown.stderr" "object not found"
    ml_run_fail "${root}" "${out}-recover-unknown" recover nope
    ml_expect_contains "recovering an unknown id is rejected" "${out}-recover-unknown.stderr" \
        "object not found"

    business_state "${root}" > "${out}-state-after.txt"
    ml_expect "no rejected command swept the store" "identical" \
        "$(cmp -s "${out}-state-before.txt" "${out}-state-after.txt" && echo identical || echo different)"
    ml_expect "the active control is intact" "active" "$(status_of "${root}" act)"
    ml_expect "the deleted control is intact" "deleted" "$(status_of "${root}" del)"
    end_case
}

CASES=(LIFE-01 LIFE-02 LIFE-03 LIFE-04 LIFE-05 LIFE-06 LIFE-07 LIFE-08)
for case_id in "${CASES[@]}"; do
    if ! selected "${case_id}" "$@"; then
        continue
    fi
    case "${case_id}" in
        LIFE-01) run_life_01 ;;
        LIFE-02) run_life_02 ;;
        LIFE-03) run_life_03 ;;
        LIFE-04) run_life_04 ;;
        LIFE-05) run_life_05 ;;
        LIFE-06) run_life_06 ;;
        LIFE-07) run_life_07 ;;
        LIFE-08) run_life_08 ;;
    esac
done

if grep -q '"status":"FAIL"' "${ML_RESULTS}" 2>/dev/null; then
    exit 1
fi
exit 0
