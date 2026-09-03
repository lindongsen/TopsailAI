#!/usr/bin/env bash
#
# build-deb-and-update-container.sh
#
# Build the TopsailAI deb packages and hot-update them into a running
# container instance (e.g. topsailai-1) WITHOUT rebuilding the Docker image.
#
# Author: DawsonLin
#
# Workflow (see topsailai_data note: topsailai-deb-docker-build-guide,
# Appendix B "Verified Hot-Update Without Rebuilding Image"):
#   1. make build-deb  ->  $OUTPUT_DIR/topsailai-<ts>.deb (+ topsailai-data-<ts>.deb)
#   2. copy the debs into the container's host shared-folder mount
#      (host folder auto-syncs into the container, e.g. /data)
#   3. docker exec <container> dpkg -i /data/<deb> ...
#   4. clean up the temporary debs
#   5. verify the installed version matches the freshly built deb
#
# Usage:
#   ./build-deb-and-update-container.sh [--container NAME] [--skip-build] [--no-verify]
#
# Options:
#   --container NAME   target container name (default: $CONTAINER or topsailai-1)
#   --skip-build       skip the deb build step, only update an existing build
#   --no-verify        skip the post-install version verification
#   -h, --help         show this help
#
# Environment variables (all optional):
#   PROJECT_HOME  - TopsailAI project root            (default: /TopsailAI)
#   CONTAINER     - target container name             (default: topsailai-1)
#   OUTPUT_DIR    - deb output directory              (default: $PROJECT_HOME/build/output)
#   HOST_MOUNT    - host folder bind-mounted into the container
#                   (default: auto-detected via docker inspect)
#   REQUIRE_NEW_SO- force recompilation when set to 1 (default: 0)
#
# Examples:
#   ./build-deb-and-update-container.sh
#   ./build-deb-and-update-container.sh --container topsailai-2
#   ./build-deb-and-update-container.sh --skip-build
#

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (env overridable, no hardcoded paths)
# ---------------------------------------------------------------------------
PROJECT_HOME="${PROJECT_HOME:-/TopsailAI}"
CONTAINER="${CONTAINER:-topsailai-1}"
OUTPUT_DIR="${OUTPUT_DIR:-${PROJECT_HOME}/build/output}"
REQUIRE_NEW_SO="${REQUIRE_NEW_SO:-0}"
HOST_MOUNT="${HOST_MOUNT:-}"

SKIP_BUILD=0
DO_VERIFY=1

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --container)
      [ $# -ge 2 ] || { echo "error: --container requires a value" >&2; exit 1; }
      CONTAINER="$2"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --no-verify)
      DO_VERIFY=0
      shift
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "error: unknown option: $1" >&2
      usage
      ;;
  esac
done

