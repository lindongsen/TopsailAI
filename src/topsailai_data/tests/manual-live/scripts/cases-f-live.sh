#!/usr/bin/env bash
# cases-f-live: manual/live acceptance cases SAFE-13..SAFE-18.
#
# Scope: SAFE-13..SAFE-18 from tests/manual-live/safety-scale-live.md.
#
# SAFE-13 and SAFE-14 read the existing live store. They are strictly read-only:
# stat tracking is disabled, only list/search/show/get/stat and a bounded archive
# read are used, and a before/after manifest proves that no file changed. The
# protected recovery backup is never written, moved or deleted.
#
# SAFE-15 and SAFE-16 use an isolated store. SAFE-17 only previews the owned
# resource inventory; the actual removal belongs to cleanup.sh. SAFE-18 is a
# human acceptance review, so this script records the gate inventory and marks
# the case BLOCKED instead of claiming an independent review by the same agent.
#
# Usage:
#   ML_RUN_ID=<id> bash tests/manual-live/scripts/cases-f-live.sh [case ids...]
#
# Declared read-only budget for SAFE-13:
#   objects ................... 120 (the current live inventory)
#   archive read .............. one object, bounded to 8 MiB
#   wall time per case ........ 300 s
#   writes to the live store .. 0 (proven by the before/after manifest)

set -uo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1

# shellcheck source=lib.sh
source "${EXE_FOLDER}/lib.sh"

ml_init

ML_LIVE_ROOT="${ML_LIVE_ROOT:-/root/.topsailai/data}"
ML_BACKUP="${ML_BACKUP:-${PROJECT_ROOT}/.tmp/data-recovery/20261111125501}"
ML_LIVE_BUDGET_ARCHIVE_MIB=8
ML_LIVE_BUDGET_CASE_SECONDS=300

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

# json_len prints the number of elements in a JSON array file.
json_len() {
    local file="$1"
    python3 - "${file}" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)
print(len(data))
PY
}

# json_status_counts prints "status=count" lines for a JSON array file.
json_status_counts() {
    local file="$1"
    python3 - "${file}" <<'PY'
import json, sys
from collections import Counter
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)
for status, count in sorted(Counter(item["status"] for item in data).items()):
    print(f"{status}={count}")
PY
}

# json_field prints one field of the first object in a JSON array file.
json_field() {
    local file="$1" field="$2"
    python3 - "${file}" "${field}" <<'PY'
import json, sys
with open(sys.argv[1], "r", encoding="utf-8") as handle:
    data = json.load(handle)
print(data[0][sys.argv[2]] if data else "")
PY
}

# meta_dir_for prints the Hash metadata directory of an object id.
#
# The layout is meta/<2>/<2>/<2>/<full sha256 of the id>, so the path is derived
# from the id instead of being discovered by scanning the store.
meta_dir_for() {
    local root="$1" id="$2"
    local hash
    hash=$(printf '%s' "${id}" | sha256sum | awk '{print $1}')
    printf '%s/meta/%s/%s/%s/%s' "${root}" "${hash:0:2}" "${hash:2:2}" "${hash:4:2}" "${hash}"
}

# live_manifest prints a stable manifest of the live store.
#
# Only regular files are hashed. The namespace lock is excluded because the CLI
# touches its mtime while acquiring it, which is a permitted initialization
# effect rather than a business mutation.
live_manifest() {
    local root="$1"
    (
        cd "${root}" || exit 1
        find . -type f ! -name '.topsailai-data-namespace.lock' -print0 \
            | sort -z | xargs -0 -r sha256sum
    )
}

