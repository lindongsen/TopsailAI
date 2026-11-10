#!/usr/bin/env bash
#
# manual_probe.sh drives one live pair of processes through the CLI and asserts
# the answers an operator would see. It exists because the other scripts assert
# their own claims; this one is written to be read line by line and to probe the
# cases the scripted suite does not cover, such as a nested path inside a scope
# and a scope that the policy never named.
#
# Every artifact lives under .tmp/manual/, which is ignored by git. Both processes
# are stopped by the exact PID this script started, never by name.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BIN="$ROOT/bin"
WORK="$ROOT/.tmp/manual"
SERVER_LOG="$WORK/server.log"
NODE_LOG="$WORK/node.log"
ENV_FILE="$WORK/env.sh"
READY_TIMEOUT=20

SERVER_PID=""
NODE_PID=""

fail() {
	echo "manual: $*" >&2
	exit 1
}

# stop_processes stops the two processes by exact PID.
#
# A signal goes to the PID this run started, never to a name, because a name match
# would also stop an unrelated process the operator happens to be running.
stop_processes() {
	local pid
	for pid in "$NODE_PID" "$SERVER_PID"; do
		[ -n "$pid" ] || continue
		if kill -0 "$pid" 2>/dev/null; then
			kill "$pid" 2>/dev/null || true
		fi
	done
	for pid in "$NODE_PID" "$SERVER_PID"; do
		[ -n "$pid" ] || continue
		local deadline=$((SECONDS + 10))
		while kill -0 "$pid" 2>/dev/null && ((SECONDS < deadline)); do
			sleep 0.1
		done
		if kill -0 "$pid" 2>/dev/null; then
			echo "manual: pid $pid did not exit within 10s" >&2
		fi
	done
}

# cleanup_fixtures removes the files this script created.
#
# A fixture this script created and did not delete is indistinguishable from one the
# next run should have found, so it is removed. Each removal is logged, because a
# silent delete cannot be told apart from a file that was never there. The symlink is
# removed first: it points outside the scope, so leaving it behind would leave a
# standing escape route in the work directory.
cleanup_fixtures() {
	local fixture
	for fixture in "$WORK/scope/escape.txt"; do
		if [ -e "$fixture" ] || [ -L "$fixture" ]; then
			echo "manual: removing the fixture $fixture" >&2
			rm -f "$fixture"
		fi
	done
}

trap 'stop_processes; cleanup_fixtures' EXIT

# count_matches prints how many lines of a file match a pattern.
#
# It prints 0 rather than failing when the file is absent or nothing matches, so the
# caller can compare counts without treating "no match yet" as an error.
count_matches() {
	local file="$1" pattern="$2"
	if [ ! -f "$file" ]; then
		echo 0
		return 0
	fi
	grep -c "$pattern" "$file" || true
}

# wait_for_log waits for a pattern to appear in a file.
#
# It waits for a NEW occurrence beyond a baseline the caller captured BEFORE the action
# that should produce it. Two separate mistakes are avoided this way:
#   - A plain grep matches a line from an earlier run, because the Node log is appended
#     to across a restart, so the wait returns before the restarted Node registered.
#   - Capturing the baseline inside this function is also wrong, because the event can
#     already have happened by the time it is called: the baseline would include the
#     very occurrence being waited for, and the wait would then block until timeout.
wait_for_log() {
	local file="$1" pattern="$2" baseline="$3" deadline=$((SECONDS + READY_TIMEOUT))
	while ((SECONDS < deadline)); do
		if [ "$(count_matches "$file" "$pattern")" -gt "$baseline" ]; then
			return 0
		fi
		sleep 0.1
	done
	return 1
}

# pick_port asks the kernel for a free port and prints it.
#
# The Server refuses a configured port of 0 on purpose, so the script asks the
# kernel for a number and passes that number.
pick_port() {
	python3 - <<'PICK'
import socket
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PICK
}

[ -x "$BIN/connector-server" ] || fail "$BIN/connector-server is missing; run make build"
[ -x "$BIN/connector-node" ] || fail "$BIN/connector-node is missing; run make build"

