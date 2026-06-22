#!/usr/bin/env bash
# Integration test service manager for ACS.
# Builds the ACS server, starts it with PostgreSQL and the agent-command directory
# in PATH, runs pytest, then stops the server.
set -euo pipefail

PROJECT_ROOT="/TopsailAI/src/topsailai_server/agent_community"
SERVER_BIN="${PROJECT_ROOT}/bin/acs-server"
AGENT_CMD_DIR="${PROJECT_ROOT}/scripts/topsailai_agent_cmd"
TEST_HOST="127.0.0.1"
TEST_PORT="7370"
READY_URL="http://${TEST_HOST}:${TEST_PORT}/readyz"
SERVER_PID=""
SERVER_LOG="${PROJECT_ROOT}/tests/integration/.tmp/acs-server.log"

log() {
    echo "[manage_test_server] $*"
}

cleanup() {
    if [[ -n "${SERVER_PID:-}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
        log "Stopping ACS server (PID ${SERVER_PID})..."
        kill "${SERVER_PID}" 2>/dev/null || true
        wait "${SERVER_PID}" 2>/dev/null || true
    fi
}

trap cleanup EXIT

stop_existing_server() {
    local pid
    pid="$(lsof -ti tcp:"${TEST_PORT}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]]; then
        log "Found existing server on port ${TEST_PORT} (PID ${pid}); stopping it..."
        kill "${pid}" 2>/dev/null || true
        local waited=0
        while kill -0 "${pid}" 2>/dev/null && [[ ${waited} -lt 10 ]]; do
            sleep 1
            waited=$((waited + 1))
        done
        if kill -0 "${pid}" 2>/dev/null; then
            log "Warning: could not gracefully stop existing server PID ${pid}"
        fi
    fi
}

build_server() {
    log "Building ACS server..."
    cd "${PROJECT_ROOT}"
    make build-server
}

start_server() {
    log "Starting ACS server for integration tests..."
    export PATH="${AGENT_CMD_DIR}:${PATH}"
    export ACS_HTTP_PORT="${TEST_PORT}"
    export ACS_DATABASE_DRIVER="postgres"
    export ACS_DB_HOST="localhost"
    export ACS_DB_PORT="5432"
    export ACS_DB_NAME="acs"
    export ACS_DB_USER="acs"
    export ACS_DB_PASSWORD="acs"
    export ACS_DB_SSL_MODE="disable"
    export ACS_NATS_SERVERS="nats://localhost:4222"
    export ACS_NATS_STREAM_GROUP="acs_group"
    export ACS_NATS_SUBJECT_GROUP_PENDING_MESSAGE_PREFIX="acs.group.pending-message"
    export ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX="acs.group.message"
    export ACS_LOG_LEVEL="info"

    mkdir -p "$(dirname "${SERVER_LOG}")"
    cd "${PROJECT_ROOT}"
    "${SERVER_BIN}" --daemon-internal >"${SERVER_LOG}" 2>&1 &
    SERVER_PID=$!
    log "ACS server started with PID ${SERVER_PID}, logs: ${SERVER_LOG}"
}

wait_for_ready() {
    log "Waiting for ACS server to be ready..."
    local waited=0
    while [[ ${waited} -lt 60 ]]; do
        if curl -fsS "${READY_URL}" >/dev/null 2>&1; then
            log "ACS server is ready."
            return 0
        fi
        if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
            log "ACS server exited unexpectedly. See ${SERVER_LOG}"
            return 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
    log "ACS server did not become ready within timeout. See ${SERVER_LOG}"
    return 1
}

main() {
    stop_existing_server
    build_server
    start_server
    wait_for_ready
    log "Running integration tests..."
    uv run pytest --color=no "$@"
}

main "$@"
