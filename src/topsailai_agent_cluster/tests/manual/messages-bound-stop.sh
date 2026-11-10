#!/bin/bash
# Author: DawsonLin
# Purpose: Stop the isolated Agent Cluster started by messages-bound-start.sh.
#
# It stops only the exact PIDs recorded by the launcher, in reverse start order, so
# a consumer leaves before a producer. It never matches processes by name: a pattern
# such as `pgrep -f 28080` also matches the shell running the cleanup, which once
# terminated the cleanup itself.
#
# It also reports whether anything survived, because a teardown that claims success
# without checking is the same defect as a test that claims a pass without running.

set -uo pipefail

PROJECT_DIR=/TopsailAI/src/topsailai_agent_cluster
RUN_DIR="${PROJECT_DIR}/.tmp/msgbound"
PID_DIR="${RUN_DIR}/pids"

function stop_role() {
    local name="$1"
    local pid_file="${PID_DIR}/${name}.pid"
    if [ ! -f "${pid_file}" ]; then
        echo "${name}: no pid file, nothing to stop"
        return 0
    fi
    local pid
    pid=$(cat "${pid_file}" 2>/dev/null)
    if [ -z "${pid}" ]; then
        echo "${name}: empty pid file, removing it"
        rm -f "${pid_file}"
        return 0
    fi
    if ! kill -0 "${pid}" 2>/dev/null; then
        echo "${name}: pid ${pid} already gone"
        rm -f "${pid_file}"
        return 0
    fi
    echo "${name}: stopping pid ${pid}"
    kill "${pid}" 2>/dev/null
    for _ in $(seq 1 25); do
        if ! kill -0 "${pid}" 2>/dev/null; then
            echo "${name}: pid ${pid} exited"
            rm -f "${pid_file}"
            return 0
        fi
        sleep 0.2
    done
    echo "${name}: pid ${pid} did not exit, sending SIGKILL"
    kill -9 "${pid}" 2>/dev/null
    rm -f "${pid_file}"
}

# Reverse start order: the Endpoint dials the Server, so it leaves first.
stop_role endpoint
stop_role server

# Report survivors by exact pid file contents, not by a name pattern.
survivors=0
for pid_file in "${PID_DIR}"/*.pid; do
    [ -f "${pid_file}" ] || continue
    pid=$(cat "${pid_file}" 2>/dev/null)
    if [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null; then
        echo "SURVIVOR: ${pid_file} pid ${pid}"
        survivors=$((survivors + 1))
    fi
done

if [ "${survivors}" -eq 0 ]; then
    echo "no isolated survivors"
else
    echo "${survivors} isolated survivors remain"
    exit 1
fi
