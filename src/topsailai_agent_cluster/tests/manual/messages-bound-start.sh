#!/bin/bash
# Author: DawsonLin
# Purpose: Start an isolated Agent Cluster for the messages display-bound check.
#
# This is a manual-test launcher, not a deployment script. It exists because the
# display bound is only observable in a running binary, and because the live
# deployment must not be touched: scripts/start-local-cluster.sh drives the live
# Server, the ai-dev container and the relay ports, so using it here would restart
# the live Server and kill the live Agents.
#
# It starts one Server and one Endpoint on ports that do not collide with the live
# deployment, writes their exact PIDs to a pid directory, and waits for readiness.
# It never stops anything: teardown is a separate script so a startup failure is
# reported as a startup failure rather than as a failed assertion.
#
# The message body is supplied by the caller through AGENT_CLUSTER_TEST_MESSAGES_BODY
# and forwarded to the provider as an argv flag. It cannot travel as an environment
# variable: the Generic CLI Adapter sets a child's environment to exactly the
# configured Environment, which is empty, so an exported variable never reaches the
# provider process.

set -uo pipefail

PROJECT_DIR=/TopsailAI/src/topsailai_agent_cluster
RUN_DIR="${PROJECT_DIR}/.tmp/msgbound"
CERT_DIR="${RUN_DIR}/certs"
PROVIDER_DIR="${RUN_DIR}/provider"
PROVIDER_BIN="${PROVIDER_DIR}/agent-cluster-provider-mock"
SERVER_BIN="${PROJECT_DIR}/bin/agent-cluster-server"
ENDPOINT_BIN="${PROJECT_DIR}/bin/agent-cluster-endpoint"

API_PORT=28080
CHANNEL_PORT=28443
# The Endpoint identity must equal the client certificate subject, because the
# Server verifies the certificate name during the mTLS handshake. The generator
# issues the client certificate with the DNS SAN endpoint-1, so any other value
# fails the handshake and looks like a network fault rather than an identity
# mismatch.
ENDPOINT_ID=endpoint-1
AUTH_TOKEN=msgbound-token

function die() {
    echo "ERROR: $*" >&2
    exit 1
}

function require_file() {
    [ -f "$1" ] || die "missing required file: $1"
}

# The provider is the mock Provider CLI, which is a separate Go module. It is built
# from its own directory because a module cannot be built from the repository root,
# and the build runs from the project directory so the caller's working directory
# never decides what gets built.
#
# The mock answers inspection, discovery, messages and command execution from one
# executable, so there is no second sibling binary to build. The removed fixture
# needed one because it resolved topsailai_session_info as a sibling; that
# resolution no longer exists.
cd "${PROJECT_DIR}" || die "cannot enter ${PROJECT_DIR}"
mkdir -p "${PROVIDER_DIR}"
if ! (cd "${PROJECT_DIR}/providers/mock" && go build -o "${PROVIDER_BIN}" .); then
    die "failed to build the mock provider cli"
fi

require_file "${SERVER_BIN}"
require_file "${ENDPOINT_BIN}"
require_file "${PROVIDER_BIN}"

mkdir -p "${RUN_DIR}/logs" "${RUN_DIR}/data" "${RUN_DIR}/pids"

