#!/usr/bin/env bash
# prepare: validate run boundaries, binary identity, fixtures and controls.
#
# This script never touches the existing live store. It creates the isolated
# run area, records binary identity, and builds the shared fixtures used by the
# case scripts. It refuses to reuse a non-empty run area unless --force is
# given, so a previous run's evidence is never silently overwritten.

set -euo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")
cd "${EXE_FOLDER}" || exit 1

# shellcheck source=lib.sh
source "${EXE_FOLDER}/lib.sh"

usage() {
    cat <<'EOF'
Usage: prepare.sh [--force] [--run-id <id>]

Creates the isolated manual/live run area and shared fixtures.

Options:
  --force          reuse an existing run area (previous evidence is kept)
  --run-id <id>    explicit run identifier instead of a timestamp
  -h, --help       show this help

Exit codes:
  0  run area ready
  1  unsafe or unusable run area
  2  invalid arguments
EOF
}

FORCE=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE=1; shift ;;
        --run-id) ML_RUN_ID="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

ML_BASE="${PROJECT_ROOT}/.tmp/manual-live/${ML_RUN_ID}"
ML_REPORTS="${ML_BASE}/reports"
ML_CASE_DIR="${ML_REPORTS}/cases"
ML_RESULTS="${ML_REPORTS}/results.jsonl"
ML_FIXTURES="${ML_BASE}/fixtures"
ML_STORES="${ML_BASE}/stores"
ML_ARTIFACTS="${ML_BASE}/artifacts"
ML_HOME="${ML_BASE}/home"

# Refuse to run outside the project's temporary area.
case "${ML_BASE}" in
    "${PROJECT_ROOT}/.tmp/manual-live/"*) ;;
    *) printf 'refusing run area outside .tmp/manual-live: %s\n' "${ML_BASE}" >&2; exit 1 ;;
esac

if [[ -e "${ML_BASE}" && "${FORCE}" -eq 0 ]]; then
    printf 'run area already exists: %s (use --force to reuse)\n' "${ML_BASE}" >&2
    exit 1
fi

ml_init

# Fixtures: markdown variants covering the description fallback contract.
ml_make_markdown "${ML_FIXTURES}/md/plain.md" "Plain description" "# Plain"
ml_make_markdown "${ML_FIXTURES}/md/unicode.md" "Unicode 描述 ✓" "# 你好 world"
printf '# no frontmatter\n' > "${ML_FIXTURES}/md/no-frontmatter.md"
printf -- '---\ndescription: [not, a, string]\n---\n\nbody\n' > "${ML_FIXTURES}/md/non-string.md"
printf -- '---\nname: only-name\n---\n\nbody\n' > "${ML_FIXTURES}/md/missing-key.md"
printf -- '---\ndescription: "unterminated\n\nbody\n' > "${ML_FIXTURES}/md/malformed.md"
printf -- '---\ndescription: ""\n---\n\nbody\n' > "${ML_FIXTURES}/md/empty-description.md"
printf '' > "${ML_FIXTURES}/md/empty.md"
printf 'body only, no frontmatter\n' > "${ML_FIXTURES}/md/body-only.md"

# 8 KiB boundary: the description block ends just before, at, and after 8192 bytes.
python3 - "${ML_FIXTURES}/md" <<'PY'
import sys, pathlib
base = pathlib.Path(sys.argv[1])
for name, pad in (("boundary-before", 8100), ("boundary-at", 8192), ("boundary-after", 8300)):
    filler = "x" * pad
    (base / f"{name}.md").write_text(
        "---\ndescription: boundary\n---\n" + filler + "\n", encoding="utf-8"
    )
PY

# Line-oriented fixtures for the file readers and editors.
mkdir -p "${ML_FIXTURES}/text"
printf 'alpha\nbeta\ngamma\ndelta\n' > "${ML_FIXTURES}/text/lines-lf.txt"
printf 'alpha\r\nbeta\r\ngamma\r\n' > "${ML_FIXTURES}/text/lines-crlf.txt"
printf 'alpha\nbeta' > "${ML_FIXTURES}/text/no-final-newline.txt"
printf '' > "${ML_FIXTURES}/text/empty.txt"
printf 'one two one two one\n' > "${ML_FIXTURES}/text/overlap.txt"

# Deterministic binary fixture containing NUL and every byte value.
python3 - "${ML_FIXTURES}/binary/pattern.bin" <<'PY'
import sys, pathlib
path = pathlib.Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(bytes(range(256)) * 8 + b"\x00\x00tail")
PY

# Size-limit fixtures around the default 30000-byte truncation limit.
python3 - "${ML_FIXTURES}/text" <<'PY'
import sys, pathlib
base = pathlib.Path(sys.argv[1])
for name, size in (("limit-minus", 29999), ("limit", 30000), ("limit-plus", 30001)):
    (base / f"{name}.log").write_text("a" * size, encoding="utf-8")
PY

# Archive fixtures: marker present, marker absent, traversal, absolute, link.
mkdir -p "${ML_FIXTURES}/archive/marker" "${ML_FIXTURES}/archive/no-marker" \
         "${ML_FIXTURES}/archive/traversal" "${ML_FIXTURES}/archive/absolute" \
         "${ML_FIXTURES}/archive/link"
printf 'replacement marker\n' > "${ML_FIXTURES}/archive/marker/__OBJ__.md"
printf 'extra payload\n' > "${ML_FIXTURES}/archive/no-marker/extra.txt"
printf 'evil\n' > "${ML_FIXTURES}/archive/traversal/evil.txt"
printf 'absolute\n' > "${ML_FIXTURES}/archive/absolute/abs.txt"
printf 'linked\n' > "${ML_FIXTURES}/archive/link/target.txt"
ln -sf target.txt "${ML_FIXTURES}/archive/link/link.txt"

# Hostile archives are built per case because they need the object name.
tar -cf "${ML_FIXTURES}/archive/traversal.tar" -C "${ML_FIXTURES}/archive/traversal" \
    --transform 's,^\./,,' --transform 's,evil.txt,../../escaped.txt,' evil.txt
tar -cf "${ML_FIXTURES}/archive/absolute.tar" -C "${ML_FIXTURES}/archive/absolute" \
    --transform 's,^\./,,' --transform 's,abs.txt,/tmp/manual-live-absolute.txt,' abs.txt
tar -cf "${ML_FIXTURES}/archive/link.tar" -C "${ML_FIXTURES}/archive/link" \
    --transform 's,^\./,,' target.txt link.txt
printf 'not a tar archive\n' > "${ML_FIXTURES}/archive/malformed.tar"
head -c 512 "${ML_FIXTURES}/archive/traversal.tar" > "${ML_FIXTURES}/archive/truncated.tar"

# Independent oracle manifests computed before execution.
ml_manifest "${ML_FIXTURES}" > "${ML_REPORTS}/fixtures.manifest"
sha256sum "${ML_FIXTURES}/binary/pattern.bin" > "${ML_REPORTS}/binary.manifest"

# Sentinel store and file prove that no case escapes its own root.
mkdir -p "${ML_STORES}/sentinel-store"
printf 'sentinel\n' > "${ML_ARTIFACTS}/sentinel.txt"
sha256sum "${ML_ARTIFACTS}/sentinel.txt" > "${ML_REPORTS}/sentinel.manifest"

printf 'run area ready: %s\n' "${ML_BASE}"
printf 'binary: %s\n' "${ML_BIN_REAL}"
printf 'binary sha256: %s\n' "${ML_BIN_SHA}"
