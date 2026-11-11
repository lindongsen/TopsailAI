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

# payload_dir_any prints the payload directory for any status, including deleted
# and ceased objects. ml_payload_dir only resolves active objects because it
# reads a plain listing.
payload_dir_any() {
    local root="$1" id="$2"
    local path
    path=$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" list --include-deleted --format json 2>/dev/null \
        | jq -r --arg id "${id}" '.[] | select(.id==$id) | .path' 2>/dev/null || true)
    if [[ -z "${path}" || "${path}" == "null" ]]; then
        return 1
    fi
    printf '%s/object/%s' "${root}" "${path}"
}

# RECOVERY_DIR is the preserved, verified recovery artifact set. It is a backup:
# every case that reads it must prove it did not modify it.
RECOVERY_DIR="${PROJECT_ROOT}/.tmp/data-recovery/20261111125501"

# recovery_available reports whether the verified recovery artifacts exist.
recovery_available() {
    [[ -d "${RECOVERY_DIR}/original" && -d "${RECOVERY_DIR}/staged" \
        && -f "${RECOVERY_DIR}/original-manifest.json" ]]
}

# run_life_09 proves that a write failure after the creating record is published
# leaves an invisible but resolvable incomplete record that a scoped GC removes.
run_life_09() {
    begin_case LIFE-09 P0 F
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-09"

    ml_make_markdown "${ML_FIXTURES}/d/life09.md" "lifecycle nine"
    make_creating_fixture "${ML_FIXTURES}/d/cre9" cre9

    ml_run_ok "${root}" "${out}-create-act" create act --from "${ML_FIXTURES}/d/life09.md"
    ml_run_fail "${root}" "${out}-create-cre" create cre9 --from "${ML_FIXTURES}/d/cre9/cre9.tar"
    ml_expect_contains "the write failure is reported" "${out}-create-cre.stderr" \
        "unsupported tar entry type"

    # The incomplete record is invisible to discovery but resolvable by show.
    ml_expect "the incomplete record is hidden from list" "act" "$(json_ids "${root}")"
    ml_expect "the incomplete record is hidden from search" "0" \
        "$(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" search cre9 --format json 2>/dev/null | jq 'length')"
    ml_expect "the incomplete record is visible to show" "creating" "$(status_of_show "${root}" cre9)"

    # Both the published record and the partial payload are retained.
    local meta
    meta=$(ml_meta_dir "${root}" cre9)
    ml_expect_file "the creating record is published" "${meta}/metadata.json" file
    ml_expect_file "the creating tags file is published" "${meta}/tags" file
    ml_expect "the partial payload boundary is retained" "1" \
        "$(find "${root}/object" -name 'cre9.md' -type f | wc -l)"

    ml_run_ok "${root}" "${out}-dry" gc --dry-run
    ml_expect_contains "the dry run announces the incomplete record" "${out}-dry.stdout" \
        "would clean up creating object cre9"
    ml_run_ok "${root}" "${out}-gc" gc
    # The default GC reports cleanup detail on stderr and only prints a summary
    # line on stdout, so the purge evidence has to be read from stderr.
    ml_expect_contains "the scoped GC purges the incomplete metadata" "${out}-gc.stderr" \
        "purged object metadata directory"
    ml_expect_contains "the purge names the incomplete record" "${out}-gc.stderr" "id=cre9"
    ml_expect_file "the incomplete metadata is removed" "${meta}" absent
    ml_expect "the active control survives" "active" "$(status_of "${root}" act)"
    ml_expect "the active control is still listed" "act" "$(json_ids "${root}")"
    end_case
}