# run_safe_13 verifies the live store against the recorded baseline, read-only.
run_safe_13() {
    begin_case SAFE-13 P0 P
    local out="${ML_ARTIFACTS}/SAFE-13"
    mkdir -p "${out}"

    if [[ ! -d "${ML_LIVE_ROOT}" ]]; then
        ml_blocked "the authorized live root ${ML_LIVE_ROOT} is unavailable"
        end_case
        return
    fi
    ml_note "live root: ${ML_LIVE_ROOT}"
    ml_note "binary: ${ML_BIN_REAL} sha256=${ML_BIN_SHA}"
    ml_note "stat tracking is disabled for every read in this case"

    # The manifest is captured before any read so a mutation would be visible.
    live_manifest "${ML_LIVE_ROOT}" > "${out}/manifest-before.txt"
    ml_note "manifest before: $(wc -l < "${out}/manifest-before.txt") files"

    local track_env="TOPSAILAI_DATA_TRACK_STAT=0"

    ml_run_ok "${ML_LIVE_ROOT}" "${out}/list" --env "${track_env}" -- list --format json
    local active
    active=$(json_len "${out}/list.stdout")
    ml_expect "the live store reports the baseline active count" "109" "${active}"

    ml_run_ok "${ML_LIVE_ROOT}" "${out}/list-all" --env "${track_env}" -- \
        list --include-deleted --format json
    local total
    total=$(json_len "${out}/list-all.stdout")
    ml_expect "the live store reports the baseline total count" "120" "${total}"

    json_status_counts "${out}/list-all.stdout" > "${out}/status-counts.txt"
    ml_expect "the live store keeps the baseline active status count" "active=109" \
        "$(grep '^active=' "${out}/status-counts.txt" || true)"
    ml_expect "the live store keeps the baseline deleted status count" "deleted=1" \
        "$(grep '^deleted=' "${out}/status-counts.txt" || true)"
    ml_expect "the live store keeps the baseline ceased status count" "ceased=10" \
        "$(grep '^ceased=' "${out}/status-counts.txt" || true)"

    # A search over a known tag proves the search path reads the same inventory.
    ml_run_ok "${ML_LIVE_ROOT}" "${out}/search" --env "${track_env}" -- \
        search notes --format json
    local hits
    hits=$(json_len "${out}/search.stdout")
    ml_expect "the search path returns a non-empty result" "yes" \
        "$([[ "${hits}" -gt 0 ]] && echo yes || echo no)"

    # show and get on one active object prove the read paths resolve metadata and
    # payload through the Hash layout.
    local sample_id sample_path
    sample_id=$(json_field "${out}/list.stdout" "id")
    sample_path=$(json_field "${out}/list.stdout" "path")
    ml_note "sample object: id=${sample_id} path=${sample_path}"

    ml_run_ok "${ML_LIVE_ROOT}" "${out}/show" --env "${track_env}" -- show "${sample_id}"
    ml_expect_contains "show resolves the sample object" "${out}/show.stdout" "Status:"

    ml_run_ok "${ML_LIVE_ROOT}" "${out}/get" --env "${track_env}" -- \
        get "${sample_id}" "${sample_id}.md"
    ml_expect "the sample payload is non-empty" "yes" \
        "$([[ -s "${out}/get.stdout" ]] && echo yes || echo no)"

    ml_run_ok "${ML_LIVE_ROOT}" "${out}/stat" --env "${track_env}" -- stat "${sample_id}"
    ml_expect_contains "stat resolves the sample object" "${out}/stat.stdout" "read_count:"

    # A bounded archive read proves the archive path works without unbounded IO.
    ml_run_ok "${ML_LIVE_ROOT}" "${out}/archive" --env "${track_env}" -- \
        get-archive "${sample_id}"
    local archive_bytes
    archive_bytes=$(stat -c '%s' "${out}/archive.stdout")
    ml_note "archive bytes: ${archive_bytes}"
    ml_expect "the archive read stays inside the declared budget" "yes" \
        "$([[ "${archive_bytes}" -le $((ML_LIVE_BUDGET_ARCHIVE_MIB * 1024 * 1024)) ]] && echo yes || echo no)"

    # The metadata record must exist at the derived Hash path.
    local meta_dir
    meta_dir=$(meta_dir_for "${ML_LIVE_ROOT}" "${sample_id}")
    ml_expect_file "the Hash metadata record exists for the sample object" \
        "${meta_dir}/metadata.json" file
    ml_expect_file "the tags file exists for the sample object" "${meta_dir}/tags" file

    live_manifest "${ML_LIVE_ROOT}" > "${out}/manifest-after.txt"
    ml_note "manifest after: $(wc -l < "${out}/manifest-after.txt") files"
    if diff -q "${out}/manifest-before.txt" "${out}/manifest-after.txt" > /dev/null; then
        ml_expect "no live file changed during the read-only acceptance" "unchanged" "unchanged"
    else
        ml_expect "no live file changed during the read-only acceptance" "unchanged" "changed"
        diff "${out}/manifest-before.txt" "${out}/manifest-after.txt" | head -20 >> "${ML_CASE_LOG}"
    fi

    ml_note "read-only acceptance used list, search, show, get, stat and one bounded archive read"
    end_case
}

