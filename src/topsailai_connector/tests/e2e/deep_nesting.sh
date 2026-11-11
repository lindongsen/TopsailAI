#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Prove that a deeply nested directory tree is readable through two real
# processes, and that depth does not weaken the fence.
#
# The unit test proves the fence handles depth in-process. This script proves the
# same thing across the wire, because a depth limit could also come from the frame
# cap, the JSON encoding or the CLI's own argument handling, none of which the
# unit test touches.
#
# Every artifact lives under .tmp/e2e-deep/, which is ignored by git. The scope
# root is a sibling of the config directory because the Node refuses a scope that
# is inside its own config directory.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK="$ROOT/.tmp/e2e-deep"
BIN="$ROOT/bin"

SERVER_LOG="$WORK/server.log"
NODE_LOG="$WORK/node.log"
SCOPE="$WORK/scope"
CONFIG="$WORK/node-config"

TUNNEL_TOKEN="deep-tunnel-token-0123456789"
CLIENT_TOKEN="deep-client-token-0123456789"
READY_TIMEOUT=30

SERVER_PID=""
NODE_PID=""

fail() {
	echo "deep: $*" >&2
	exit 1
}

# stop_processes stops the two processes by exact PID.
#
# A signal is sent to the PID this run started, never to a name, because a name
# match would also stop an unrelated process the operator happens to be running.
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
			echo "deep: pid $pid did not exit within 10s" >&2
		fi
	done
}
trap stop_processes EXIT

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

if [ -e "$WORK" ]; then
	echo "deep: removing the previous work directory $WORK" >&2
	rm -rf "$WORK"
fi
mkdir -p "$CONFIG" "$SCOPE"

# build_tree creates `depth` nested directories named d and writes one file at the
# bottom of each sampled depth, so a read at depth N is a real read of a real file.
build_tree() {
	local depth=$1
	local path=$SCOPE
	local index
	for ((index = 0; index < depth; index++)); do
		path="$path/d"
	done
	mkdir -p "$path"
	printf 'payload-at-%d' "$depth" >"$path/f.txt"
}

DEPTHS=(1 2 3 5 10 20 50 100 200)
for depth in "${DEPTHS[@]}"; do
	build_tree "$depth"
done

# A symlink at the bottom of a deep tree, pointing outside the scope. A fence that
# truncated or depth-limited the path would miss this, because the escape happens
# far from the root where a shallow check never looks.
mkdir -p "$WORK/outside"
printf 'outside secret' >"$WORK/outside/secret.txt"
# DEEP_LINK_FS is a filesystem suffix, so it needs a leading separator.
# DEEP_LINK_WIRE is a wire path, so it must not have one: a leading "/" is
# absolute and the Node refuses it before the fence is reached.
DEEP_LINK_FS=""
DEEP_LINK_WIRE=""
for ((index = 0; index < 20; index++)); do
	DEEP_LINK_FS="$DEEP_LINK_FS/d"
	if [ -z "$DEEP_LINK_WIRE" ]; then
		DEEP_LINK_WIRE="d"
	else
		DEEP_LINK_WIRE="$DEEP_LINK_WIRE/d"
	fi
done
ln -s "$WORK/outside" "$SCOPE$DEEP_LINK_FS/escape"

cat >"$CONFIG/policy.yaml" <<POLICY
version: 1
scopes:
  project:
    path: $SCOPE
grants:
  - scope: project
    permissions: [read, list, stat]
POLICY

PORT=$(pick_port)
[ -n "$PORT" ] || fail "could not pick a free port"
LISTEN="127.0.0.1:$PORT"
BASE_URL="http://$LISTEN"
CHANNEL_URL="ws://$LISTEN/channel"

echo "deep: launching the Server on $LISTEN" >&2
CONNECTOR_SERVER_LISTEN="$LISTEN" \
	CONNECTOR_SERVER_TUNNEL_TOKEN="$TUNNEL_TOKEN" \
	CONNECTOR_SERVER_CLIENT_TOKEN="$CLIENT_TOKEN" \
	"$BIN/connector-server" run >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
wait_for_log "$SERVER_LOG" 'msg="server listening"' || fail "the Server did not listen; see $SERVER_LOG"

echo "deep: launching the Node" >&2
CONNECTOR_NODE_SERVER_URL="$CHANNEL_URL" \
	CONNECTOR_NODE_TUNNEL_TOKEN="$TUNNEL_TOKEN" \
	CONNECTOR_NODE_CONFIG_DIR="$CONFIG" \
	"$BIN/connector-node" run >"$NODE_LOG" 2>&1 &
NODE_PID=$!
wait_for_log "$SERVER_LOG" 'msg="channel established"' || fail "the Node did not register; see $SERVER_LOG"
wait_for_log "$NODE_LOG" 'msg="handshake accepted"' || fail "the Node did not accept the handshake; see $NODE_LOG"