# A stale work directory would let a previous run's identity answer for this one,
# so it is removed first. The removal is logged because a silent delete cannot be
# told apart from a directory that was never there.
if [ -e "$WORK" ]; then
	echo "manual: removing the previous work directory $WORK" >&2
	rm -rf "$WORK"
fi
mkdir -p "$WORK/node-config" "$WORK/scope/sub"

printf 'manual live probe payload\n' >"$WORK/scope/probe.txt"
printf 'nested payload\n' >"$WORK/scope/sub/nested.txt"
# This file sits outside the scope root. A read of it must be refused, which is the
# fence doing its job rather than a missing file being reported.
printf 'SECRET-OUTSIDE-SCOPE\n' >"$WORK/outside.txt"

cat >"$WORK/node-config/policy.yaml" <<POLICY
version: 1
scopes:
  project:
    path: $WORK/scope
grants:
  - scope: project
    permissions: [read, list, stat]
POLICY

PORT=$(pick_port)
[ -n "$PORT" ] || fail "could not pick a free port"
TUNNEL_TOKEN="tunnel-manual-$RANDOM$RANDOM"
CLIENT_TOKEN="client-manual-$RANDOM$RANDOM"
LISTEN="127.0.0.1:$PORT"
BASE_URL="http://$LISTEN"
CHANNEL_URL="ws://$LISTEN/channel"

echo "manual: launching the Server on $LISTEN" >&2
LISTEN_BASELINE=$(count_matches "$SERVER_LOG" 'msg="server listening"')
CONNECTOR_SERVER_LISTEN="$LISTEN" \
	CONNECTOR_SERVER_TUNNEL_TOKEN="$TUNNEL_TOKEN" \
	CONNECTOR_SERVER_CLIENT_TOKEN="$CLIENT_TOKEN" \
	"$BIN/connector-server" run >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
wait_for_log "$SERVER_LOG" 'msg="server listening"' "$LISTEN_BASELINE" ||
	fail "the Server did not listen within ${READY_TIMEOUT}s; see $SERVER_LOG"

echo "manual: launching the Node" >&2
ESTABLISHED_BASELINE=$(count_matches "$SERVER_LOG" 'msg="channel established"')
CONNECTOR_NODE_SERVER_URL="$CHANNEL_URL" \
	CONNECTOR_NODE_TUNNEL_TOKEN="$TUNNEL_TOKEN" \
	CONNECTOR_NODE_CONFIG_DIR="$WORK/node-config" \
	"$BIN/connector-node" run >"$NODE_LOG" 2>&1 &
NODE_PID=$!
wait_for_log "$SERVER_LOG" 'msg="channel established"' "$ESTABLISHED_BASELINE" ||
	fail "the Node did not register within ${READY_TIMEOUT}s; see $SERVER_LOG"

IDENTITY_FILE="$WORK/node-config/identity"
[ -f "$IDENTITY_FILE" ] || fail "$IDENTITY_FILE is missing; the Node did not write an identity"
PAIR=$(tr -d '\r\n' <"$IDENTITY_FILE")
case "$PAIR" in
*.*) ;;
*) fail "identity $PAIR is not a node-id.node-token pair" ;;
esac
NODE_ID="${PAIR%%.*}"
NODE_TOKEN="${PAIR#*.}"

{
	echo "E2E_BASE_URL=$BASE_URL"
	echo "E2E_CLIENT_TOKEN=$CLIENT_TOKEN"
	echo "E2E_NODE_ID=$NODE_ID"
	echo "E2E_NODE_TOKEN=$NODE_TOKEN"
	echo "E2E_SERVER_PID=$SERVER_PID"
	echo "E2E_NODE_PID=$NODE_PID"
	echo "E2E_WORK=$WORK"
} >"$ENV_FILE"

echo "manual: node identity is $NODE_ID" >&2