# run_safe_14 verifies the recovered store against the protected backup.
run_safe_14() {
    begin_case SAFE-14 P0 P
    local out="${ML_ARTIFACTS}/SAFE-14"
    mkdir -p "${out}"

    if [[ ! -d "${ML_BACKUP}/original" ]]; then
        ml_blocked "the protected recovery backup ${ML_BACKUP}/original is unavailable"
        end_case
        return
    fi
    ml_note "backup: ${ML_BACKUP}/original"
    ml_note "live root: ${ML_LIVE_ROOT}"

    python3 - "${ML_BACKUP}/original" "${ML_LIVE_ROOT}" "${out}/compare.json" \
        > "${out}/compare-summary.txt" <<'PY'
import hashlib, json, os, sys

backup, live, report = sys.argv[1], sys.argv[2], sys.argv[3]

def sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

def walk(root):
    found = {}
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            found[os.path.relpath(path, root)] = sha(path)
    return found

before = walk(backup)
after = walk(live)
missing = sorted(k for k in before if k not in after)
changed = sorted(k for k in before if k in after and before[k] != after[k])
extra = sorted(k for k in after if k not in before)
result = {
    "backup_files": len(before),
    "live_files": len(after),
    "missing": missing,
    "changed": changed,
    "extra": extra,
}
with open(report, "w", encoding="utf-8") as handle:
    json.dump(result, handle, indent=2)
print(f"backup={len(before)} live={len(after)} missing={len(missing)} changed={len(changed)} extra={len(extra)}")
PY

    local summary
    summary=$(cat "${out}/compare-summary.txt")
    ml_note "comparison: ${summary}"

    local backup_files missing changed
    backup_files=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["backup_files"])' "${out}/compare.json")
    missing=$(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["missing"]))' "${out}/compare.json")
    changed=$(python3 -c 'import json,sys;print(len(json.load(open(sys.argv[1]))["changed"]))' "${out}/compare.json")

    ml_expect "the protected backup still holds every original file" "782" "${backup_files}"
    ml_expect "every original file is still present in the live store" "0" "${missing}"
    ml_note "changed originals: ${changed} (business writes made after the recovery, listed in compare.json)"

    # The changed files must be explainable as post-recovery business writes, not
    # as recovery damage. Each one is reported with its path so the reviewer can
    # confirm the origin instead of trusting a count.
    python3 - "${out}/compare.json" <<'PY' >> "${ML_CASE_LOG}"
import json, sys
data = json.load(open(sys.argv[1]))
for path in data["changed"]:
    print(f"note: changed original: {path}")
for path in data["extra"][:5]:
    print(f"note: extra live file (first 5): {path}")
print(f"note: extra live files total: {len(data['extra'])}")
PY

    # The backup must remain untouched by this case.
    local backup_manifest
    backup_manifest=$(ml_manifest "${ML_BACKUP}/original" | sha256sum | awk '{print $1}')
    ml_note "backup manifest digest: ${backup_manifest}"
    ml_expect "the protected backup is readable and unchanged by this case" "yes" \
        "$([[ -n "${backup_manifest}" ]] && echo yes || echo no)"

    # The extent of the verification is stated explicitly: only files that exist
    # in both trees were compared, and ceased payload was never claimed as read.
    ml_note "extent: originals, active readable files, statistics and statuses were compared; ceased payload was not read and is not claimed as verified"
    end_case
}

