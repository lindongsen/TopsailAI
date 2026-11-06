#!/bin/bash
# Author: DawsonLin
# Purpose: Start, stop and inspect the local Agent Cluster server and endpoint.
#
# The Go binaries read process environment variables only; they never parse .env.
# This script clears inherited AGENT_CLUSTER_* variables, sources the shared
# workspace .env, then supplies the role-specific values as explicit command-line
# flags because the server and the endpoint need different database paths and
# different TLS leaf certificates.
#
# Joint verbs act on both roles; the role-scoped verbs act on one role only.

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

# Validates the prerequisites shared by both roles.
function preflight_common() {
    load_shared_env
    [ -f "${CERTS_DIR}/ca.pem" ] || die "missing ${CERTS_DIR}/ca.pem"
}

# Validates the executable of one role so a missing binary fails before any start.
function preflight_role() {
    local name="$1"
    case "${name}" in
        server) [ -x "${SERVER_BIN}" ] || die "missing ${SERVER_BIN}; build it first" ;;
        endpoint) [ -x "${ENDPOINT_BIN}" ] || die "missing ${ENDPOINT_BIN}; build it first" ;;
        *) die "unknown role ${name}" ;;
    esac
}

# Starts one role with the flags that role requires.
function start_named() {
    local name="$1"
    case "${name}" in
        server)
            start_role server \
                "${SERVER_BIN}" \
                --database-path "${RUN_DIR}/server.sqlite" \
                --tls-certificate-file "${CERTS_DIR}/server.pem" \
                --tls-key-file "${CERTS_DIR}/server-key.pem" \
                --log-path "${LOGS_DIR}/server.log"
            ;;
        endpoint)
            start_role endpoint \
                "${ENDPOINT_BIN}" \
                --database-path "${RUN_DIR}/endpoint.sqlite" \
                --tls-certificate-file "${CERTS_DIR}/client.pem" \
                --tls-key-file "${CERTS_DIR}/client-key.pem" \
                --log-path "${LOGS_DIR}/endpoint.log"
            ;;
        *) die "unknown role ${name}" ;;
    esac
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
    preflight_role server
    preflight_role endpoint

    start_named server
    start_named endpoint

    echo ""
    echo "API      : ${AGENT_CLUSTER_API_LISTEN_ADDR}"
    echo "Channel  : ${AGENT_CLUSTER_CHANNEL_LISTEN_ADDR}"
    echo "Token    : ${AGENT_CLUSTER_AUTH_TOKEN}"
    echo "Endpoint : ${AGENT_CLUSTER_ENDPOINT_ID}"
    echo ""
    echo "Try: topsailai_agent_cluster list"
}

function stop_all() {
    local name
    for name in endpoint server; do
        stop_named "${name}"
    done
}

function status_all() {
    local name
    for name in server endpoint; do
        status_named "${name}"
    done
}

USAGE="usage: $0 {start|stop|restart|status|start-server|stop-server|restart-server|start-endpoint|stop-endpoint|restart-endpoint|status-server|status-endpoint}"

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
    *) die "${USAGE}" ;;
esac