# cli runs one operation through the CLI and prints its output.
#
# The operation is the single positional argument; the scope and the path are flags.
# Passing them positionally is refused by the CLI, which is why this helper spells
# the shape out once instead of at every call site.
cli() {
	local operation="$1" scope="$2" path="$3"
	"$BIN/connector-server" cli \
		--server "$BASE_URL" \
		--client-token "$CLIENT_TOKEN" \
		--node "$PAIR" \
		--scope "$scope" \
		--path "$path" \
		"$operation"
}

echo "manual: probe 1: a read returns the exact bytes" >&2
OUT=$(cli file.read project probe.txt) || fail "file.read failed: $OUT"
case "$OUT" in
*"manual live probe payload"*) ;;
*) fail "file.read returned $OUT, want the file content" ;;
esac

echo "manual: probe 2: a nested path inside the scope is readable" >&2
OUT=$(cli file.read project sub/nested.txt) || fail "a nested read failed: $OUT"
case "$OUT" in
*"nested payload"*) ;;
*) fail "a nested read returned $OUT, want the nested content" ;;
esac

echo "manual: probe 3: a listing names the file" >&2
# The scope root is addressed with an empty path. A "." component is refused rather
# than normalised, which is deliberate: normalising would mean the fence and the
# caller disagree about which file was named.
OUT=$(cli file.list project "") || fail "file.list failed: $OUT"
case "$OUT" in
*probe.txt*) ;;
*) fail "file.list returned $OUT, want probe.txt named" ;;
esac

echo "manual: probe 3b: a dot component is refused rather than normalised" >&2
OUT=$(cli file.list project "." 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
	fail "a path with a dot component was accepted and returned $OUT"
fi

echo "manual: probe 4: a stat reports the size" >&2
# The expected size is read from the file rather than written as a literal, because a
# literal drifts the moment the fixture changes and a loose glob such as *25* would
# match a number in another field and pass for the wrong reason.
WANT_SIZE=$(wc -c <"$WORK/scope/probe.txt" | tr -d ' ')
OUT=$(cli file.stat project probe.txt) || fail "file.stat failed: $OUT"
case "$OUT" in
*"size"*"$WANT_SIZE"*) ;;
*) fail "file.stat returned $OUT, want the size $WANT_SIZE" ;;
esac

echo "manual: probe 5: a path outside the scope is refused" >&2
OUT=$(cli file.read project ../outside.txt 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
	fail "a read outside the scope succeeded and returned $OUT"
fi
case "$OUT" in
*SECRET-OUTSIDE-SCOPE*) fail "the refusal leaked the outside file content: $OUT" ;;
*) ;;
esac

echo "manual: probe 5b: a symlink pointing outside the scope is refused" >&2
# The path is a clean relative name, so the refusal cannot come from path syntax. It
# has to come from the fence resolving the link and finding the target outside the
# scope root, which is the containment check itself.
ln -sfn "$WORK/outside.txt" "$WORK/scope/escape.txt"
OUT=$(cli file.read project escape.txt 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
	fail "a read through a symlink out of the scope succeeded and returned $OUT"
fi
case "$OUT" in
*SECRET-OUTSIDE-SCOPE*) fail "the refusal leaked the outside file content: $OUT" ;;
*) ;;
esac

echo "manual: probe 6: an absolute path is refused" >&2
OUT=$(cli file.read project /etc/passwd 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
	fail "an absolute read succeeded and returned $OUT"
fi

echo "manual: probe 7: a scope the policy never named is refused" >&2
OUT=$(cli file.read scratch probe.txt 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
	fail "a read of an unnamed scope succeeded and returned $OUT"
fi

echo "manual: probe 8: a wrong client token is refused" >&2
OUT=$("$BIN/connector-server" cli \
	--server "$BASE_URL" \
	--client-token "wrong-client-token" \
	--node "$PAIR" \
	--scope project \
	--path probe.txt \
	file.read 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
	fail "a wrong client token was accepted and returned $OUT"
fi
# The code is asserted, not just the exit status: a usage error also exits non-zero and
# would let this probe pass without ever reaching the authentication check.
case "$OUT" in
*unauthenticated*) ;;
*) fail "a wrong client token was refused with $OUT, want unauthenticated" ;;
esac

echo "manual: probe 9: a wrong node token is refused" >&2
# The substitute is the same shape as a real token, because a token the CLI rejects as
# malformed never reaches the Node and the probe would pass without testing anything.
WRONG_NODE_TOKEN=$(printf '%052d' 0 | tr '0' 'a')
OUT=$("$BIN/connector-server" cli \
	--server "$BASE_URL" \
	--client-token "$CLIENT_TOKEN" \
	--node "$NODE_ID.$WRONG_NODE_TOKEN" \
	--scope project \
	--path probe.txt \
	file.read 2>&1)
STATUS=$?
if [ "$STATUS" -eq 0 ]; then
	fail "a wrong node token was accepted and returned $OUT"
fi
# The Node answers unauthenticated rather than denied, because the caller did not prove
# it may talk to this Node at all. Asserting the code keeps that distinction honest.
case "$OUT" in
*unauthenticated*) ;;
*) fail "a wrong node token was refused with $OUT, want unauthenticated" ;;
esac

