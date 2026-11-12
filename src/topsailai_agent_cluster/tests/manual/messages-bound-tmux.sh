#!/bin/bash
# Author: DawsonLin
# Purpose: Drive the messages display-bound cases against an isolated cluster in tmux.
#
# Lifecycle is delegated to messages-bound-start.sh and messages-bound-stop.sh, so
# this script only interacts and asserts. A startup failure is therefore reported as
# a startup failure rather than as a failed assertion.
#
# The command is run inside tmux rather than through a pipe, because the operator
# reads a terminal. A piped capture is not a TTY, so it cannot prove the form an
# operator actually sees; the human requirement is explicitly to run the built binary
# in tmux and send the command there.
#
# Each case restarts the cluster because the fixture body is read from the Endpoint
# process environment at startup. A body cannot be changed for a running Endpoint,
# and reusing one Endpoint for two bodies would silently test the first body twice.
#
# The CLI is pointed at the isolated Server through the process environment, which
# outranks bin/.env.local. That file points at the live relay port, so a run without
# these overrides would send the command to the live deployment.

set -uo pipefail

PROJECT_DIR=/TopsailAI/src/topsailai_agent_cluster
RUN_DIR="${PROJECT_DIR}/.tmp/msgbound"
LOG_DIR="${RUN_DIR}/logs"
CLI_BIN="${PROJECT_DIR}/bin/agent-cluster-cli"
START_SCRIPT="${PROJECT_DIR}/tests/manual/messages-bound-start.sh"
STOP_SCRIPT="${PROJECT_DIR}/tests/manual/messages-bound-stop.sh"

API_PORT=28080
AUTH_TOKEN=msgbound-token
# The Endpoint identity must equal the client certificate subject, because the
# Server verifies the certificate name during the mTLS handshake. The generator
# issues the client certificate with the DNS SAN endpoint-1, so any other value
# fails the handshake and the command reports an offline Endpoint.
ENDPOINT_ID=endpoint-1
SESSION_ID=fixture-session
TMUX_SESSION=msgbound

DICT_BODY='{"alpha":"first value","beta":{"nested":"inner value"},"gamma":["one","two"]}'
LIST_BODY='[{"name":"first item","state":"ready"},{"name":"second item","state":"waiting"}]'

failures=0
cases=0

function fail() {
    echo "FAIL: $*"
    failures=$((failures + 1))
}

# Runs one case: start the cluster with the given body, run the command in tmux,
# capture the pane, then assert the required and forbidden fragments.
function run_case() {
    local name="$1"
    local body="$2"
    local extra="$3"
    local must_show="$4"
    local must_not_show="$5"

    cases=$((cases + 1))
    echo ""
    echo "=== case ${cases}: ${name} ==="

    "${STOP_SCRIPT}" >/dev/null 2>&1
    tmux kill-session -t "${TMUX_SESSION}" 2>/dev/null

    if ! AGENT_CLUSTER_TEST_MESSAGES_BODY="${body}" AGENT_CLUSTER_TEST_MESSAGES_COUNT=1 \
        "${START_SCRIPT}" >"${LOG_DIR}/case${cases}-start.log" 2>&1; then
        fail "${name}: cluster did not start; see ${LOG_DIR}/case${cases}-start.log"
        return
    fi

    # The command is typed into a real terminal, so the captured pane is the form an
    # operator sees. The environment is exported inside the session for the same
    # reason the launcher exports it: the CLI reads it at its own process boundary.
    tmux new-session -d -s "${TMUX_SESSION}" -x 200 -y 50
    tmux send-keys -t "${TMUX_SESSION}" \
        "export AGENT_CLUSTER_CLI_SERVER_URL=http://127.0.0.1:${API_PORT}" C-m
    tmux send-keys -t "${TMUX_SESSION}" \
        "export AGENT_CLUSTER_CLI_SERVER_TOKEN=${AUTH_TOKEN}" C-m
    tmux send-keys -t "${TMUX_SESSION}" \
        "${CLI_BIN} messages ${ENDPOINT_ID} ${SESSION_ID} ${extra}; echo EXIT=\$?" C-m

    # Wait for the command to finish rather than sleeping a fixed time, so a slow
    # provider read is not mistaken for a missing marker.
    #
    # The pattern is anchored to the start of a line because the typed command line
    # itself contains "echo EXIT=$?", so an unanchored match is satisfied by the
    # command that was just sent and the loop exits before any output exists. The
    # real marker is printed by the shell at column zero.
    local waited=0
    while [ "${waited}" -lt 150 ]; do
        if tmux capture-pane -p -t "${TMUX_SESSION}" 2>/dev/null | grep -q '^EXIT='; then
            break
        fi
        sleep 0.2
        waited=$((waited + 1))
    done

    local out="${LOG_DIR}/case${cases}.txt"
    tmux capture-pane -p -t "${TMUX_SESSION}" >"${out}" 2>&1
    tmux kill-session -t "${TMUX_SESSION}" 2>/dev/null

    if ! grep -q '^EXIT=0' "${out}"; then
        fail "${name}: command did not exit 0; see ${out}"
        return
    fi

    # Fragments are separated by "|" rather than by whitespace, because a required
    # fragment such as "alpha: first value" contains spaces. Word splitting would
    # turn it into three independent greps, so a body that showed only "alpha:"
    # would satisfy the assertion.
    local fragment
    local saved_ifs="${IFS}"
    IFS='|'
    for fragment in ${must_show}; do
        if ! grep -qF -- "${fragment}" "${out}"; then
            fail "${name}: output is missing ${fragment}; see ${out}"
        fi
    done
    for fragment in ${must_not_show}; do
        if grep -qF -- "${fragment}" "${out}"; then
            fail "${name}: output contains forbidden ${fragment}; see ${out}"
        fi
    done
    IFS="${saved_ifs}"
    echo "captured ${out}"
}

# The unbounded cases prove the renderer itself, so a bounded failure cannot be
# blamed on the renderer being broken for that body shape.
# Fragments are "|"-separated because a fragment such as "alpha: first value"
# contains spaces. The unbounded cases assert the full rendered shape, so a
# renderer that dropped a nested block cannot pass on the first key alone.
# A bounded case must assert that the body WAS shortened, not merely that a key
# survived. Asserting only "alpha:" is satisfied by an unbounded body too, so a
# disabled bound would pass; that vacuous pass was observed and is why every
# bounded case now requires the truncation trailer and forbids the full body.
SHORTENED="one or more message bodies were shortened to the requested bound"

run_case "dict unbounded" "${DICT_BODY}" "" \
    "alpha: first value|beta:|nested: inner value|gamma:" \
    '{"|shortened to the requested bound'
run_case "dict token bound" "${DICT_BODY}" "--max-tokens 3" \
    "alpha: first...|${SHORTENED}" \
    '{"|alpha: first value'
run_case "dict char bound" "${DICT_BODY}" "--max-chars 20" \
    "alpha: first value|b...|${SHORTENED}" \
    '{"'
run_case "list unbounded" "${LIST_BODY}" "" \
    "[1]|name: first item|state: ready|[2]" \
    '[{|shortened to the requested bound'
run_case "list token bound" "${LIST_BODY}" "--max-tokens 5" \
    "[1]|name...|${SHORTENED}" \
    '[{|name: first item'
run_case "list char bound" "${LIST_BODY}" "--max-chars 20" \
    "[1]|name: first it...|${SHORTENED}" \
    '[{'

echo ""
echo "=== summary: ${cases} cases, ${failures} failures ==="
"${STOP_SCRIPT}"
if [ "${failures}" -ne 0 ]; then
    exit 1
fi
