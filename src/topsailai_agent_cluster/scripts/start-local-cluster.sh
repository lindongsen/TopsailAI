#!/bin/bash
# Author: DawsonLin
# Purpose: Drive the local Agent Cluster topology from the workspace.
#
# Every role is delegated to a portable node bundle driven by agent-clusterctl, so
# this script holds no role logic of its own: it only knows where each bundle
# lives and in which order the roles come up. A bundle carries the controller,
# the binaries and the configuration, which is what makes it movable to a node.
#
# Topology:
#   server    local bundle, the cluster server
#   endpoint  local bundle, the local-endpoint endpoint
#   relay     socat hops publishing the channel and API ports on the docker
#             bridge gateway, so a container CLI can reach the Server
#   ai-dev    endpoint bundle inside the ai-dev container, dialled through relay
#
# Joint verbs act on every role; the role-scoped verbs act on one role only.

set -uo pipefail

PROJECT_DIR=/TopsailAI/src/topsailai_agent_cluster
LOCAL_BUNDLE="${PROJECT_DIR}/.tmp/local-cluster"
CONTROL_MASTER="${PROJECT_DIR}/scripts/agent-clusterctl"
CONTROL="${LOCAL_BUNDLE}/agent-clusterctl"

CONTAINER_NAME=ai-dev
CONTAINER_BUNDLE_GUEST=/opt/git/ai/lindongsen/work/hosts/ai-dev/agent-cluster.new
BRIDGE_ADDRESS=172.18.0.1
RELAY_PORT=53943
API_RELAY_PORT=53680
RELAY_PID_DIR="${LOCAL_BUNDLE}/pids"

# Start order; stop order is the reverse so consumers leave before producers.
START_ORDER=(server endpoint relay ai-dev)

function die() {
    echo "ERROR: $*" >&2
    exit 1
}

# Copies the controller into the bundle so the bundle stays self-contained.
function ensure_control() {
    [ -d "${LOCAL_BUNDLE}" ] || die "missing bundle ${LOCAL_BUNDLE}"
    if ! cmp -s "${CONTROL_MASTER}" "${CONTROL}"; then
        cp "${CONTROL_MASTER}" "${CONTROL}"
        chmod +x "${CONTROL}"
    fi
}

# Runs the portable controller against the local bundle for one role.
function local_ctl() {
    local role="$1"
    shift
    ensure_control
    "${CONTROL}" -c "${LOCAL_BUNDLE}/conf/${role}.conf" "$@"
}

# Reports the pid of a live relay hop for one published port.
function relay_pid_of() {
    local pid_file="${RELAY_PID_DIR}/relay-$1.pid"
    [ -f "${pid_file}" ] || return 1
    local pid
    pid=$(cat "${pid_file}" 2>/dev/null)
    [ -n "${pid}" ] || return 1
    kill -0 "${pid}" 2>/dev/null || return 1
    echo "${pid}"
}

# Publishes one loopback port on the bridge gateway so a container can dial it.
function start_relay_port() {
    local port="$1"
    local pid_file="${RELAY_PID_DIR}/relay-${port}.pid"
    if pid=$(relay_pid_of "${port}"); then
        echo "relay ${port} already running with pid ${pid}"
        return 0
    fi
    mkdir -p "${RELAY_PID_DIR}"
    nohup socat "TCP-LISTEN:${port},bind=${BRIDGE_ADDRESS},fork,reuseaddr" \
        "TCP:127.0.0.1:${port}" \
        >>"${LOCAL_BUNDLE}/logs/relay.stdout.log" 2>&1 &
    local pid=$!
    echo "${pid}" >"${pid_file}"
    sleep 1
    if ! kill -0 "${pid}" 2>/dev/null; then
        rm -f "${pid_file}"
        echo "relay ${port} failed to start; see ${LOCAL_BUNDLE}/logs/relay.stdout.log" >&2
        return 1
    fi
    echo "started relay ${port} with pid ${pid}"
}

# Stops one relay hop.
function stop_relay_port() {
    local port="$1"
    local pid_file="${RELAY_PID_DIR}/relay-${port}.pid"
    local pid
    if pid=$(relay_pid_of "${port}"); then
        echo "stopping relay ${port} pid ${pid}"
        kill "${pid}" 2>/dev/null
    else
        echo "relay ${port} is not running"
    fi
    rm -f "${pid_file}"
}

# Reports whether one relay hop is running.
function status_relay_port() {
    local port="$1"
    local pid
    if pid=$(relay_pid_of "${port}"); then
        echo "relay ${port}: running pid ${pid} on ${BRIDGE_ADDRESS}:${port}"
    else
        echo "relay ${port}: stopped"
    fi
}