IDENTITY_FILE="$CONFIG/identity"
[ -f "$IDENTITY_FILE" ] || fail "$IDENTITY_FILE is missing"
PAIR=$(tr -d '\r\n' <"$IDENTITY_FILE")
[ -n "$PAIR" ] || fail "$IDENTITY_FILE is empty"

cli() {
	"$BIN/connector-server" cli \
		--server "$BASE_URL" \
		--client-token "$CLIENT_TOKEN" \
		--node "$PAIR" \
		"$@"
}

# deep_rel builds the relative path of the file at `depth`.
#
# The first component is written without a leading separator, because a path that
# starts with "/" is absolute and the Node refuses it before it reaches the fence.
deep_rel() {
	local depth=$1
	local rel="d"
	local index
	for ((index = 1; index < depth; index++)); do
		rel="$rel/d"
	done
	printf '%s/f.txt' "$rel"
}

# deep_dir builds the relative path of the directory at `depth`.
deep_dir() {
	local depth=$1
	local rel="d"
	local index
	for ((index = 1; index < depth; index++)); do
		rel="$rel/d"
	done
	printf '%s' "$rel"
}

PASS=0
FAILED=0

check() {
	local label=$1
	shift
	if "$@"; then
		PASS=$((PASS + 1))
		echo "deep: PASS $label" >&2
	else
		FAILED=$((FAILED + 1))
		echo "deep: FAIL $label" >&2
	fi
}

# check_depth asserts read, stat and list all work at one depth.
check_depth() {
	local depth=$1
	local rel dir want got

	rel=$(deep_rel "$depth")
	dir=$(deep_dir "$depth")
	want="payload-at-$depth"

	got=$(cli --scope project --path "$rel" file.read 2>&1) || {
		echo "deep:   depth $depth file.read failed: $got" >&2
		return 1
	}
	if [ "$got" != "$want" ]; then
		echo "deep:   depth $depth file.read returned $(printf '%q' "$got"), want $(printf '%q' "$want")" >&2
		return 1
	fi

	got=$(cli --scope project --path "$rel" file.stat 2>&1) || {
		echo "deep:   depth $depth file.stat failed: $got" >&2
		return 1
	}
	case "$got" in
	*$'size\t'"${#want}"$'\n'*) ;;
	*)
		echo "deep:   depth $depth file.stat returned $(printf '%q' "$got"), want size ${#want}" >&2
		return 1
		;;
	esac

	got=$(cli --scope project --path "$dir" file.list 2>&1) || {
		echo "deep:   depth $depth file.list failed: $got" >&2
		return 1
	}
	case "$got" in
	*f.txt*) ;;
	*)
		echo "deep:   depth $depth file.list returned $(printf '%q' "$got"), want an entry named f.txt" >&2
		return 1
		;;
	esac

	return 0
}

for depth in "${DEPTHS[@]}"; do
	check "depth $depth read stat list" check_depth "$depth"
done

# check_deep_escape asserts the fence still refuses an escape at depth 20.
check_deep_escape() {
	local out
	if out=$(cli --scope project --path "$DEEP_LINK_WIRE/escape/secret.txt" file.read 2>&1); then
		echo "deep:   a deep escaping symlink was read: $out" >&2
		return 1
	fi
	case "$out" in
	*denied*) ;;
	*)
		echo "deep:   a deep escaping symlink reported $(printf '%q' "$out"), want denied" >&2
		return 1
		;;
	esac
	return 0
}
check "deep escaping symlink refused" check_deep_escape

# check_deep_stat_symlink asserts stat reports the link without following it.
check_deep_stat_symlink() {
	local out
	out=$(cli --scope project --path "$DEEP_LINK_WIRE/escape" file.stat 2>&1) || {
		echo "deep:   file.stat on a deep symlink failed: $out" >&2
		return 1
	}
	case "$out" in
	*symlink*) ;;
	*)
		echo "deep:   file.stat on a deep symlink returned $(printf '%q' "$out"), want a symlink" >&2
		return 1
		;;
	esac
	return 0
}
check "deep symlink reported without following" check_deep_stat_symlink

# check_over_limit asserts a path over the grammar limit is refused.
check_over_limit() {
	local out long
	long=$(python3 -c 'print("a" * 5000)')
	if out=$(cli --scope project --path "$long" file.read 2>&1); then
		echo "deep:   an over-long path was read: $out" >&2
		return 1
	fi
	case "$out" in
	*invalid_argument*) ;;
	*)
		echo "deep:   an over-long path reported $(printf '%q' "$out"), want invalid_argument" >&2
		return 1
		;;
	esac
	return 0
}
check "over-long path refused" check_over_limit

echo "deep: $PASS passed, $FAILED failed" >&2
[ "$FAILED" -eq 0 ] || exit 1
