#!/bin/bash
# Author: DawsonLin
# Purpose: Start, stop and inspect the local Agent Cluster server and endpoints.
#
# The Go binaries read process environment variables only; they never parse .env.
# This script clears inherited AGENT_CLUSTER_* variables, sources the shared
# workspace .env, then supplies the role-specific values as explicit command-line
# flags because the server and each endpoint need different database paths and
# different TLS leaf certificates.
#
# Roles:
#   server    the cluster server
#   endpoint  the local-endpoint endpoint
#   ai-dev    the ai-dev endpoint
#
# Joint verbs act on every role; the role-scoped verbs act on one role only.

set -uo pipefail

PROJECT_DIR=/TopsailAI/src/topsailai_agent_cluster
BIN_DIR="${PROJECT_DIR}/bin"
RUN_DIR="${PROJECT_DIR}/.tmp/local-cluster"
CERTS_DIR="${RUN_DIR}/certs"
LOGS_DIR="${RUN_DIR}/logs"
PIDS_DIR="${RUN_DIR}/pids"
SERVER_BIN="${BIN_DIR}/agent-cluster-server"
ENDPOINT_BIN="${BIN_DIR}/agent-cluster-endpoint"
SHARED_ENV="${PROJECT_DIR}/.env"

# Start order; stop order is the reverse so consumers leave before producers.
START_ORDER=(server endpoint ai-dev)

mkdir -p "${LOGS_DIR}" "${PIDS_DIR}"

function die() {
    echo "ERROR: $*" >&2
    exit 1
}

function load_shared_env() {
    [ -f "${SHARED_ENV}" ] || die "missing shared configuration ${SHARED_ENV}"
    # Inherited values would shadow the file, so clear them first.
    while IFS='=' read -r key _; do
        case "${key}" in
            AGENT_CLUSTER_*) unset "${key}" ;;
        esac
    done < <(env)
    set -a
    # shellcheck disable=SC1090
    . "${SHARED_ENV}"
    set +a
}

# Reports the executable serving a role.
function role_binary() {
    case "$1" in
        server) echo "${SERVER_BIN}" ;;
        endpoint | ai-dev) echo "${ENDPOINT_BIN}" ;;
        *) return 1 ;;
    esac
}

# Reports the TLS leaf certificate identifying a role.
function role_cert() {
    case "$1" in
        server) echo "${CERTS_DIR}/server.pem" ;;
        endpoint) echo "${CERTS_DIR}/client.pem" ;;
        ai-dev) echo "${CERTS_DIR}/endpoint-ai-dev.pem" ;;
        *) return 1 ;;
    esac
}

# Reports the TLS private key paired with role_cert.
function role_key() {
    case "$1" in
        server) echo "${CERTS_DIR}/server-key.pem" ;;
        endpoint) echo "${CERTS_DIR}/client-key.pem" ;;
        ai-dev) echo "${CERTS_DIR}/endpoint-ai-dev-key.pem" ;;
        *) return 1 ;;
    esac
}

# Reports the SQLite database owned by a role.
function role_db() {
    case "$1" in
        server) echo "${RUN_DIR}/server.sqlite" ;;
        endpoint) echo "${RUN_DIR}/endpoint.sqlite" ;;
        ai-dev) echo "${RUN_DIR}/endpoint-ai-dev.sqlite" ;;
        *) return 1 ;;
    esac
}

# Reports the endpoint identity a role announces; the certificate CN must match it.
function role_endpoint_id() {
    case "$1" in
        endpoint) echo "local-endpoint" ;;
        ai-dev) echo "ai-dev" ;;
        *) return 1 ;;
    esac
}

# Reports the endpoint instance identity a role announces.
function role_instance_id() {
    case "$1" in
        endpoint) echo "local-endpoint-1" ;;
        ai-dev) echo "ai-dev-1" ;;
        *) return 1 ;;
    esac
}

function pid_of() {
    local name="$1"
    local file="${PIDS_DIR}/${name}.pid"
    [ -f "${file}" ] || return 1
    local pid
    pid=$(cat "${file}")
    [ -n "${pid}" ] || return 1
    kill -0 "${pid}" 2>/dev/null || return 1
    echo "${pid}"
}

function start_role() {
    local name="$1"
    shift
    if pid=$(pid_of "${name}"); then
        echo "${name} already running with pid ${pid}"
        return 0
    fi
    "$@" >>"${LOGS_DIR}/${name}.stdout.log" 2>&1 &
    local pid=$!
    echo "${pid}" >"${PIDS_DIR}/${name}.pid"
    echo "started ${name} with pid ${pid}"
}

# Validates the prerequisites shared by every role.
function preflight_common() {
    load_shared_env
    [ -f "${CERTS_DIR}/ca.pem" ] || die "missing ${CERTS_DIR}/ca.pem"
}