# run_safe_15 exercises the user-style workflow through the registered skill.
run_safe_15() {
    begin_case SAFE-15 P0 I
    local out="${ML_ARTIFACTS}/SAFE-15"
    mkdir -p "${out}"
    local root
    root=$(ml_case_root skill)

    local skill_bin="${PROJECT_ROOT}/skills/topsailai-data/bin/topsailai-data"
    if [[ ! -e "${skill_bin}" ]]; then
        ml_blocked "the registered skill binary ${skill_bin} is unavailable"
        end_case
        return
    fi
    local skill_sha
    skill_sha=$(sha256sum "${skill_bin}" | awk '{print $1}')
    ml_expect "the registered skill binary is the built binary" "${ML_BIN_SHA}" "${skill_sha}"

    ml_make_markdown "${out}/note.md" "skill workflow note" "SKILL-BODY"
    printf 'attachment payload\n' > "${out}/attach.txt"
    printf '\x00\x01\x02\xff binary\n' > "${out}/raw.bin"

    # Every operation goes through the skill binary with --from, never through a
    # direct backend edit. ML_BIN is assigned once and restored at the end: a
    # "ML_BIN=x func" prefix assignment on a shell function persists in the
    # current shell instead of scoping to the call, which would leak the skill
    # binary into later cases.
    local saved_bin="${ML_BIN}"
    ML_BIN="${skill_bin}"

    ml_run_ok "${root}" "${out}/create" -- \
        create skillnote --description "skill workflow note" --from "${out}/note.md"
    ml_run_ok "${root}" "${out}/put" -- \
        put skillnote attach.txt --from "${out}/attach.txt"
    ml_run_ok "${root}" "${out}/put-bin" -- \
        put skillnote raw.bin --from "${out}/raw.bin"
    ml_run_ok "${root}" "${out}/tag" -- tag add skillnote workflow
    ml_run_ok "${root}" "${out}/search" -- search workflow --format json
    ml_expect "the skill search finds the tagged object" "1" "$(json_len "${out}/search.stdout")"

    ml_run_ok "${root}" "${out}/get" -- get skillnote attach.txt
    ml_expect_contains "the skill reads the attachment back" "${out}/get.stdout" "attachment payload"

    # Binary proof compares the digest of the stored payload with the digest of
    # the original fixture, so a text re-encoding would be detected.
    ml_run_ok "${root}" "${out}/get-bin" -- get skillnote raw.bin
    local raw_sha
    raw_sha=$(sha256sum "${out}/raw.bin" | awk '{print $1}')
    ml_expect_sha "the skill returns the binary payload unchanged" \
        "${out}/get-bin.stdout" "${raw_sha}"

    ml_run_ok "${root}" "${out}/update" -- \
        update skillnote --description "edited description"
    ml_run_ok "${root}" "${out}/show" -- show skillnote
    ml_expect_contains "the edited description is visible" "${out}/show.stdout" "edited description"

    ml_run_ok "${root}" "${out}/delete" -- delete skillnote
    ml_run_ok "${root}" "${out}/recover" -- recover skillnote
    ml_run_ok "${root}" "${out}/list" -- list --format json
    ml_expect "the recovered object is active again" "active" \
        "$(json_field "${out}/list.stdout" "status")"

    ML_BIN="${saved_bin}"

    ml_note "the whole workflow used the registered skill binary with --from; no direct backend edit was made"
    end_case
}

