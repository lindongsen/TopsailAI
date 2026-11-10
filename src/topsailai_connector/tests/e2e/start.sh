#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Launch the Server and the Node for the end-to-end test and report readiness.
#
# This script only launches and reports. It sends no request and asserts nothing
# about an answer, so a failure here means "the processes did not come up" while a
# failure in run.sh means "they came up but answered wrongly". Keeping the two
# apart is what makes a red run diagnosable instead of a single opaque failure.
#
# Every artifact lives under .tmp/e2e/, which is ignored by git. The scope root is
# deliberately a sibling of the config directory rather than a child, because the
# Node refuses a scope that is inside its own config directory.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK="$ROOT/.tmp/e2e"
BIN="$ROOT/bin"

SERVER_LOG="$WORK/server.log"
NODE_LOG="$WORK/node.log"
ENV_FILE="$WORK/env.sh"

TUNNEL_TOKEN="e2e-tunnel-token-0123456789"
CLIENT_TOKEN="e2e-client-token-0123456789"
READY_TIMEOUT=30

fail() {
	echo "start: $*" >&2
	exit 1
}

# wait_for_log waits for a pattern to appear in a log file, so readiness is read
# from what the process actually reported rather than from a fixed sleep.
#
# It returns non-zero on timeout instead of exiting, because the caller decides
# whether a missing line is fatal or worth one more attempt with a new port.
wait_for_log() {
	local file=$1 pattern=$2
	local deadline=$((SECONDS + READY_TIMEOUT))
	while ((SECONDS < deadline)); do
		if grep -q -- "$pattern" "$file" 2>/dev/null; then
			return 0
		fi
		sleep 0.1
	done
	return 1
}

# record writes the values run.sh needs. It is rewritten after each launch so a
# partial start still leaves the PIDs behind for run.sh to clean up.
record() {
	{
		echo "E2E_SERVER_PID=${SERVER_PID:-}"
		echo "E2E_NODE_PID=${NODE_PID:-}"
		echo "E2E_BASE_URL=${BASE_URL:-}"
		echo "E2E_CHANNEL_URL=${CHANNEL_URL:-}"
		echo "E2E_CLIENT_TOKEN=${CLIENT_TOKEN}"
		echo "E2E_TUNNEL_TOKEN=${TUNNEL_TOKEN}"
		echo "E2E_WORK=${WORK}"
	} >"$ENV_FILE"
}

[ -x "$BIN/connector-server" ] || fail "$BIN/connector-server is missing; run make build"
[ -x "$BIN/connector-node" ] || fail "$BIN/connector-node is missing; run make build"

# A stale work directory would let a previous run's identity and log answer for
# this one, so it is removed before anything starts. The removal is logged because
# a silent delete is indistinguishable from a directory that was never there.
if [ -e "$WORK" ]; then
	echo "start: removing the previous work directory $WORK" >&2
	rm -rf "$WORK"
fi
mkdir -p "$WORK/node-config" "$WORK/scope"

printf 'hello from the end-to-end test\n' >"$WORK/scope/hello.txt"

cat >"$WORK/node-config/policy.yaml" <<POLICY
version: 1
scopes:
  project:
    path: $WORK/scope
grants:
  - scope: project
    permissions: [read, list, stat]
POLICY
SERVER_PID=""
NODE_PID=""
BASE_URL=""
CHANNEL_URL=""
record

# pick_port asks the kernel for a free port and prints it.
#
# The Server refuses port 0 on purpose, because a configured port of 0 means "any
# port" and an operator who wrote 0 almost certainly meant a real number. So the
# script asks the kernel for a free port itself and passes that number.
pick_port() {
	python3 - <<'PICK'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PICK
}

# launch_server starts the Server on a free port and waits for it to listen.
#
# The port is picked and then bound by a different process, so a race is possible:
# another process can take the port in between. A failed bind is retried with a new
# port a bounded number of times rather than treated as a test failure, because the
# race is not a defect in the code under test.
launch_server() {
	local attempt
	for attempt in 1 2 3 4 5; do
		PORT=$(pick_port)
		[ -n "$PORT" ] || fail "could not pick a free port"
		: >"$SERVER_LOG"
		CONNECTOR_SERVER_LISTEN="127.0.0.1:$PORT" \
			CONNECTOR_SERVER_TUNNEL_TOKEN="$TUNNEL_TOKEN" \
			CONNECTOR_SERVER_CLIENT_TOKEN="$CLIENT_TOKEN" \
			"$BIN/connector-server" run >"$SERVER_LOG" 2>&1 &
		SERVER_PID=$!
		record
		if wait_for_log "$SERVER_LOG" 'msg="server listening"'; then
			return 0
		fi
		kill "$SERVER_PID" 2>/dev/null || true
		wait "$SERVER_PID" 2>/dev/null || true
		SERVER_PID=""
		record
		echo "start: port $PORT was not usable, trying another" >&2
	done
	fail "the Server did not listen after 5 attempts; see $SERVER_LOG"
}

echo "start: launching the Server" >&2
launch_server

LISTEN="127.0.0.1:$PORT"
BASE_URL="http://$LISTEN"
CHANNEL_URL="ws://$LISTEN/channel"
record
echo "start: Server listening on $LISTEN" >&2

echo "start: launching the Node" >&2
CONNECTOR_NODE_SERVER_URL="$CHANNEL_URL" \
	CONNECTOR_NODE_TUNNEL_TOKEN="$TUNNEL_TOKEN" \
	CONNECTOR_NODE_CONFIG_DIR="$WORK/node-config" \
	"$BIN/connector-node" run >"$NODE_LOG" 2>&1 &
NODE_PID=$!
record

wait_for_log "$SERVER_LOG" 'msg="channel established"' ||
	fail "the Node did not register its channel within ${READY_TIMEOUT}s; see $SERVER_LOG"
wait_for_log "$NODE_LOG" 'msg="handshake accepted"' ||
	fail "the Node did not accept the handshake within ${READY_TIMEOUT}s; see $NODE_LOG"

echo "start: ready" >&2
