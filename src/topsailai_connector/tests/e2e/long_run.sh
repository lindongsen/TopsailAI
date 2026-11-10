#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Prove the Server releases every connection over many real Node restarts.
#
# The in-process test in tests/integration/long_run_test.go counts goroutines and
# registry entries, which is precise but runs inside one process. This script is the
# complement: it restarts the real Node binary twenty times against one real Server
# and reads the evidence from the Server's own log, so the claim is about the shipped
# binaries rather than about a library call.
#
# Two independent signals are asserted:
#   1. The Server logs one "channel established" per accepted connection and one
#      "channel closed" per removed registration. After the last Node is stopped the
#      two counts must be equal. A registration that was never removed would leave
#      the counts apart, which is the leak this script exists to catch.
#   2. The Server's resident memory must not grow past a loose bound. The bound is
#      loose on purpose; see the comment on RSS_GROWTH_LIMIT_KB.
#
# Every Node stop uses the exact PID this script started. Nothing is stopped by name.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK="$ROOT/.tmp/e2e"
ENV_FILE="$WORK/env.sh"
BIN="$ROOT/bin"

SERVER_LOG="$WORK/server.log"
NODE_LOG="$WORK/node.log"

ROUNDS=20
READY_TIMEOUT=30
OFFLINE_BUDGET_MS=10000

# RSS_GROWTH_LIMIT_KB is how much the Server's resident memory may grow across the
# whole run.
#
# The bound is deliberately loose, because resident memory is a poor leak detector on
# its own: the Go runtime does not return freed pages to the operating system
# promptly, and its GC target lets the heap grow with the allocation rate rather than
# with retained data. A tight bound would therefore fail on ordinary GC behaviour and
# teach the reader to ignore the check. Thirty-two mebibytes is roughly an order of
# magnitude above what twenty short connections should cost, so it still catches a
# gross leak such as retaining every connection's buffers, which is the failure mode
# worth catching here. The precise per-round check is the goroutine count in the
# in-process test; this bound is the coarse process-level backstop.
RSS_GROWTH_LIMIT_KB=$((32 * 1024))

fail() {
	echo "long-run: $*" >&2
	exit 1
}

# now_ms prints the current time in milliseconds.
#
# python3 is used rather than `date +%s%3N`, because the latter is a GNU extension and
# this script must not depend on which date implementation is installed.
now_ms() {
	python3 -c 'import time; print(int(time.time() * 1000))'
}

# count_log prints how many times a pattern appears, treating no match as zero.
count_log() {
	local file=$1 pattern=$2
	local got
	got=$(grep -c -- "$pattern" "$file" 2>/dev/null || true)
	echo "${got:-0}"
}

# wait_for_log_count waits until a pattern has appeared at least want times.
#
# Counting rather than matching is what makes the next occurrence observable: a log
# that already contains twenty lines would satisfy a plain match immediately.
wait_for_log_count() {
	local file=$1 pattern=$2 want=$3
	local deadline=$((SECONDS + READY_TIMEOUT))
	local got
	while ((SECONDS < deadline)); do
		got=$(count_log "$file" "$pattern")
		if [ "$got" -ge "$want" ]; then
			return 0
		fi
		sleep 0.1
	done
	return 1
}

# rss_kb prints the resident memory of one process in kibibytes.
#
# /proc is read directly rather than through ps, because ps column formats differ
# between implementations and this value is compared against a number.
rss_kb() {
	local pid=$1
	local value
	value=$(awk '/^VmRSS:/ {print $2}' "/proc/$pid/status" 2>/dev/null || true)
	echo "${value:-0}"
}

# stop_pid stops one process by exact PID and waits for it to exit.
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

# stop_all stops every process this run owns. Safe to call more than once, so the
# explicit call at the end and the EXIT trap can both use it.
stop_all() {
	stop_pid "${NODE_PID:-}"
	stop_pid "${E2E_SERVER_PID:-}"
}

# record rewrites env.sh so a failure part way through still leaves the PIDs behind.
record() {
	{
		echo "E2E_SERVER_PID=${E2E_SERVER_PID:-}"
		echo "E2E_NODE_PID=${NODE_PID:-}"
		echo "E2E_BASE_URL=${E2E_BASE_URL:-}"
		echo "E2E_CHANNEL_URL=${E2E_CHANNEL_URL:-}"
		echo "E2E_CLIENT_TOKEN=${E2E_CLIENT_TOKEN:-}"
		echo "E2E_TUNNEL_TOKEN=${E2E_TUNNEL_TOKEN:-}"
		echo "E2E_WORK=${E2E_WORK:-}"
	} >"$ENV_FILE"
}

# start_node launches the Node against the recorded channel URL, appending to the
# Node log so the history of every attempt stays readable.
start_node() {
	CONNECTOR_NODE_SERVER_URL="$E2E_CHANNEL_URL" \
		CONNECTOR_NODE_TUNNEL_TOKEN="$E2E_TUNNEL_TOKEN" \
		CONNECTOR_NODE_CONFIG_DIR="$E2E_WORK/node-config" \
		"$BIN/connector-node" run >>"$NODE_LOG" 2>&1 &
	NODE_PID=$!
	record
}

