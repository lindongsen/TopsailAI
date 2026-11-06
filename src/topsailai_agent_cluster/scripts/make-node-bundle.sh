#!/bin/bash
# Author: DawsonLin
# Purpose: Assemble a relocatable Agent Cluster node bundle.
#
# The bundle is the unit of deployment: controller script, role binary, role
# configuration and TLS material. Copy the directory to a node and run
# ./agent-clusterctl start there. Nothing in the bundle refers back to this
# repository, so the node needs no source tree and no build toolchain.
#
# Usage:
#   make-node-bundle.sh --role <server|endpoint> --dest <dir> [options]
#
# Options:
#   --role     server or endpoint (required)
#   --dest     destination directory (required)
#   --cert     leaf certificate to embed (required)
#   --key      private key paired with --cert (required)
#   --ca       CA certificate (default: .tmp/local-cluster/certs/ca.pem)
#   --config   configuration template (default: conf/node.<role>.conf.example)
#   --adapters adapter JSON for the endpoint role; replaces the template value
#   --static   build the binary with CGO disabled for a foreign libc

set -uo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
PROJECT_DIR=$(dirname "${SCRIPT_DIR}")

ROLE=""
DEST=""
CERT=""
KEY=""
CA="${PROJECT_DIR}/.tmp/local-cluster/certs/ca.pem"
CONFIG=""
ADAPTERS=""
STATIC=0

function die() {
    echo "ERROR: $*" >&2
    exit 1
}

function usage() {
    sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//' >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --role) ROLE="${2:-}"; shift 2 ;;
        --dest) DEST="${2:-}"; shift 2 ;;
        --cert) CERT="${2:-}"; shift 2 ;;
        --key) KEY="${2:-}"; shift 2 ;;
        --ca) CA="${2:-}"; shift 2 ;;
        --config) CONFIG="${2:-}"; shift 2 ;;
        --adapters) ADAPTERS="${2:-}"; shift 2 ;;
        --static) STATIC=1; shift ;;
        -h | --help) usage ;;
        *) die "unknown argument $1" ;;
    esac
done

case "${ROLE}" in
    server | endpoint) ;;
    *) die "--role must be server or endpoint" ;;
esac
[ -n "${DEST}" ] || die "--dest is required"
[ -f "${CERT}" ] || die "missing certificate ${CERT}"
[ -f "${KEY}" ] || die "missing private key ${KEY}"
[ -f "${CA}" ] || die "missing CA ${CA}"

[ -n "${CONFIG}" ] || CONFIG="${PROJECT_DIR}/conf/node.${ROLE}.conf.example"
[ -f "${CONFIG}" ] || die "missing configuration template ${CONFIG}"

PKG="./src/main/agent-cluster-${ROLE}"
BINARY_NAME="agent-cluster-${ROLE}"

mkdir -p "${DEST}/bin" "${DEST}/conf" "${DEST}/certs" \
    "${DEST}/data" "${DEST}/logs" "${DEST}/run" ||
    die "cannot create ${DEST}"

# Build the role binary. A static build removes any dependency on the node libc.
if [ "${STATIC}" -eq 1 ]; then
    ( cd "${PROJECT_DIR}" && CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" \
        -o "${DEST}/bin/${BINARY_NAME}" "${PKG}" ) ||
        die "static build failed for ${PKG}"
else
    ( cd "${PROJECT_DIR}" && go build -o "${DEST}/bin/${BINARY_NAME}" "${PKG}" ) ||
        die "build failed for ${PKG}"
fi

install -m 0755 "${SCRIPT_DIR}/agent-clusterctl" "${DEST}/agent-clusterctl" ||
    die "cannot install controller"
install -m 0644 "${CONFIG}" "${DEST}/conf/node.conf" ||
    die "cannot install configuration"
install -m 0644 "${CA}" "${DEST}/certs/ca.pem" || die "cannot install CA"
install -m 0644 "${CERT}" "${DEST}/certs/node.pem" || die "cannot install certificate"
install -m 0600 "${KEY}" "${DEST}/certs/node-key.pem" || die "cannot install key"

# An adapter override is appended rather than substituted: the controller sources
# the configuration, so a later assignment wins and the template stays readable.
# The value is single-quoted, so it must not itself contain a single quote.
if [ -n "${ADAPTERS}" ]; then
    [ "${ROLE}" = "endpoint" ] || die "--adapters only applies to the endpoint role"
    case "${ADAPTERS}" in
        *"'"*) die "--adapters must not contain a single quote" ;;
    esac
    {
        echo ""
        echo "# Adapter override supplied when the bundle was assembled."
        echo "ADAPTERS='${ADAPTERS}'"
    } >>"${DEST}/conf/node.conf" || die "cannot append adapter override"
fi

echo "bundle ready: ${DEST}"
echo "  role    : ${ROLE}"
echo "  binary  : bin/${BINARY_NAME}"
echo "  config  : conf/node.conf"
echo "carry it to the node and run: ./agent-clusterctl doctor && ./agent-clusterctl start"