log()  { echo "==> $*"; }
warn() { echo "!!  $*" >&2; }
die()  { echo "ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
[ -d "${PROJECT_HOME}" ] || die "PROJECT_HOME does not exist: ${PROJECT_HOME}"
[ -f "${PROJECT_HOME}/Makefile" ] || die "Makefile not found in ${PROJECT_HOME}"

if ! command -v docker >/dev/null 2>&1; then
  die "docker command not found"
fi

if ! docker inspect "${CONTAINER}" >/dev/null 2>&1; then
  die "container '${CONTAINER}' does not exist (docker inspect failed)"
fi

# ---------------------------------------------------------------------------
# Detect the host folder bind-mounted into the container
# ---------------------------------------------------------------------------
detect_host_mount() {
  local mounts line type src dst
  mounts=$(docker inspect "${CONTAINER}" \
    --format '{{range .Mounts}}{{.Type}}|{{.Source}}|{{.Destination}}{{println}}{{end}}' \
    2>/dev/null || true)

  # 1) Prefer the conventional per-container folder
  #    /opt/docker/topsailai/<container-name>
  while IFS= read -r line; do
    [ -n "${line}" ] || continue
    type=${line%%|*}
    rest=${line#*|}
    src=${rest%%|*}
    dst=${rest#*|}
    if [ "${type}" = "bind" ] && [ "${src}" = "/opt/docker/topsailai/${CONTAINER}" ]; then
      echo "${src}|${dst}"
      return 0
    fi
  done <<< "${mounts}"

  # 2) Fall back to the first bind mount
  while IFS= read -r line; do
    [ -n "${line}" ] || continue
    type=${line%%|*}
    rest=${line#*|}
    src=${rest%%|*}
    dst=${rest#*|}
    if [ "${type}" = "bind" ]; then
      echo "${src}|${dst}"
      return 0
    fi
  done <<< "${mounts}"

  return 1
}

if [ -z "${HOST_MOUNT}" ]; then
  if ! HOST_MOUNT=$(detect_host_mount); then
    die "no bind mount found for container '${CONTAINER}'; set HOST_MOUNT explicitly"
  fi
fi

HOST_DIR="${HOST_MOUNT%%|*}"
CONTAINER_DIR="${HOST_MOUNT#*|}"
[ -d "${HOST_DIR}" ] || die "host mount folder does not exist: ${HOST_DIR}"

log "Target container : ${CONTAINER}"
log "Host mount folder: ${HOST_DIR}  ->  container ${CONTAINER_DIR}"

# ---------------------------------------------------------------------------
# Step 1: Build the deb packages (unless --skip-build)
# ---------------------------------------------------------------------------
if [ "${SKIP_BUILD}" -eq 1 ]; then
  log "Skipping deb build (--skip-build)"
else
  log "Building deb packages (make build-deb, REQUIRE_NEW_SO=${REQUIRE_NEW_SO}) ..."
  ( cd "${PROJECT_HOME}" && REQUIRE_NEW_SO="${REQUIRE_NEW_SO}" make build-deb )
fi

# ---------------------------------------------------------------------------
# Step 2: Locate the freshly built debs (latest by mtime)
# ---------------------------------------------------------------------------
DEB_CORE=$(ls -t "${OUTPUT_DIR}"/topsailai-[0-9]*.deb 2>/dev/null | head -1 || true)
DEB_DATA=$(ls -t "${OUTPUT_DIR}"/topsailai-data-[0-9]*.deb 2>/dev/null | head -1 || true)

[ -n "${DEB_CORE}" ]  || die "no topsailai deb found in ${OUTPUT_DIR}"
[ -n "${DEB_DATA}" ]  || die "no topsailai-data deb found in ${OUTPUT_DIR}"

log "Deb packages:"
log "  ${DEB_CORE}"
log "  ${DEB_DATA}"

# ---------------------------------------------------------------------------
# Step 3: Copy debs into the container via the host shared-folder mount
# ---------------------------------------------------------------------------
log "Copying debs into host mount folder ${HOST_DIR} ..."
cp -f "${DEB_CORE}" "${HOST_DIR}/"
cp -f "${DEB_DATA}" "${HOST_DIR}/"

CORE_NAME=$(basename "${DEB_CORE}")
DATA_NAME=$(basename "${DEB_DATA}")

# ---------------------------------------------------------------------------
# Step 4: Upgrade-install inside the container
# ---------------------------------------------------------------------------
log "Installing debs inside container ${CONTAINER} (dpkg -i) ..."
docker exec "${CONTAINER}" dpkg -i \
  "${CONTAINER_DIR}/${CORE_NAME}" \
  "${CONTAINER_DIR}/${DATA_NAME}"

# ---------------------------------------------------------------------------
# Step 5: Clean up the temporary debs (logged deletion)
# ---------------------------------------------------------------------------
log "Cleaning up temporary debs ..."
docker exec "${CONTAINER}" rm -f \
  "${CONTAINER_DIR}/${CORE_NAME}" \
  "${CONTAINER_DIR}/${DATA_NAME}"
log "Removed ${CONTAINER_DIR}/${CORE_NAME} and ${CONTAINER_DIR}/${DATA_NAME} inside ${CONTAINER}"

# ---------------------------------------------------------------------------
# Step 6: Verify installed version matches the built deb
# ---------------------------------------------------------------------------
if [ "${DO_VERIFY}" -eq 1 ]; then
  log "Verifying installed versions ..."
  CORE_TS=$(basename "${DEB_CORE}" | sed -E 's/^topsailai-([0-9]+)\.deb$/\1/')
  DATA_TS=$(basename "${DEB_DATA}" | sed -E 's/^topsailai-data-([0-9]+)\.deb$/\1/')

  INSTALLED_CORE=$(docker exec "${CONTAINER}" dpkg-query -W -f='${Version}' topsailai 2>/dev/null || true)
  INSTALLED_DATA=$(docker exec "${CONTAINER}" dpkg-query -W -f='${Version}' topsailai-data 2>/dev/null || true)

  log "  topsailai      built=${CORE_TS} installed=${INSTALLED_CORE}"
  log "  topsailai-data built=${DATA_TS} installed=${INSTALLED_DATA}"

  if [ "${INSTALLED_CORE}" = "${CORE_TS}" ] && [ "${INSTALLED_DATA}" = "${DATA_TS}" ]; then
    log "Verification OK: container ${CONTAINER} is up to date."
  else
    warn "Verification mismatch: installed versions differ from the built debs."
    warn "  topsailai      expected=${CORE_TS} actual=${INSTALLED_CORE}"
    warn "  topsailai-data expected=${DATA_TS} actual=${INSTALLED_DATA}"
    exit 1
  fi
else
  log "Skipping verification (--no-verify)"
fi

log "Done. Container ${CONTAINER} updated with the latest TopsailAI debs."