cli() {
	"$BIN/connector-server" cli \
		--server "$E2E_BASE_URL" \
		--client-token "$E2E_CLIENT_TOKEN" \
		--node "$PAIR" \
		"$@"
}

# A fresh pair of processes is started here rather than inherited, so this script does
# not depend on another script's cleanup order.
echo "long-run: starting a fresh pair of processes" >&2
bash "$ROOT/tests/e2e/start.sh"

[ -f "$ENV_FILE" ] || fail "$ENV_FILE is missing after start.sh"
# shellcheck source=/dev/null
. "$ENV_FILE"

[ -n "${E2E_SERVER_PID:-}" ] || fail "no Server PID recorded"
[ -n "${E2E_NODE_PID:-}" ] || fail "no Node PID recorded"

NODE_PID="$E2E_NODE_PID"
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

echo "long-run: node identity is ${PAIR%%.*}" >&2

# The baseline is taken after the first connection is up, so the Server's own startup
# allocations are already counted and cannot be mistaken for growth caused by the
# rounds below.
BASELINE_RSS=$(rss_kb "$E2E_SERVER_PID")
[ "$BASELINE_RSS" -gt 0 ] || fail "could not read the Server's resident memory"
echo "long-run: baseline Server RSS is ${BASELINE_RSS} KiB" >&2

ESTABLISHED=$(count_log "$SERVER_LOG" 'msg="channel established"')
CLOSED=$(count_log "$SERVER_LOG" 'msg="channel closed"')
echo "long-run: before the rounds, established=$ESTABLISHED closed=$CLOSED" >&2

for round in $(seq 1 "$ROUNDS"); do
	stop_pid "$NODE_PID"
	NODE_PID=""
	record

	# The Server must report the removal before the next Node starts, otherwise the
	# next round would measure a replacement rather than a fresh registration.
	wait_for_log_count "$SERVER_LOG" 'msg="channel closed"' $((CLOSED + 1)) ||
		fail "round $round: the Server did not report the closed channel; see $SERVER_LOG"
	CLOSED=$((CLOSED + 1))

	start_node
	wait_for_log_count "$SERVER_LOG" 'msg="channel established"' $((ESTABLISHED + 1)) ||
		fail "round $round: the Node did not register; see $SERVER_LOG and $NODE_LOG"
	ESTABLISHED=$((ESTABLISHED + 1))
done

echo "long-run: completed $ROUNDS rounds, established=$ESTABLISHED closed=$CLOSED" >&2

# The final stop is what makes the counts comparable: with a Node still connected the
# Server legitimately holds one registration, so the counts would differ by one.
stop_pid "$NODE_PID"
NODE_PID=""
record
wait_for_log_count "$SERVER_LOG" 'msg="channel closed"' $((CLOSED + 1)) ||
	fail "the Server did not report the final closed channel; see $SERVER_LOG"
CLOSED=$((CLOSED + 1))

ESTABLISHED=$(count_log "$SERVER_LOG" 'msg="channel established"')
CLOSED=$(count_log "$SERVER_LOG" 'msg="channel closed"')
if [ "$ESTABLISHED" -ne "$CLOSED" ]; then
	fail "the Server logged $ESTABLISHED established channels and $CLOSED closed ones, want equal counts"
fi
echo "long-run: $ESTABLISHED channels were established and $CLOSED were closed" >&2

# With every Node stopped, a request must still be refused promptly. A Server that
# leaked a registration would answer from a dead connection instead, and the symptom
# would be a timeout rather than node_offline.
start_ms=$(now_ms)
if out=$(cli --scope project --path hello.txt file.read 2>&1); then
	fail "a request was served with no Node connected: $out"
fi
end_ms=$(now_ms)
elapsed=$((end_ms - start_ms))
case "$out" in
*node_offline*) ;;
*) fail "a request with no Node connected reported $(printf '%q' "$out"), want node_offline" ;;
esac
if [ "$elapsed" -ge "$OFFLINE_BUDGET_MS" ]; then
	fail "a request with no Node connected took ${elapsed}ms, want under ${OFFLINE_BUDGET_MS}ms"
fi
echo "long-run: with no Node connected, a request was refused with node_offline in ${elapsed}ms" >&2

FINAL_RSS=$(rss_kb "$E2E_SERVER_PID")
GROWTH=$((FINAL_RSS - BASELINE_RSS))
echo "long-run: final Server RSS is ${FINAL_RSS} KiB, growth ${GROWTH} KiB" >&2
if [ "$GROWTH" -gt "$RSS_GROWTH_LIMIT_KB" ]; then
	fail "the Server's resident memory grew ${GROWTH} KiB across $ROUNDS rounds, limit ${RSS_GROWTH_LIMIT_KB} KiB"
fi

# Cleanup is explicit rather than left to the trap, so the orphan check below runs
# after the processes are gone instead of before.
stop_all
trap - EXIT

# An orphan would keep the port and the identity in use and make the next run fail for
# a reason that has nothing to do with the code under test.
orphans=$(pgrep -af 'bin/connector-(server|node)' || true)
if [ -n "$orphans" ]; then
	fail "orphan processes are still running: $orphans"
fi

echo "long-run: all long-run checks passed" >&2
