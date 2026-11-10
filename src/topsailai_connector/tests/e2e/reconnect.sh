#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Prove reconnect replacement, offline refusal and concurrent correlation
#          against two real processes over a real socket.
#
# This script starts its own pair of processes by calling start.sh, because the
# scenarios below stop and restart the Node and a run that inherited a pair from
# another script would depend on that script's cleanup order. It never launches the
# Server itself; it only stops and restarts the Node, because a reconnect cannot be
# observed without one.
#
# Three scenarios, in this order:
#   A. The Node dies. A request is refused with node_offline instead of hanging, and
#      the Node recovers when it comes back.
#   B. Concurrent reads of distinct files each answer with their own content, so a
#      response cannot be matched to the wrong request.
#   C. A second Node with the same identity replaces the first, and the first Node's
#      later exit does not evict its replacement.
#
# Scenario C runs last because it leaves no Node connected.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK="$ROOT/.tmp/e2e"
ENV_FILE="$WORK/env.sh"
BIN="$ROOT/bin"

SERVER_LOG="$WORK/server.log"
NODE_LOG="$WORK/node.log"
NODE2_LOG="$WORK/node2.log"
CONC_DIR="$WORK/conc"

READY_TIMEOUT=30
# A refusal must arrive well inside the CLI's own 45 second timeout. The budget is
# deliberately far below it, because a Server that waited for its timeout before
# answering would still pass a check that only asserted the code.
OFFLINE_BUDGET_MS=10000
CONCURRENT_FILES=8

fail() {
	echo "reconnect: $*" >&2
	exit 1
}

# now_ms prints the current time in milliseconds.
#
# python3 is used rather than `date +%s%3N`, because the latter is a GNU extension
# and this script must not depend on which date implementation is installed.
now_ms() {
	python3 -c 'import time; print(int(time.time() * 1000))'
}

# wait_for_log_count waits until a pattern has appeared at least `want` times.
#
# Counting rather than merely matching is what makes a second occurrence
# observable: a log that already contains one "channel established" would satisfy a
# plain match before the Node ever reconnected.
wait_for_log_count() {
	local file=$1 pattern=$2 want=$3
	local deadline=$((SECONDS + READY_TIMEOUT))
	local got
	while ((SECONDS < deadline)); do
		got=$(grep -c -- "$pattern" "$file" 2>/dev/null || true)
		if [ "${got:-0}" -ge "$want" ]; then
			return 0
		fi
		sleep 0.1
	done
	return 1
}

# count_log prints how many times a pattern appears, treating no match as zero.
count_log() {
	local file=$1 pattern=$2
	local got
	got=$(grep -c -- "$pattern" "$file" 2>/dev/null || true)
	echo "${got:-0}"
}

# stop_pid stops one process by exact PID and waits for it to exit.
#
# The PID is the one this run started, never a name, because a name match would also
# stop an unrelated process the operator happens to be running. A process that
# ignores the signal is reported rather than escalated to a broader kill.
stop_pid() {
	local pid=${1:-}
	[ -n "$pid" ] || return 0
	if kill -0 "$pid" 2>/dev/null; then
		kill "$pid" 2>/dev/null || true
	fi
	local deadline=$((SECONDS + 10))
	while kill -0 "$pid" 2>/dev/null && ((SECONDS < deadline)); do
		sleep 0.1
	done
	if kill -0 "$pid" 2>/dev/null; then
		fail "pid $pid did not exit within 10s"
	fi
	wait "$pid" 2>/dev/null || true
}

# stop_all stops every process this run owns. It is safe to call more than once, so
# the explicit call at the end of the body and the EXIT trap can both use it.
stop_all() {
	stop_pid "${NODE2_PID:-}"
	stop_pid "${NODE_PID:-}"
	stop_pid "${E2E_SERVER_PID:-}"
}

# record rewrites env.sh so a failure part way through still leaves the PIDs behind
# for whoever cleans up next.
record() {
	{
		echo "E2E_SERVER_PID=${E2E_SERVER_PID:-}"
		echo "E2E_NODE_PID=${NODE_PID:-}"
		echo "E2E_NODE2_PID=${NODE2_PID:-}"
		echo "E2E_BASE_URL=${E2E_BASE_URL:-}"
		echo "E2E_CHANNEL_URL=${E2E_CHANNEL_URL:-}"
		echo "E2E_CLIENT_TOKEN=${E2E_CLIENT_TOKEN:-}"
		echo "E2E_TUNNEL_TOKEN=${E2E_TUNNEL_TOKEN:-}"
		echo "E2E_WORK=${E2E_WORK:-}"
	} >"$ENV_FILE"
}

