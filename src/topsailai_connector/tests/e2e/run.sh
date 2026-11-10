#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Drive one file.read through two real processes and assert the answer.
#
# This script assumes start.sh already launched the Server and the Node and wrote
# .tmp/e2e/env.sh. It sends requests, asserts the answers and stops the two
# processes by exact PID. It never launches anything, so a failure here is always
# about behaviour rather than about startup.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK="$ROOT/.tmp/e2e"
ENV_FILE="$WORK/env.sh"
BIN="$ROOT/bin"

SERVER_LOG="$WORK/server.log"
NODE_LOG="$WORK/node.log"

fail() {
	echo "run: $*" >&2
	exit 1
}

[ -f "$ENV_FILE" ] || fail "$ENV_FILE is missing; run start.sh first"
# shellcheck source=/dev/null
. "$ENV_FILE"

[ -n "${E2E_SERVER_PID:-}" ] || fail "no Server PID recorded; run start.sh first"
[ -n "${E2E_NODE_PID:-}" ] || fail "no Node PID recorded; run start.sh first"

# stop_processes stops the two processes by exact PID.
#
# A signal is sent to the PID this run started, never to a name, because a name
# match would also stop an unrelated process the operator happens to be running.
# The wait is bounded and a process that ignores the signal is reported rather
# than escalated to a broader kill.
stop_processes() {
	local pid
	for pid in "${E2E_NODE_PID:-}" "${E2E_SERVER_PID:-}"; do
		[ -n "$pid" ] || continue
		if kill -0 "$pid" 2>/dev/null; then
			kill "$pid" 2>/dev/null || true
		fi
	done
	for pid in "${E2E_NODE_PID:-}" "${E2E_SERVER_PID:-}"; do
		[ -n "$pid" ] || continue
		local deadline=$((SECONDS + 10))
		while kill -0 "$pid" 2>/dev/null && ((SECONDS < deadline)); do
			sleep 0.1
		done
		if kill -0 "$pid" 2>/dev/null; then
			echo "run: pid $pid did not exit within 10s" >&2
		fi
	done
}

trap stop_processes EXIT

# The pair is read from the identity file the Node wrote, which is the same value
# an operator would copy. Reading it here proves the file is usable, not just that
# the Node started.
IDENTITY_FILE="$E2E_WORK/node-config/identity"
[ -f "$IDENTITY_FILE" ] || fail "$IDENTITY_FILE is missing; the Node did not write an identity"
PAIR=$(tr -d '\r\n' <"$IDENTITY_FILE")
[ -n "$PAIR" ] || fail "$IDENTITY_FILE is empty"
case "$PAIR" in
*.*) ;;
*) fail "identity $PAIR is not a node-id.node-token pair" ;;
esac

echo "run: node identity is ${PAIR%%.*}" >&2

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
	echo "run: file.read returned the file content" >&2
}

# check_list asserts that file.list names the file, which proves a second
# operation works over the same channel rather than only the first one.
check_list() {
	local got
	got=$(cli --scope project file.list)
	case "$got" in
	*hello.txt*) ;;
	*) fail "file.list returned $(printf '%q' "$got"), want an entry named hello.txt" ;;
	esac
	echo "run: file.list named hello.txt" >&2
}

# check_stat asserts that file.stat reports the size, which proves the stat path
# reaches the same file the read did. The match is anchored to the size line
# because modified_at is a timestamp that can also contain the digits 31, and a
# loose match would pass for the wrong reason.
check_stat() {
	local got
	got=$(cli --scope project --path hello.txt file.stat)
	case "$got" in
	*$'size\t31'*) ;;
	*) fail "file.stat returned $(printf '%q' "$got"), want a size of 31" ;;
	esac
	echo "run: file.stat reported the size" >&2
}

# check_refusals asserts that the two gates refuse a wrong secret. A run that only
# proved the happy path would not show that the secrets are checked at all.
check_refusals() {
	local out
	if out=$("$BIN/connector-server" cli \
		--server "$E2E_BASE_URL" \
		--client-token "wrong-client-token-0123456789" \
		--node "$PAIR" \
		--scope project --path hello.txt file.read 2>&1); then
		fail "a wrong client token was accepted: $out"
	fi
	case "$out" in
	*unauthenticated*) ;;
	*) fail "a wrong client token reported $(printf '%q' "$out"), want unauthenticated" ;;
	esac
	echo "run: a wrong client token was refused" >&2

	local wrong_pair="${PAIR%%.*}.wrongnodetoken0123456789"
	if out=$("$BIN/connector-server" cli \
		--server "$E2E_BASE_URL" \
		--client-token "$E2E_CLIENT_TOKEN" \
		--node "$wrong_pair" \
		--scope project --path hello.txt file.read 2>&1); then
		fail "a wrong node token was accepted: $out"
	fi
	case "$out" in
	*unauthenticated*) ;;
	*) fail "a wrong node token reported $(printf '%q' "$out"), want unauthenticated" ;;
	esac
	echo "run: a wrong node token was refused" >&2

	if out=$(cli --scope project --path ../policy.yaml file.read 2>&1); then
		fail "a path outside the scope was served: $out"
	fi
	echo "run: a path outside the scope was refused" >&2
}

# check_secrets_absent asserts that no secret reached a log file.
#
# The tunnel token must be absent from both logs. The node token must be absent
# from the Server log specifically, because the Server is the party that must never
# store a node token. The Node prints its own pair once at generation, on stdout,
# because the operator has to copy it into a CLI and there is no lookup endpoint;
# that is the documented provisioning path, not a leak, so the Node log is not
# asserted against its own token.
check_secrets_absent() {
	local file
	for file in "$SERVER_LOG" "$NODE_LOG"; do
		[ -f "$file" ] || continue
		if grep -qF "$E2E_TUNNEL_TOKEN" "$file"; then
			fail "$file contains the tunnel token"
		fi
	done
	if grep -qF "${PAIR#*.}" "$SERVER_LOG"; then
		fail "$SERVER_LOG contains the node token"
	fi
	echo "run: no secret reached the Server log" >&2
}

check_read
check_list
check_stat
check_refusals
check_secrets_absent

echo "run: all end-to-end checks passed" >&2