# run_life_10 proves that a failure before the creating record is published leaves
# no discoverable object and no payload, and that the recordless remnant is not
# misrepresented as a normal GC candidate.
run_life_10() {
    begin_case LIFE-10 P0 F
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-10"

    ml_make_markdown "${ML_FIXTURES}/d/life10.md" "lifecycle ten"
    ml_run_ok "${root}" "${out}-init" list
    ml_chown_nobody "${root}"
    chmod 0555 "${root}/object"

    local code=0
    ml_run_nobody "${root}" "${out}-create" -- create rec --from "${ML_FIXTURES}/d/life10.md" || code=$?
    chmod 0755 "${root}/object"
    ml_expect "the pre-publication failure is reported" "1" "${code}"
    ml_expect_contains "the failure happens before record publication" "${out}-create.stderr" \
        "create payload boundary directory"

    ml_expect "no object is discoverable" "" "$(json_ids "${root}")"
    ml_run_fail "${root}" "${out}-show" show rec
    ml_expect_contains "the recordless remnant is not a normal object" "${out}-show.stderr" \
        "object not found"
    ml_expect "no payload file was written" "0" "$(find "${root}/object" -type f | wc -l)"

    local meta
    meta=$(ml_meta_dir "${root}" rec)
    ml_expect_file "the recordless lock remnant is preserved as evidence" "${meta}/lock" file
    ml_expect_file "no metadata record was published" "${meta}/metadata.json" absent

    ml_run_ok "${root}" "${out}-dry" gc --dry-run
    ml_expect_not_contains "the dry run does not misrepresent the remnant" "${out}-dry.stdout" "rec"
    ml_note "the recordless lock directory under meta/ is not removed by gc; it is preserved as reconciliation evidence"
    end_case
}

# run_life_11 proves that a payload removal fault is surfaced, keeps the object
# retryable, and that the retry finalizes it without a false success.
run_life_11() {
    begin_case LIFE-11 P0 F
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-11"

    ml_make_markdown "${ML_FIXTURES}/d/life11.md" "lifecycle eleven"
    ml_run_ok "${root}" "${out}-create" create del --from "${ML_FIXTURES}/d/life11.md"
    ml_run_ok "${root}" "${out}-delete" delete del

    local payload parent
    payload=$(payload_dir_any "${root}" del)
    parent=$(dirname "${payload}")
    ml_chown_nobody "${root}"
    chmod 0555 "${parent}"

    local code=0
    ml_run_nobody "${root}" "${out}-finalize-fault" -- delete del || code=$?
    ml_expect "the payload removal fault is reported" "1" "${code}"
    ml_expect_contains "the fault names the payload removal" "${out}-finalize-fault.stderr" \
        "delete actual data"
    ml_expect "the object stays deleted after the fault" "deleted" "$(status_of "${root}" del)"
    ml_expect_file "the payload survives the fault" "${payload}" dir

    chmod 0755 "${parent}"
    ml_run_ok "${root}" "${out}-retry" delete del
    ml_expect "the retry finalizes the object" "ceased" "$(status_of "${root}" del)"
    ml_expect_file "the payload is removed by the retry" "${payload}" absent
    ml_expect_file "the ceased record is retained" "$(ml_meta_dir "${root}" del)/metadata.json" file
    end_case
}

# run_life_12 proves that a deleted object with a missing payload refuses recovery
# without a source, accepts a valid archive, and rejects an invalid one without
# activating the object.
run_life_12() {
    begin_case LIFE-12 P1 F
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-12"

    ml_make_markdown "${ML_FIXTURES}/d/life12.md" "lifecycle twelve"
    ml_run_ok "${root}" "${out}-create" create del --from "${ML_FIXTURES}/d/life12.md"
    ml_run_ok "${root}" "${out}-delete" delete del

    local payload
    payload=$(payload_dir_any "${root}" del)
    rm -rf "${payload}"

    ml_run_fail "${root}" "${out}-recover-nosource" recover del
    ml_expect_contains "a missing payload refuses recovery without a source" \
        "${out}-recover-nosource.stderr" "provide --from to restore"
    ml_expect "the object stays deleted after the refusal" "deleted" "$(status_of "${root}" del)"

    mkdir -p "${ML_FIXTURES}/d/life12-arc"
    ml_make_markdown "${ML_FIXTURES}/d/life12-arc/del.md" "restored twelve"
    tar -cf "${ML_FIXTURES}/d/life12-ok.tar" -C "${ML_FIXTURES}/d/life12-arc" .
    ml_run_ok "${root}" "${out}-recover-ok" recover del --from "${ML_FIXTURES}/d/life12-ok.tar"
    ml_expect "a valid archive restores the object" "active" "$(status_of "${root}" del)"
    ml_run_ok "${root}" "${out}-get" get del del.md
    ml_expect_contains "the restored content is the archive content" "${out}-get.stdout" \
        "restored twelve"

    ml_run_ok "${root}" "${out}-delete2" delete del
    printf 'not a tar archive' > "${ML_FIXTURES}/d/life12-bad.tar"
    ml_run_fail "${root}" "${out}-recover-bad" recover del --from "${ML_FIXTURES}/d/life12-bad.tar"
    ml_expect_contains "an invalid archive is rejected" "${out}-recover-bad.stderr" "tar"
    ml_expect "an invalid archive does not activate the object" "deleted" "$(status_of "${root}" del)"
    end_case
}