echo "manual: probe 10: the Server log holds no node token" >&2
if grep -qF "$NODE_TOKEN" "$SERVER_LOG"; then
	fail "the node token reached the Server log"
fi

echo "manual: probe 11: the Server log holds no client token" >&2
if grep -qF "$CLIENT_TOKEN" "$SERVER_LOG"; then
	fail "the client token reached the Server log"
fi

echo "manual: probe 12: the Server log holds no tunnel token" >&2
if grep -qF "$TUNNEL_TOKEN" "$SERVER_LOG"; then
	fail "the tunnel token reached the Server log"
fi

echo "manual: probe 13: the node token appears once, from the first-run print" >&2
COUNT=$(grep -cF "$NODE_TOKEN" "$NODE_LOG" || true)
if [ "$COUNT" -ne 1 ]; then
	fail "the node token appears $COUNT times in the Node log, want exactly 1 from the first-run print"
fi
if ! grep -q 'node identity generated' "$NODE_LOG"; then
	fail "the single occurrence is not the first-run identity print"
fi

echo "manual: probe 14: a killed Node makes the next request fail fast" >&2
CLOSED_BASELINE=$(count_matches "$SERVER_LOG" 'msg="channel closed"')
kill "$NODE_PID" 2>/dev/null || true
wait_for_log "$SERVER_LOG" 'msg="channel closed"' "$CLOSED_BASELINE" ||
	fail "the Server did not record the closed channel"
START_MS=$(date +%s%3N)
OUT=$(cli file.read project probe.txt 2>&1)
STATUS=$?
ELAPSED_MS=$(( $(date +%s%3N) - START_MS ))
if [ "$STATUS" -eq 0 ]; then
	fail "a request with no Node connected succeeded and returned $OUT"
fi
case "$OUT" in
*node_offline*) ;;
*) fail "the refusal was $OUT, want node_offline" ;;
esac
if [ "$ELAPSED_MS" -gt 10000 ]; then
	fail "the refusal took ${ELAPSED_MS}ms, want under 10000ms"
fi
echo "manual: an offline request was refused with node_offline in ${ELAPSED_MS}ms" >&2
NODE_PID=""

echo "manual: probe 15: a restarted Node serves again" >&2
RESTART_BASELINE=$(count_matches "$SERVER_LOG" 'msg="channel established"')
CONNECTOR_NODE_SERVER_URL="$CHANNEL_URL" \
	CONNECTOR_NODE_TUNNEL_TOKEN="$TUNNEL_TOKEN" \
	CONNECTOR_NODE_CONFIG_DIR="$WORK/node-config" \
	"$BIN/connector-node" run >>"$NODE_LOG" 2>&1 &
NODE_PID=$!
wait_for_log "$SERVER_LOG" 'msg="channel established"' "$RESTART_BASELINE" ||
	fail "the restarted Node did not register"
OUT=$(cli file.read project probe.txt) || fail "a read after the restart failed: $OUT"
case "$OUT" in
*"manual live probe payload"*) ;;
*) fail "a read after the restart returned $OUT, want the file content" ;;
esac

echo "manual: all live probes passed" >&2