# start_node launches the Node against the recorded channel URL and appends to the
# Node log, so the history of every connection attempt stays readable.
start_node() {
	CONNECTOR_NODE_SERVER_URL="$E2E_CHANNEL_URL" \
		CONNECTOR_NODE_TUNNEL_TOKEN="$E2E_TUNNEL_TOKEN" \
		CONNECTOR_NODE_CONFIG_DIR="$E2E_WORK/node-config" \
		"$BIN/connector-node" run >>"$NODE_LOG" 2>&1 &
	NODE_PID=$!
	record
}

# start_node2 launches a second Node with the same config directory, which means the
# same identity. That is the only way to observe a replacement: one identity, two
# live connections, and the Server must keep exactly one.
start_node2() {
	CONNECTOR_NODE_SERVER_URL="$E2E_CHANNEL_URL" \
		CONNECTOR_NODE_TUNNEL_TOKEN="$E2E_TUNNEL_TOKEN" \
		CONNECTOR_NODE_CONFIG_DIR="$E2E_WORK/node-config" \
		"$BIN/connector-node" run >"$NODE2_LOG" 2>&1 &
	NODE2_PID=$!
	record
}

cli() {
	"$BIN/connector-server" cli \
		--server "$E2E_BASE_URL" \
		--client-token "$E2E_CLIENT_TOKEN" \
		--node "$PAIR" \
		"$@"
}

# check_read asserts that one file.read returns the exact bytes on disk.
check_read() {
	local got
	got=$(cli --scope project --path hello.txt file.read)
	if [ "$got" != "hello from the end-to-end test" ]; then
		fail "file.read returned $(printf '%q' "$got"), want the file content"
	fi
}

# wait_for_read retries a read until it succeeds or the budget runs out.
#
# Recovery is asserted through the operation itself rather than through a log line,
# because a Node that logged a handshake and then failed to serve would satisfy a
# log check and fail the user.
wait_for_read() {
	local deadline=$((SECONDS + READY_TIMEOUT))
	while ((SECONDS < deadline)); do
		if cli --scope project --path hello.txt file.read >/dev/null 2>&1; then
			return 0
		fi
		sleep 0.2
	done
	return 1
}

# scenario_offline kills the Node, asserts the refusal is explicit and prompt, then
# asserts the Node recovers.
scenario_offline() {
	echo "reconnect: scenario A: the node dies and a request is refused" >&2

	local closed_before
	closed_before=$(count_log "$SERVER_LOG" 'msg="channel closed"')

	stop_pid "$NODE_PID"
	NODE_PID=""
	record

	wait_for_log_count "$SERVER_LOG" 'msg="channel closed"' $((closed_before + 1)) ||
		fail "the Server did not report the closed channel; see $SERVER_LOG"
	echo "reconnect: the Server dropped the registration" >&2

	local start_ms end_ms elapsed out
	start_ms=$(now_ms)
	if out=$(cli --scope project --path hello.txt file.read 2>&1); then
		fail "a request to an offline node was served: $out"
	fi
	end_ms=$(now_ms)
	elapsed=$((end_ms - start_ms))

	case "$out" in
	*node_offline*) ;;
	*) fail "an offline request reported $(printf '%q' "$out"), want node_offline" ;;
	esac
	if [ "$elapsed" -ge "$OFFLINE_BUDGET_MS" ]; then
		fail "an offline request took ${elapsed}ms, want under ${OFFLINE_BUDGET_MS}ms"
	fi
	echo "reconnect: an offline request was refused with node_offline in ${elapsed}ms" >&2

	start_node
	wait_for_read || fail "the Node did not recover after restarting; see $NODE_LOG"
	echo "reconnect: the Node recovered and served a read again" >&2
}