# run_life_13 proves that recovery refuses every non-deleted state and preserves
# the source and the record.
run_life_13() {
    begin_case LIFE-13 P1 I
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-13"

    ml_make_markdown "${ML_FIXTURES}/d/life13.md" "lifecycle thirteen"
    make_creating_fixture "${ML_FIXTURES}/d/cre13" cre13

    ml_run_ok "${root}" "${out}-create-act" create act --from "${ML_FIXTURES}/d/life13.md"
    ml_run_ok "${root}" "${out}-create-cea" create cea --from "${ML_FIXTURES}/d/life13.md"
    ml_run_ok "${root}" "${out}-delete-cea1" delete cea
    ml_run_ok "${root}" "${out}-delete-cea2" delete cea
    ml_run_fail "${root}" "${out}-create-cre" create cre13 --from "${ML_FIXTURES}/d/cre13/cre13.tar"

    business_state "${root}" > "${out}-state-before.txt"

    ml_run_fail "${root}" "${out}-recover-active" recover act
    ml_expect_contains "recovering an active object is refused" "${out}-recover-active.stderr" \
        "already active"
    ml_run_fail "${root}" "${out}-recover-ceased" recover cea
    ml_expect_contains "recovering a ceased object is refused" "${out}-recover-ceased.stderr" "ceased"
    ml_run_fail "${root}" "${out}-recover-creating" recover cre13
    ml_expect_contains "recovering a creating object is refused" "${out}-recover-creating.stderr" \
        "creating"

    business_state "${root}" > "${out}-state-after.txt"
    ml_expect "no refused recovery changed the store" "identical" \
        "$(cmp -s "${out}-state-before.txt" "${out}-state-after.txt" && echo identical || echo different)"
    ml_expect "the active control is intact" "active" "$(status_of "${root}" act)"
    ml_expect "the ceased control is intact" "ceased" "$(status_of "${root}" cea)"
    ml_expect "the creating control is intact" "creating" "$(status_of_show "${root}" cre13)"
    end_case
}

# run_life_14 proves that the new CLI refuses an unmarked legacy store, claims no
# automatic migration, and leaves both the clone and the preserved backup intact.
run_life_14() {
    begin_case LIFE-14 P0 C
    local out
    out="${ML_ARTIFACTS}/LIFE-14"
    if ! recovery_available; then
        ml_blocked "verified recovery artifacts are unavailable"
        end_case
        return
    fi

    local root
    root="${ML_STORES}/${ML_CASE_ID}/legacy"
    mkdir -p "${root}"
    cp -a "${RECOVERY_DIR}/original/." "${root}/"

    ml_manifest "${RECOVERY_DIR}/original" > "${out}-backup-before.txt"
    ml_manifest "${root}" > "${out}-clone-before.txt"

    ml_run_fail "${root}" "${out}-list" list
    ml_expect_contains "the unmarked legacy store is refused" "${out}-list.stderr" \
        "migration is unsupported"
    ml_expect_contains "the refusal names the fresh-root requirement" "${out}-list.stderr" \
        "fresh root"

    ml_manifest "${root}" > "${out}-clone-after.txt"
    ml_expect "the refused invocation left the clone untouched" "identical" \
        "$(cmp -s "${out}-clone-before.txt" "${out}-clone-after.txt" && echo identical || echo different)"
    ml_manifest "${RECOVERY_DIR}/original" > "${out}-backup-after.txt"
    ml_expect "the preserved backup was not modified" "identical" \
        "$(cmp -s "${out}-backup-before.txt" "${out}-backup-after.txt" && echo identical || echo different)"
    ml_note "no automatic migration is attempted; conversion is rehearsed separately on a copy in LIFE-15"
    end_case
}