# The certificates are minted per run rather than reused, because the harness
# implementation issues them with a one-hour lifetime. A directory left by an
# earlier run is therefore expired, and the Endpoint reports "certificate has
# expired or is not yet valid", which reads like a transport fault instead of a
# stale artifact. Minting here also keeps the run independent of any temporary
# directory another task may have created.
# The removal is guarded because an empty CERT_DIR would turn it into `rm -rf /`,
# and the value is derived from RUN_DIR rather than typed, so a future edit to
# RUN_DIR must not be able to widen the deletion.
[ -n "${CERT_DIR}" ] || die "CERT_DIR is empty; refusing to remove it"
case "${CERT_DIR}" in
    "${RUN_DIR}"/*) ;;
    *) die "CERT_DIR ${CERT_DIR} is outside ${RUN_DIR}; refusing to remove it" ;;
esac
rm -rf "${CERT_DIR}"
mkdir -p "${CERT_DIR}"
if ! go run ./tests/manual/messages-bound-gencerts "${CERT_DIR}" >/dev/null; then
    die "failed to mint the TLS material"
fi
require_file "${CERT_DIR}/ca.pem"
require_file "${CERT_DIR}/server.pem"
require_file "${CERT_DIR}/server-key.pem"
require_file "${CERT_DIR}/client.pem"
require_file "${CERT_DIR}/client-key.pem"

# Refuse to start on top of a running instance, so a stale process cannot be
# mistaken for the one this script started.
for name in server endpoint; do
    pid_file="${RUN_DIR}/pids/${name}.pid"
    if [ -f "${pid_file}" ]; then
        pid=$(cat "${pid_file}" 2>/dev/null)
        if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
            die "${name} is already running with pid ${pid}; run messages-bound-stop.sh first"
        fi
        rm -f "${pid_file}"
    fi
done

# The fixture body is a display fixture, so an unset value is a usage error rather
# than a silent default: a run with no body would prove nothing about rendering.
if [ -z "${AGENT_CLUSTER_TEST_MESSAGES_BODY:-}" ]; then
    die "AGENT_CLUSTER_TEST_MESSAGES_BODY must be set to the body under test"
fi

# The adapter is a Generic CLI Adapter pointed at the mock Provider CLI. The
# provider type must be genericcli: the factory refuses any other value at startup,
# so a stale "topsailai" here would make the Endpoint exit instead of serving.
#
# --session-dir is required because the Cluster resolves an operator command's
# working directory from provider evidence and refuses the command when the
# provider reports none.
#
# --messages-body carries the display body under test. It is argv rather than an
# environment variable because the adapter sets a child's environment to exactly
# the configured Environment, which is empty.
#
# The document is built by a JSON encoder rather than by printf, because the body
# under test is arbitrary text: a body containing a double quote or a backslash
# would produce an unparseable document and the Endpoint would exit with
# "invalid character ... after array element" instead of starting. printf cannot
# escape, so it must not be used to assemble JSON.
ADAPTERS_JSON=$(python3 -c '
import json, sys
document = [{
    "adapter_id": "mock-main",
    "provider_type": "genericcli",
    "command": sys.argv[1],
    "args": [
        "--session-dir", sys.argv[2],
        "--messages-body", sys.argv[3],
        "--messages-count", sys.argv[4],
    ],
    "timeout_ms": 10000,
}]
sys.stdout.write(json.dumps(document))
' "${PROVIDER_BIN}" "${RUN_DIR}/data" "${AGENT_CLUSTER_TEST_MESSAGES_BODY}" "${AGENT_CLUSTER_TEST_MESSAGES_COUNT:-1}")

# The Server owns the API and the channel listener. Its certificate is the one the
# Endpoint verifies, and the CA is the one both sides trust.
AGENT_CLUSTER_SERVER_API_LISTEN_ADDR="127.0.0.1:${API_PORT}" \
AGENT_CLUSTER_SERVER_CHANNEL_LISTEN_ADDR="127.0.0.1:${CHANNEL_PORT}" \
AGENT_CLUSTER_SERVER_AUTH_TOKEN="${AUTH_TOKEN}" \
AGENT_CLUSTER_TLS_CA_FILE="${CERT_DIR}/ca.pem" \
AGENT_CLUSTER_TLS_CERTIFICATE_FILE="${CERT_DIR}/server.pem" \
AGENT_CLUSTER_TLS_KEY_FILE="${CERT_DIR}/server-key.pem" \
AGENT_CLUSTER_DATABASE_PATH="${RUN_DIR}/data/server.sqlite" \
AGENT_CLUSTER_LOG_OUTPUT=stderr \
    "${SERVER_BIN}" >"${RUN_DIR}/logs/server.log" 2>&1 &
server_pid=$!
echo "${server_pid}" >"${RUN_DIR}/pids/server.pid"

# Wait for the API to answer before starting the Endpoint, so an Endpoint dial
# failure cannot be confused with a Server that never came up.
ready=0
for _ in $(seq 1 50); do
    if curl -fsS -H "Authorization: Bearer ${AUTH_TOKEN}" \
        "http://127.0.0.1:${API_PORT}/api/v1/endpoints" >/dev/null 2>&1; then
        ready=1
        break
    fi
    if ! kill -0 "${server_pid}" 2>/dev/null; then
        die "server exited during startup; see ${RUN_DIR}/logs/server.log"
    fi
    sleep 0.2
done
[ "${ready}" -eq 1 ] || die "server did not become ready; see ${RUN_DIR}/logs/server.log"

# The Endpoint dials the Server. Its identity must match the certificate subject,
# otherwise the mTLS handshake fails and the Endpoint looks like a network fault.
AGENT_CLUSTER_ENDPOINT_ID="${ENDPOINT_ID}" \
AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESS="wss://127.0.0.1:${CHANNEL_PORT}" \
AGENT_CLUSTER_TLS_CA_FILE="${CERT_DIR}/ca.pem" \
AGENT_CLUSTER_TLS_CERTIFICATE_FILE="${CERT_DIR}/client.pem" \
AGENT_CLUSTER_TLS_KEY_FILE="${CERT_DIR}/client-key.pem" \
AGENT_CLUSTER_DATABASE_PATH="${RUN_DIR}/data/endpoint.sqlite" \
AGENT_CLUSTER_ENDPOINT_ADAPTERS="${ADAPTERS_JSON}" \
AGENT_CLUSTER_LOG_OUTPUT=stderr \
    "${ENDPOINT_BIN}" >"${RUN_DIR}/logs/endpoint.log" 2>&1 &
endpoint_pid=$!
echo "${endpoint_pid}" >"${RUN_DIR}/pids/endpoint.pid"

# Wait for the Endpoint to register, so a command sent immediately after this
# script returns cannot race the registration.
registered=0
for _ in $(seq 1 50); do
    if curl -fsS -H "Authorization: Bearer ${AUTH_TOKEN}" \
        "http://127.0.0.1:${API_PORT}/api/v1/endpoints" 2>/dev/null | grep -q "${ENDPOINT_ID}"; then
        registered=1
        break
    fi
    if ! kill -0 "${endpoint_pid}" 2>/dev/null; then
        die "endpoint exited during startup; see ${RUN_DIR}/logs/endpoint.log"
    fi
    sleep 0.2
done
[ "${registered}" -eq 1 ] || die "endpoint did not register; see ${RUN_DIR}/logs/endpoint.log"

echo "server pid ${server_pid} api 127.0.0.1:${API_PORT}"
echo "endpoint pid ${endpoint_pid} id ${ENDPOINT_ID} channel 127.0.0.1:${CHANNEL_PORT}"
echo "run dir ${RUN_DIR}"