# Publishes both the channel port and the Server API port. The channel carries
# endpoint traffic; the API port is what an installed CLI dials from a container.
function start_relay() {
    start_relay_port "${RELAY_PORT}" || return 1
    start_relay_port "${API_RELAY_PORT}" || return 1
}

# Stops both relay hops.
function stop_relay() {
    stop_relay_port "${API_RELAY_PORT}"
    stop_relay_port "${RELAY_PORT}"
}

# Reports both relay hops.
function status_relay() {
    status_relay_port "${RELAY_PORT}"
    status_relay_port "${API_RELAY_PORT}"
}

# Runs the portable controller inside the ai-dev container for its endpoint role.
# The container bundle carries the same controller, binary and config as a local
# bundle, so the launcher only has to enter the container and delegate.
function container_ctl() {
    docker exec "${CONTAINER_NAME}" bash -c \
        "cd '${CONTAINER_BUNDLE_GUEST}' && ./agent-clusterctl -c conf/node.conf $*" ||
        die "cannot run agent-clusterctl inside ${CONTAINER_NAME}"
}

# Starts the endpoint bundle that lives inside the ai-dev container.
function start_container_endpoint() {
    container_ctl start
}

# Stops the endpoint running inside the ai-dev container.
function stop_container_endpoint() {
    container_ctl stop
}

# Reports whether the endpoint inside the ai-dev container is running. The
# controller reports the role name it was configured with, so the launcher
# prefixes each line with the container name to keep the two endpoints distinct.
function status_container_endpoint() {
    container_ctl status | sed 's/^/ai-dev /'
}

# Installs the container bundle into system paths: the endpoint binary, the CLI
# as /usr/local/sbin/topsailai_agent_cluster, and the per-user CLI env file that
# points the CLI at the Server API. Re-running with identical configuration is a
# no-op, so this is safe after a bundle refresh.
function install_container_node() {
    docker exec "${CONTAINER_NAME}" bash -c \
        "cd '${CONTAINER_BUNDLE_GUEST}' && ./install-node.sh" ||
        die "cannot install the node bundle inside ${CONTAINER_NAME}"
}

# Brings up every role in dependency order.
function start_all() {
    local role
    for role in "${START_ORDER[@]}"; do
        case "${role}" in
            server | endpoint) local_ctl "${role}" start ;;
            relay) start_relay ;;
            ai-dev) start_container_endpoint ;;
        esac
    done
    echo ""
    echo "Try: topsailai_agent_cluster list"
}

# Tears every role down in reverse dependency order.
function stop_all() {
    local index role
    for ((index = ${#START_ORDER[@]} - 1; index >= 0; index--)); do
        role="${START_ORDER[index]}"
        case "${role}" in
            server | endpoint) local_ctl "${role}" stop ;;
            relay) stop_relay ;;
            ai-dev) stop_container_endpoint ;;
        esac
    done
}

# Reports every role.
function status_all() {
    local role
    for role in "${START_ORDER[@]}"; do
        case "${role}" in
            server | endpoint) local_ctl "${role}" status ;;
            relay) status_relay ;;
            ai-dev) status_container_endpoint ;;
        esac
    done
}

USAGE="usage: $0 {start|stop|restart|status|install-ai-dev|start-server|stop-server|restart-server|status-server|start-endpoint|stop-endpoint|restart-endpoint|status-endpoint|start-relay|stop-relay|status-relay|start-ai-dev|stop-ai-dev|restart-ai-dev|status-ai-dev}"

case "${1:-start}" in
    start) start_all ;;
    stop) stop_all ;;
    restart) stop_all; start_all ;;
    status) status_all ;;
    start-server) local_ctl server start ;;
    stop-server) local_ctl server stop ;;
    restart-server) local_ctl server restart ;;
    status-server) local_ctl server status ;;
    start-endpoint) local_ctl endpoint start ;;
    stop-endpoint) local_ctl endpoint stop ;;
    restart-endpoint) local_ctl endpoint restart ;;
    status-endpoint) local_ctl endpoint status ;;
    start-relay) start_relay ;;
    stop-relay) stop_relay ;;
    status-relay) status_relay ;;
    install-ai-dev) install_container_node ;;
    start-ai-dev) start_relay; start_container_endpoint ;;
    stop-ai-dev) stop_container_endpoint ;;
    restart-ai-dev) stop_container_endpoint; start_relay; start_container_endpoint ;;
    status-ai-dev) status_container_endpoint ;;
    *) die "${USAGE}" ;;
esac