# run_life_15 proves that the converted copy carries current Hash records and
# relative references while preserving payloads, tags, descriptions, statuses and
# statistics, without touching the conversion source.
run_life_15() {
    begin_case LIFE-15 P0 C
    local out
    out="${ML_ARTIFACTS}/LIFE-15"
    if ! recovery_available; then
        ml_blocked "verified recovery artifacts are unavailable"
        end_case
        return
    fi

    local root
    root="${ML_STORES}/${ML_CASE_ID}/converted"
    mkdir -p "${root}"
    cp -a "${RECOVERY_DIR}/staged/." "${root}/"

    ml_manifest "${RECOVERY_DIR}/staged" > "${out}-source-before.txt"

    ml_run_ok "${root}" "${out}-list" list --format json
    ml_expect "every active object is preserved" "109" "$(jq 'length' "${out}-list.stdout")"
    ml_run_ok "${root}" "${out}-list-all" list --include-deleted --format json
    ml_expect "every lifecycle record is preserved" "121" "$(jq 'length' "${out}-list-all.stdout")"
    ml_expect "the active count is preserved" "109" \
        "$(jq '[.[]|select(.status=="active")]|length' "${out}-list-all.stdout")"
    ml_expect "the ceased count is preserved" "11" \
        "$(jq '[.[]|select(.status=="ceased")]|length' "${out}-list-all.stdout")"
    ml_expect "the deleted count is preserved" "1" \
        "$(jq '[.[]|select(.status=="deleted")]|length' "${out}-list-all.stdout")"
    ml_expect "every record uses the current schema version" "0" \
        "$(jq '[.[]|select(.schema_version!=2)]|length' "${out}-list-all.stdout")"
    ml_expect "every data reference is relative" "0" \
        "$(jq '[.[]|select(.data_ref|startswith("/"))]|length' "${out}-list-all.stdout")"
    # The conversion source itself carries 16 empty descriptions, so the correct
    # invariant is that descriptions are preserved verbatim, not that all of them
    # are non-empty.
    ml_expect "every description is preserved verbatim" \
        "$(jq '[.[]|select(.description=="")]|length' "${RECOVERY_DIR}/stage-list.json")" \
        "$(jq '[.[]|select(.description=="")]|length' "${out}-list-all.stdout")"
    ml_expect "a known object keeps its tags" "shell,bash,cli,argument-forwarding" \
        "$(jq -r '.[]|select(.id=="note--shell-wrapper-argument-quoting")|.tags|join(",")' "${out}-list-all.stdout")"

    ml_run_ok "${root}" "${out}-stat" stat note--shell-wrapper-argument-quoting
    ml_expect_contains "the preserved statistics survive the conversion" "${out}-stat.stdout" \
        "write_count: 1"

    # The payload tree must be byte-identical to the preserved original.
    ( cd "${RECOVERY_DIR}/original" && find object -type f -print0 | sort -z | xargs -0 -r sha256sum ) \
        > "${out}-payload-original.txt"
    ( cd "${root}" && find object -type f -print0 | sort -z | xargs -0 -r sha256sum ) \
        > "${out}-payload-converted.txt"
    ml_expect "no payload file was rewritten" "identical" \
        "$(cmp -s "${out}-payload-original.txt" "${out}-payload-converted.txt" && echo identical || echo different)"

    ml_manifest "${RECOVERY_DIR}/staged" > "${out}-source-after.txt"
    ml_expect "the conversion source was not modified" "identical" \
        "$(cmp -s "${out}-source-before.txt" "${out}-source-after.txt" && echo identical || echo different)"
    end_case
}