# Validates one role so a missing artefact fails before any process starts.
function preflight_role() {
    local name="$1"
    local binary cert key
    binary=$(role_binary "${name}") || die "unknown role ${name}"
    cert=$(role_cert "${name}") || die "unknown role ${name}"
    key=$(role_key "${name}") || die "unknown role ${name}"
    [ -x "${binary}" ] || die "missing ${binary}; build it first"
    [ -f "${cert}" ] || die "missing ${cert}"
    [ -f "${key}" ] || die "missing ${key}"
}

# Starts one role with the flags that role requires.
function start_named() {
    local name="$1"
    local binary cert key db
    binary=$(role_binary "${name}") || die "unknown role ${name}"
    cert=$(role_cert "${name}") || die "unknown role ${name}"
    key=$(role_key "${name}") || die "unknown role ${name}"
    db=$(role_db "${name}") || die "unknown role ${name}"
    if [ "${name}" = "server" ]; then
        start_role server \
            "${binary}" \
            --database-path "${db}" \
            --tls-certificate-file "${cert}" \
            --tls-key-file "${key}" \
            --log-path "${LOGS_DIR}/server.log"
        return 0
    fi
    start_role "${name}" \
        "${binary}" \
        --database-path "${db}" \
        --endpoint-id "$(role_endpoint_id "${name}")" \
        --instance-id "$(role_instance_id "${name}")" \
        --tls-certificate-file "${cert}" \
        --tls-key-file "${key}" \
        --log-path "${LOGS_DIR}/${name}.log"
}

# Stops one role, escalating to SIGKILL only when graceful termination stalls.
function stop_named() {
    local name="$1"
    local pid
    if pid=$(pid_of "${name}"); then
        echo "stopping ${name} pid ${pid}"
        kill "${pid}" 2>/dev/null
        for _ in $(seq 1 50); do
            kill -0 "${pid}" 2>/dev/null || break
            sleep 0.1
        done
        if kill -0 "${pid}" 2>/dev/null; then
            echo "forcing ${name} pid ${pid}"
            kill -9 "${pid}" 2>/dev/null
        fi
    else
        echo "${name} is not running"
    fi
    rm -f "${PIDS_DIR}/${name}.pid"
}

function status_named() {
    local name="$1"
    local pid
    if pid=$(pid_of "${name}"); then
        echo "${name}: running pid ${pid}"
    else
        echo "${name}: stopped"
    fi
}

function start_all() {
    preflight_common
    local name
    for name in "${START_ORDER[@]}"; do
        preflight_role "${name}"
    done
    for name in "${START_ORDER[@]}"; do
        start_named "${name}"
    done

    echo ""
    echo "API      : ${AGENT_CLUSTER_API_LISTEN_ADDR}"
    echo "Channel  : ${AGENT_CLUSTER_CHANNEL_LISTEN_ADDR}"
    echo "Token    : ${AGENT_CLUSTER_AUTH_TOKEN}"
    echo "Endpoints: local-endpoint, ai-dev"
    echo ""
    echo "Try: topsailai_agent_cluster list"
}

function stop_all() {
    local index name
    for ((index = ${#START_ORDER[@]} - 1; index >= 0; index--)); do
        stop_named "${START_ORDER[index]}"
    done
}

function status_all() {
    local name
    for name in "${START_ORDER[@]}"; do
        status_named "${name}"
    done
}

USAGE="usage: $0 {start|stop|restart|status|start-server|stop-server|restart-server|status-server|start-endpoint|stop-endpoint|restart-endpoint|status-endpoint|start-relay|stop-relay|status-relay|start-ai-dev|stop-ai-dev|restart-ai-dev|status-ai-dev}"

case "${1:-start}" in
    start) start_all ;;
    stop) stop_all ;;
    restart) stop_all; start_all ;;
    status) status_all ;;
    start-server) preflight_common; preflight_role server; start_named server ;;
    stop-server) stop_named server ;;
    restart-server) stop_named server; preflight_common; preflight_role server; start_named server ;;
    start-endpoint) preflight_common; preflight_role endpoint; start_named endpoint ;;
    stop-endpoint) stop_named endpoint ;;
    restart-endpoint) stop_named endpoint; preflight_common; preflight_role endpoint; start_named endpoint ;;
    status-server) status_named server ;;
    status-endpoint) status_named endpoint ;;
    start-relay) preflight_common; start_relay ;;
    stop-relay) stop_relay ;;
    status-relay) status_relay ;;
    start-ai-dev) preflight_common; start_relay; start_container_endpoint ;;
    stop-ai-dev) stop_container_endpoint ;;
    restart-ai-dev) stop_container_endpoint; preflight_common; start_relay; start_container_endpoint ;;
    status-ai-dev) status_container_endpoint ;;
    *) die "${USAGE}" ;;
esac