# scenario_concurrent reads several distinct files at the same time and asserts each
# answer carries its own content.
#
# Distinct content is the whole point: if every file held the same bytes, a response
# delivered to the wrong caller would still match and the check would pass for the
# wrong reason.
scenario_concurrent() {
	echo "reconnect: scenario B: concurrent reads keep their own answers" >&2

	if [ -e "$CONC_DIR" ]; then
		echo "reconnect: removing the previous concurrency directory $CONC_DIR" >&2
		rm -rf "$CONC_DIR"
	fi
	mkdir -p "$CONC_DIR"

	local i
	for i in $(seq 0 $((CONCURRENT_FILES - 1))); do
		printf 'payload-%d-%08d' "$i" $((i * 7919)) >"$E2E_WORK/scope/conc-$i.txt"
	done

	local pids=()
	for i in $(seq 0 $((CONCURRENT_FILES - 1))); do
		cli --scope project --path "conc-$i.txt" file.read \
			>"$CONC_DIR/$i.out" 2>"$CONC_DIR/$i.err" &
		pids+=("$!")
	done

	local pid
	for pid in "${pids[@]}"; do
		if ! wait "$pid"; then
			fail "a concurrent read failed; see $CONC_DIR"
		fi
	done

	local expected got
	for i in $(seq 0 $((CONCURRENT_FILES - 1))); do
		expected=$(cat "$E2E_WORK/scope/conc-$i.txt")
		got=$(cat "$CONC_DIR/$i.out")
		if [ "$got" != "$expected" ]; then
			fail "concurrent read $i returned $(printf '%q' "$got"), want $(printf '%q' "$expected")"
		fi
	done
	echo "reconnect: ${CONCURRENT_FILES} concurrent reads each returned their own content" >&2
}

# scenario_replacement starts a second Node with the same identity and asserts the
# Server keeps exactly one connection for it.
scenario_replacement() {
	echo "reconnect: scenario C: a second node replaces the first" >&2

	local replaced_before
	replaced_before=$(count_log "$SERVER_LOG" 'msg="replacing a live connection for the same node"')

	start_node2
	wait_for_log_count "$SERVER_LOG" 'msg="replacing a live connection for the same node"' $((replaced_before + 1)) ||
		fail "the Server did not report a replacement; see $SERVER_LOG"
	echo "reconnect: the Server replaced the live connection" >&2

	# The first Node's connection was closed by the Server, and its dialer retries
	# after five seconds. It is stopped now so it cannot reconnect and start a
	# replacement loop that would make the next assertion ambiguous.
	stop_pid "$NODE_PID"
	NODE_PID=""
	record

	# The first Node's shutdown unregisters a stale generation. If that removal were
	# not generation checked it would evict the replacement, and the symptom would be
	# a Node that looks connected and answers node_offline.
	check_read
	echo "reconnect: the replacement still served after the first node exited" >&2

	stop_pid "$NODE2_PID"
	NODE2_PID=""
	record
}

# A fresh pair of processes is started here rather than inherited, so this script
# does not depend on another script's cleanup order.
echo "reconnect: starting a fresh pair of processes" >&2
bash "$ROOT/tests/e2e/start.sh"

[ -f "$ENV_FILE" ] || fail "$ENV_FILE is missing after start.sh"
# shellcheck source=/dev/null
. "$ENV_FILE"

[ -n "${E2E_SERVER_PID:-}" ] || fail "no Server PID recorded"
[ -n "${E2E_NODE_PID:-}" ] || fail "no Node PID recorded"

NODE_PID="$E2E_NODE_PID"
NODE2_PID=""
record

trap stop_all EXIT

IDENTITY_FILE="$E2E_WORK/node-config/identity"
[ -f "$IDENTITY_FILE" ] || fail "$IDENTITY_FILE is missing; the Node did not write an identity"
PAIR=$(tr -d '\r\n' <"$IDENTITY_FILE")
[ -n "$PAIR" ] || fail "$IDENTITY_FILE is empty"
case "$PAIR" in
*.*) ;;
*) fail "identity $PAIR is not a node-id.node-token pair" ;;
esac

echo "reconnect: node identity is ${PAIR%%.*}" >&2

scenario_offline
scenario_concurrent
scenario_replacement

# Cleanup is explicit rather than left to the trap, so the orphan check below runs
# after the processes are gone instead of before.
stop_all
trap - EXIT

# The concurrency fixtures are removed here rather than left behind, because a file
# this script created and did not delete is indistinguishable from one the next run
# should have found. Each removal is logged, since a silent delete cannot be told
# apart from a file that was never there.
if [ -e "$CONC_DIR" ]; then
	echo "reconnect: removing the concurrency directory $CONC_DIR" >&2
	rm -rf "$CONC_DIR"
fi
for fixture in "$E2E_WORK"/scope/conc-*.txt; do
	[ -e "$fixture" ] || continue
	echo "reconnect: removing the concurrency fixture $fixture" >&2
	rm -f "$fixture"
done

# An orphan would keep the port and the identity in use and make the next run fail
# for a reason that has nothing to do with the code under test.
orphans=$(pgrep -af 'bin/connector-(server|node)' || true)
if [ -n "$orphans" ]; then
	fail "orphan processes are still running: $orphans"
fi

echo "reconnect: all reconnect and concurrency checks passed" >&2