# run_life_16 verifies the preserved backup against its recorded manifest and
# rehearses a restore on a separate copy read through the CLI.
run_life_16() {
    begin_case LIFE-16 P0 C
    local out
    out="${ML_ARTIFACTS}/LIFE-16"
    if ! recovery_available; then
        ml_blocked "verified recovery artifacts are unavailable"
        end_case
        return
    fi

    local total=0 missing=0 mismatches=0 path expected actual
    while IFS=$'\t' read -r path expected; do
        total=$((total + 1))
        if [[ ! -f "${RECOVERY_DIR}/original/${path}" ]]; then
            missing=$((missing + 1))
            continue
        fi
        actual=$(sha256sum "${RECOVERY_DIR}/original/${path}" | awk '{print $1}')
        if [[ "${actual}" != "${expected}" ]]; then
            mismatches=$((mismatches + 1))
        fi
    done < <(jq -r 'to_entries[] | "\(.key)\t\(.value)"' "${RECOVERY_DIR}/original-manifest.json")
    ml_expect "the backup manifest covers every recorded file" "782" "${total}"
    ml_expect "no recorded backup file is missing" "0" "${missing}"
    ml_expect "every recorded backup file matches its digest" "0" "${mismatches}"

    local root
    root="${ML_STORES}/${ML_CASE_ID}/restored"
    mkdir -p "${root}"
    cp -a "${RECOVERY_DIR}/staged/." "${root}/"
    ml_run_ok "${root}" "${out}-list" list --format json
    ml_expect "the restored copy exposes every active object" "109" "$(jq 'length' "${out}-list.stdout")"
    ml_run_ok "${root}" "${out}-list-all" list --include-deleted --format json
    ml_expect "the restored copy keeps every lifecycle record" "121" \
        "$(jq 'length' "${out}-list-all.stdout")"

    # tar -tf prints directory entries without a trailing slash, so the listing
    # has to be filtered by the tar type flag instead of by a trailing slash.
    local id file failed=0 checked=0
    while IFS= read -r id; do
        while IFS= read -r file; do
            checked=$((checked + 1))
            if ! TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" get "${id}" "${file}" > /dev/null 2>&1; then
                failed=$((failed + 1))
            fi
        done < <(TOPSAILAI_DATA_ROOT="${root}" "${ML_BIN}" get-archive "${id}" 2>/dev/null \
            | tar -tvf - 2>/dev/null | awk '$1 !~ /^d/ {print $NF}' \
            | sed 's|^\./||' | grep -v "^${id}\.md$" || true)
    done < <(jq -r '.[]|select(.status=="active")|.id' "${out}-list-all.stdout")
    ml_expect "no accessible payload file fails to read" "0" "${failed}"
    ml_note "checked ${checked} payload files through get"
    end_case
}

# run_life_17 proves that a purged ceased identity is unavailable everywhere and
# that a fresh create reuses the id without stale lock or statistic leakage.
run_life_17() {
    begin_case LIFE-17 P1 I
    local root out
    root=$(ml_case_root store)
    out="${ML_ARTIFACTS}/LIFE-17"

    ml_make_markdown "${ML_FIXTURES}/d/life17.md" "lifecycle seventeen"
    ml_run_ok "${root}" "${out}-create" create gone --from "${ML_FIXTURES}/d/life17.md"
    ml_run_ok "${root}" "${out}-get" get gone gone.md
    ml_run_ok "${root}" "${out}-delete1" delete gone
    ml_run_ok "${root}" "${out}-delete2" delete gone
    ml_expect "the object is ceased before the purge" "ceased" "$(status_of "${root}" gone)"

    ml_run_ok "${root}" "${out}-purge" gc --status ceased
    ml_expect "the purged identity is gone from every listing" "" "$(json_ids "${root}")"
    ml_run_fail "${root}" "${out}-show" show gone
    ml_expect_contains "the purged identity is not resolvable" "${out}-show.stderr" "object not found"
    ml_run_fail "${root}" "${out}-get-after" get gone gone.md
    ml_run_fail "${root}" "${out}-stat-after" stat gone

    ml_run_ok "${root}" "${out}-recreate" create gone --from "${ML_FIXTURES}/d/life17.md"
    ml_expect "a fresh create reuses the purged id" "active" "$(status_of "${root}" gone)"
    ml_run_ok "${root}" "${out}-stat-fresh" stat gone
    ml_expect_contains "the fresh object starts with a clean write counter" \
        "${out}-stat-fresh.stdout" "write_count: 1"
    ml_expect_contains "the fresh object has no inherited read counter" \
        "${out}-stat-fresh.stdout" "read_count: 0"
    ml_run_ok "${root}" "${out}-get-fresh" get gone gone.md
    ml_expect_contains "the fresh object serves its own content" "${out}-get-fresh.stdout" \
        "lifecycle seventeen"
    end_case
}

CASES=(LIFE-01 LIFE-02 LIFE-03 LIFE-04 LIFE-05 LIFE-06 LIFE-07 LIFE-08
    LIFE-09 LIFE-10 LIFE-11 LIFE-12 LIFE-13 LIFE-14 LIFE-15 LIFE-16 LIFE-17)
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
        LIFE-09) run_life_09 ;;
        LIFE-10) run_life_10 ;;
        LIFE-11) run_life_11 ;;
        LIFE-12) run_life_12 ;;
        LIFE-13) run_life_13 ;;
        LIFE-14) run_life_14 ;;
        LIFE-15) run_life_15 ;;
        LIFE-16) run_life_16 ;;
        LIFE-17) run_life_17 ;;
    esac
done

if grep -q '"status":"FAIL"' "${ML_RESULTS}" 2>/dev/null; then
    exit 1
fi
exit 0