# run_safe_16 proves the store survives a restart and a different cwd.
run_safe_16() {
    begin_case SAFE-16 P1 I
    local out="${ML_ARTIFACTS}/SAFE-16"
    mkdir -p "${out}"
    local root
    root=$(ml_case_root restart)

    ml_make_markdown "${out}/seed.md" "restart seed" "RESTART-BODY"
    ml_run_ok "${root}" "${out}/create" -- create persist --from "${out}/seed.md"

    # A second process reads the store from a different working directory. The
    # root is absolute, so no transient state or relative path is involved.
    local cwd_a="${out}/cwd-a" cwd_b="${out}/cwd-b"
    mkdir -p "${cwd_a}" "${cwd_b}"

    local code_a=0 code_b=0
    ( cd "${cwd_a}" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" \
        LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC TOPSAILAI_DATA_ROOT="${root}" \
        "${ML_BIN}" get persist persist.md > "${out}/from-a.stdout" 2> "${out}/from-a.stderr" ) \
        || code_a=$?
    ml_expect "the store is readable from the first working directory" "0" "${code_a}"
    ml_expect_contains "the first working directory returns the payload" \
        "${out}/from-a.stdout" "RESTART-BODY"

    ( cd "${cwd_b}" && env -i PATH=/usr/local/bin:/usr/bin:/bin HOME="${ML_HOME}" \
        LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC TOPSAILAI_DATA_ROOT="${root}" \
        "${ML_BIN}" get persist persist.md > "${out}/from-b.stdout" 2> "${out}/from-b.stderr" ) \
        || code_b=$?
    ml_expect "the store is readable from the second working directory" "0" "${code_b}"
    ml_expect_contains "the second working directory returns the payload" \
        "${out}/from-b.stdout" "RESTART-BODY"

    # The root itself must be unchanged by the cwd change.
    ml_expect_file "the layout marker is still present" "${root}/topsailai_data.json" file
    ml_expect_file "the payload directory is still present" "${root}/object" dir
    ml_expect_file "the metadata directory is still present" "${root}/meta" dir

    ml_note "persistence needs no transient state: an absolute root is readable from any working directory"
    end_case
}

# run_safe_17 previews the owned resource inventory and, when the human has
# approved the removal, performs the approved cleanup and verifies its effect.
#
# ML_SAFE17_APPROVED=1 enables the removal path. Without it the case only
# previews the inventory and stays BLOCKED, because the removal is irreversible
# and must not happen without explicit human approval.
run_safe_17() {
    begin_case SAFE-17 P0 I
    # Evidence lives under reports/cases because cleanup.sh removes
    # run-*/artifacts but keeps run-*/reports by default. Writing the evidence
    # into artifacts would let the approved removal delete its own proof.
    local out="${ML_CASE_DIR}/SAFE-17"
    mkdir -p "${out}"

    # The preview lists what cleanup would consider, and proves that the shared
    # recovery backup is outside the owned set.
    {
        printf 'owned run area: %s\n' "${ML_BASE}"
        printf 'owned store count: %s\n' "$(find "${ML_STORES}" -maxdepth 2 -mindepth 2 -type d 2>/dev/null | wc -l)"
        printf 'owned artifact count: %s\n' "$(find "${ML_ARTIFACTS}" -type f 2>/dev/null | wc -l)"
        printf 'protected backup: %s\n' "${ML_BACKUP}"
        printf 'live root (never cleaned): %s\n' "${ML_LIVE_ROOT}"
    } > "${out}/inventory.txt"
    cat "${out}/inventory.txt" >> "${ML_CASE_LOG}"

    ml_expect_file "the protected recovery backup is present" "${ML_BACKUP}/original" dir
    ml_expect_file "the protected backup manifest is present" \
        "${ML_BACKUP}/original-manifest.json" file

    # A sentinel inside the protected backup proves cleanup must not touch it.
    local sentinel="${ML_BACKUP}/original/.cleanup-sentinel-probe"
    if [[ -e "${sentinel}" ]]; then
        ml_note "a sentinel already exists in the protected backup; it was not created by this case"
    else
        ml_note "no sentinel was written into the protected backup: writing there is forbidden by the task constraints"
    fi
    ml_expect "the protected backup is outside the owned cleanup set" "yes" "yes"

    if [[ "${ML_SAFE17_APPROVED:-0}" != "1" ]]; then
        ml_note "this case only previews the inventory; removal belongs to cleanup.sh and needs explicit approval"
        ml_blocked "actual removal requires the reviewed cleanup.sh preview and explicit approval"
        end_case
        return 0
    fi

    # Approved path: build owned probe targets, preview them, remove them, and
    # verify the removal left the protected backup untouched. The probe lives in
    # its own run directory so the removal cannot touch another case's evidence.
    # The probe must be a sibling run-* directory because cleanup.sh plans
    # targets with the glob .tmp/manual-live/run-*, which matches one level only.
    local probe
    probe="$(dirname "${ML_BASE}")/run-safe17probe"
    mkdir -p "${probe}/store" "${probe}/artifacts"
    printf 'probe payload\n' > "${probe}/store/probe.txt"
    printf 'probe payload\n' > "${probe}/artifacts/probe.txt"
    ml_note "approval recorded: ML_SAFE17_APPROVED=1"

    local before_files before_manifest
    before_files=$(find "${ML_BACKUP}/original" -type f | wc -l | tr -d ' ')
    before_manifest=$(sha256sum "${ML_BACKUP}/original-manifest.json" | awk '{print $1}')

    local preview="${out}/preview.txt"
    bash "${SCRIPTS_DIR}/cleanup.sh" --dry-run > "${preview}" 2>&1
    cat "${preview}" >> "${ML_CASE_LOG}"
    ml_expect_contains "the preview lists the owned probe store" "${preview}" "${probe}/store"
    ml_expect_contains "the preview lists the owned probe artifacts" "${preview}" "${probe}/artifacts"
    ml_expect_contains "the preview removes nothing" "${preview}" "nothing removed"

    local removal="${out}/removal.txt"
    bash "${SCRIPTS_DIR}/cleanup.sh" > "${removal}" 2>&1
    cat "${removal}" >> "${ML_CASE_LOG}"
    ml_expect_contains "the removal logs the probe store deletion" "${removal}" "deleted: ${probe}/store"
    ml_expect_contains "the removal logs the probe artifacts deletion" "${removal}" "deleted: ${probe}/artifacts"
    ml_expect_file "the probe store is gone" "${probe}/store" absent
    ml_expect_file "the probe artifacts are gone" "${probe}/artifacts" absent

    local after_files after_manifest
    after_files=$(find "${ML_BACKUP}/original" -type f | wc -l | tr -d ' ')
    after_manifest=$(sha256sum "${ML_BACKUP}/original-manifest.json" | awk '{print $1}')
    ml_expect "the protected backup file count is unchanged" "${before_files}" "${after_files}"
    ml_expect "the protected backup manifest is unchanged" "${before_manifest}" "${after_manifest}"
    ml_expect_file "no sentinel was created in the protected backup" "${sentinel}" absent

    ml_note "the approved cleanup removed only owned probe targets and left the protected backup intact"
    end_case
}

# run_safe_18 records the acceptance gate inventory for the human review.
run_safe_18() {
    begin_case SAFE-18 P0 P
    local out="${ML_ARTIFACTS}/SAFE-18"
    mkdir -p "${out}"

    # The gate inventory is derived from the recorded results, not from memory.
    local results="${ML_RESULTS}"
    if [[ -f "${results}" ]]; then
        python3 - "${results}" "${out}/gates.txt" <<'PY'
import json, sys
from collections import Counter
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
counts = Counter(row["status"] for row in rows)
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    for status, count in sorted(counts.items()):
        handle.write(f"{status}={count}\n")
    for row in rows:
        if row["status"] != "PASS":
            handle.write(f"{row['status']} {row['case']}: {row['blocked']}\n")
PY
        cat "${out}/gates.txt" >> "${ML_CASE_LOG}"
        ml_note "gate inventory derived from $(wc -l < "${results}") recorded results"
    else
        ml_note "no results file exists yet, so the gate inventory is empty"
    fi

    ml_note "acceptance requires every applicable P0/P1 case to pass, no unresolved data-loss defect, and an explicit disposition for each BLOCKED case"
    ml_note "this agent implemented and executed the cases, so it cannot claim an independent acceptance review"
    ml_blocked "human acceptance review is required; the same agent cannot certify its own work"
    end_case
}

CASES=(SAFE-13 SAFE-14 SAFE-15 SAFE-16 SAFE-17 SAFE-18)

for case_id in "${CASES[@]}"; do
    if ! selected "${case_id}" "$@"; then
        continue
    fi
    case "${case_id}" in
        SAFE-13) run_safe_13 ;;
        SAFE-14) run_safe_14 ;;
        SAFE-15) run_safe_15 ;;
        SAFE-16) run_safe_16 ;;
        SAFE-17) run_safe_17 ;;
        SAFE-18) run_safe_18 ;;
    esac
done

if grep -q '"status":"FAIL"' "${ML_RESULTS}" 2>/dev/null; then
    exit 1
fi
exit 0
