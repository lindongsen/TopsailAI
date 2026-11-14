#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Verify a packaged bundle end to end: build the zip, unzip it, start a
# real Server, start the bundle with its own start script, then drive real CLI
# requests against it.
#
# This is the check that the bundle is actually usable, not merely well formed.
# It asserts what the bundle promises: it starts with no arguments and no
# environment variables, it serves the folders listed in scopes.txt, the pair
# printed by the packaging step addresses it from the CLI, and the fence still
# refuses an escape.
#
# The script creates its own fixtures and its own bundle, so a run does not
# depend on a previous run's leftovers. Everything it writes lives under
# .tmp/pkgtest, which is git-ignored.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK="$ROOT/.tmp/pkgtest"
BIN="$ROOT/bin"
BUNDLE_NAME="connector-node-linux-amd64"
BUNDLE="$WORK/unzipped/$BUNDLE_NAME"

SHARED="$WORK/shared"
TOOL_DIR="$WORK/tool"

SERVER_LOG="$WORK/server.log"
NODE_LOG="$WORK/node.log"
PACKAGE_LOG="$WORK/package.log"

TUNNEL_TOKEN='pkg-tunnel-token-0123456789'
CLIENT_TOKEN='pkg-client-token-0123456789'

SERVER_PID=""
NODE_PID=""

fail() {
	echo "verify: $*" >&2
	exit 1
}

# stop_all kills exactly the two processes this script started, by PID. It never
# matches on a process name, because a name match would also kill a Server or a
# Node that belongs to another test or to the operator.
stop_all() {
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
	done
}
trap stop_all EXIT

wait_for_log() {
	local file=$1 pattern=$2
	local deadline=$((SECONDS + 30))
	while ((SECONDS < deadline)); do
		if grep -q -- "$pattern" "$file" 2>/dev/null; then
			return 0
		fi
		sleep 0.1
	done
	return 1
}

# free_port asks the kernel for an unused port by binding one and reading it
# back. A fixed port would collide with a Server another test left running, and
# the failure would look like a bundle defect.
free_port() {
	local port
	for port in $(seq 18443 18543); do
		if ! (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
			echo "$port"
			return 0
		fi
	done
	fail "no free port in 18443-18543"
}

# make_fixtures recreates the two folders the bundle will expose. They are
# removed first so a file left by an earlier run cannot make a check pass.
make_fixtures() {
	echo "verify: creating fixtures under $WORK" >&2
	if [ -e "$SHARED" ]; then
		echo "verify: removing the previous fixture $SHARED" >&2
		rm -rf "$SHARED"
	fi
	if [ -e "$TOOL_DIR" ]; then
		echo "verify: removing the previous fixture $TOOL_DIR" >&2
		rm -rf "$TOOL_DIR"
	fi
	if [ -e "$WORK/unzipped" ]; then
		echo "verify: removing the previous unzip target $WORK/unzipped" >&2
		rm -rf "$WORK/unzipped"
	fi
	mkdir -p "$SHARED" "$TOOL_DIR" "$WORK/unzipped"
	printf 'hello from the bundle test\n' >"$SHARED/hello.txt"
	printf 'tool file\n' >"$TOOL_DIR/t.txt"
}

[ -x "$BIN/connector-server" ] || fail "$BIN/connector-server is missing; run make build"

PORT=$(free_port)
make_fixtures

echo "verify: building the bundle" >&2
(
	cd "$ROOT"
	make --no-print-directory package \
		PACKAGE_NAME="$BUNDLE_NAME" \
		PACKAGE_GOOS=linux \
		PACKAGE_GOARCH=amd64 \
		PACKAGE_SERVER_URL="http://127.0.0.1:$PORT" \
		PACKAGE_SCOPES="project=$SHARED tool=$TOOL_DIR" \
		PACKAGE_TUNNEL_TOKEN="$TUNNEL_TOKEN"
) >"$PACKAGE_LOG" 2>&1 || fail "make package failed; see $PACKAGE_LOG"

ZIP="$BIN/$BUNDLE_NAME.zip"
[ -f "$ZIP" ] || fail "$ZIP was not written"

echo "verify: unzipping $ZIP" >&2
unzip -q "$ZIP" -d "$WORK/unzipped" || fail "unzip failed"
[ -x "$BUNDLE/start.sh" ] || fail "$BUNDLE/start.sh is missing or not executable"

echo "verify: starting the Server on 127.0.0.1:$PORT" >&2
: >"$SERVER_LOG"
CONNECTOR_SERVER_LISTEN="127.0.0.1:$PORT" \
	CONNECTOR_SERVER_TUNNEL_TOKEN="$TUNNEL_TOKEN" \
	CONNECTOR_SERVER_CLIENT_TOKEN="$CLIENT_TOKEN" \
	"$BIN/connector-server" run >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!
wait_for_log "$SERVER_LOG" 'msg="server listening"' || fail "the Server did not listen; see $SERVER_LOG"

echo "verify: starting the bundle with its own start script" >&2
: >"$NODE_LOG"
# The bundle is started exactly as a user would start it: no arguments, no
# environment variables, from inside the unzipped folder.
#
# `exec` replaces the subshell with start.sh, which itself execs the Node, so
# $! is the Node's own PID. Without it $! is the subshell, the trap kills the
# subshell, and the Node survives as an orphan that retries forever.
(
	cd "$BUNDLE"
	exec ./start.sh
) >"$NODE_LOG" 2>&1 &
NODE_PID=$!

wait_for_log "$NODE_LOG" 'msg="channel established"' || fail "the bundle did not connect; see $NODE_LOG"

PAIR=$(tr -d '\r\n' <"$BUNDLE/config/identity")
[ -n "$PAIR" ] || fail "the bundle has no identity"

echo "verify: the bundle connected; driving the CLI" >&2

cli() {
	# --node is placed before the operation because Go's flag package stops
	# parsing at the first positional argument. A flag after `file.list` would be
	# read as another positional and the CLI would refuse the invocation.
	CONNECTOR_CLI_SERVER_URL="http://127.0.0.1:$PORT" \
		CONNECTOR_CLI_CLIENT_TOKEN="$CLIENT_TOKEN" \
		"$BIN/connector-server" cli --node "$PAIR" "$@"
}

echo "--- file.list project ---"
cli --scope project --path '' file.list || fail "file.list project failed"

echo "--- file.read project hello.txt ---"
cli --scope project --path hello.txt file.read || fail "file.read project failed"

echo "--- file.list tool ---"
cli --scope tool --path '' file.list || fail "file.list tool failed"

echo "--- file.read tool t.txt ---"
cli --scope tool --path t.txt file.read || fail "file.read tool failed"

echo "--- refusal: a scope the policy does not define ---"
if cli --scope scratch --path '' file.list 2>&1; then
	fail "a scope that is not in scopes.txt was served"
fi
echo "verify: undefined scope refused, as expected"

echo "--- refusal: a traversal path is refused by the grammar ---"
# This exercises the path grammar, not the fence: `..` never reaches the
# filesystem. It is asserted separately from the fence check below so a failure
# names which layer refused the request.
if cli --scope project --path ../config/identity file.read 2>&1; then
	fail "a traversal path was served"
fi
echo "verify: traversal path refused by the grammar, as expected"

echo "--- refusal: a symlink that escapes the scope is refused by the fence ---"
# This is the fence check. The path is a legal name inside the scope, so the
# grammar accepts it; only os.Root can refuse it. A bundle whose fence was
# bypassed would read the identity file here.
ln -sfn "$BUNDLE/config" "$SHARED/escape"
if cli --scope project --path escape/identity file.read 2>&1; then
	fail "a symlink escaping the scope was followed"
fi
echo "verify: escaping symlink refused by the fence, as expected"

echo "--- refusal: file.stat on an alias to the config directory is refused ---"
# The deny list answers by identity, so an alias that resolves to the config
# directory is refused by every operation. Reporting the link with its target
# withheld was the earlier behaviour and it disclosed the layout anyway: a
# symlink's reported size is the length of its target.
if cli --scope project --path escape file.stat 2>&1; then
	fail "file.stat reported an alias to the config directory"
fi
echo "verify: alias to the config directory refused by file.stat, as expected"

echo "--- file.stat reports an escaping symlink without following it ---"
# This link points outside the scope at a directory that is not one of the
# Node's own, so it must be reported as a link rather than refused. It is the
# documented file.stat contract, and the reason Lstat is used rather than Stat.
ln -sfn "$WORK" "$SHARED/outside"
cli --scope project --path outside file.stat || fail "file.stat on an escaping symlink failed"

echo "--- refusal: a bundle reached through a symlink still refuses a scope that contains config ---"
# The start script compares the scope path with the bundle's config directory. Both
# sides must be resolved physically, otherwise a bundle installed behind a symlink
# compares an unresolved path against a resolved one and the guard never matches.
# The scope here is the real bundle directory, which contains config, so a guard
# that compared the wrong forms would start the Node and expose the credentials.
SYMLINKED="$WORK/link"
ln -sfn "$BUNDLE" "$SYMLINKED"
printf 'project=%s\n' "$BUNDLE" >"$SYMLINKED/scopes.txt"
if (cd "$SYMLINKED" && ./start.sh) >"$WORK/symlink.log" 2>&1; then
	fail "a scope containing the bundle's config directory was accepted through a symlink"
fi
grep -q "overlaps the bundle's config directory" "$WORK/symlink.log" ||
	fail "the symlinked-bundle refusal did not name the config overlap"
echo "verify: symlinked bundle refuses a scope containing config, as expected"

echo "--- the filesystem-root opt-in is off unless the operator enabled it ---"
# The opt-in is a security decision made at packaging time, so it is checked on
# the delivery path rather than only in the Node's own tests. Three properties
# matter: a bundle built without the flag refuses a volume root, a bundle built
# with it accepts one and records the decision in the policy, and an
# unrecognised value fails packaging instead of being read as "off".
OPTIN_WORK="$WORK/optin"
rm -rf "$OPTIN_WORK"
mkdir -p "$OPTIN_WORK"

build_optin_bundle() {
	local name="$1"
	local flag="$2"
	(
		cd "$ROOT"
		make --no-print-directory package \
			PACKAGE_NAME="$name" \
			PACKAGE_GOOS=linux \
			PACKAGE_GOARCH=amd64 \
			PACKAGE_SERVER_URL="http://127.0.0.1:$PORT" \
			PACKAGE_SCOPES="root=/" \
			PACKAGE_TUNNEL_TOKEN="$TUNNEL_TOKEN" \
			PACKAGE_ALLOW_FILESYSTEM_ROOT="$flag"
	) >"$OPTIN_WORK/$name.log" 2>&1 || fail "make package $name failed; see $OPTIN_WORK/$name.log"
	unzip -q "$BIN/$name.zip" -d "$OPTIN_WORK/$name" || fail "unzip $name failed"
	echo "$OPTIN_WORK/$name/$name"
}

OFF_BUNDLE=$(build_optin_bundle optin-off "")
[ "$(tr -d '\r\n' <"$OFF_BUNDLE/allow_filesystem_root")" = "0" ] ||
	fail "a bundle built without the flag did not record 0"
if (cd "$OFF_BUNDLE" && CONNECTOR_NODE_TUNNEL_TOKEN="$TUNNEL_TOKEN" ./start.sh) >"$OPTIN_WORK/off.log" 2>&1; then
	fail "a bundle built without the flag accepted a volume root"
fi
grep -q "blast radius is the whole machine" "$OPTIN_WORK/off.log" ||
	fail "the volume-root refusal did not name the blast radius"
echo "verify: a bundle built without the flag refuses a volume root, as expected"

ON_BUNDLE=$(build_optin_bundle optin-on 1)
[ "$(tr -d '\r\n' <"$ON_BUNDLE/allow_filesystem_root")" = "1" ] ||
	fail "a bundle built with the flag did not record 1"
# The Node is started and then stopped: the policy is written before the dial, so
# a short run is enough to prove the scope was accepted. The Server is not
# reachable on this port, which is why the run is bounded rather than waited on.
(cd "$ON_BUNDLE" && CONNECTOR_NODE_TUNNEL_TOKEN="$TUNNEL_TOKEN" timeout 5 ./start.sh) >"$OPTIN_WORK/on.log" 2>&1 || true
grep -q "scope root -> /" "$OPTIN_WORK/on.log" ||
	fail "a bundle built with the flag refused a volume root; see $OPTIN_WORK/on.log"
grep -q "^allow_filesystem_root: true$" "$ON_BUNDLE/config/policy.yaml" ||
	fail "the generated policy does not carry allow_filesystem_root: true"
echo "verify: a bundle built with the flag accepts a volume root and records it in the policy"

# The home-directory refusal is never skipped, because the Node refuses it
# unconditionally. A bundle that allowed it would fail on the user's machine
# instead of at start.
printf 'home=%s\n' "$HOME" >"$ON_BUNDLE/scopes.txt"
if (cd "$ON_BUNDLE" && CONNECTOR_NODE_TUNNEL_TOKEN="$TUNNEL_TOKEN" ./start.sh) >"$OPTIN_WORK/home.log" 2>&1; then
	fail "the opt-in also allowed the home directory"
fi
grep -q "blast radius is every file you own" "$OPTIN_WORK/home.log" ||
	fail "the home-directory refusal did not fire under the opt-in"
echo "verify: the opt-in does not allow the home directory"

if (
	cd "$ROOT"
	make --no-print-directory package \
		PACKAGE_NAME=optin-bad \
		PACKAGE_GOOS=linux \
		PACKAGE_GOARCH=amd64 \
		PACKAGE_SERVER_URL="http://127.0.0.1:$PORT" \
		PACKAGE_SCOPES="root=/" \
		PACKAGE_ALLOW_FILESYSTEM_ROOT=true
) >"$OPTIN_WORK/bad.log" 2>&1; then
	fail "an unrecognised PACKAGE_ALLOW_FILESYSTEM_ROOT value was accepted"
fi
grep -q "PACKAGE_ALLOW_FILESYSTEM_ROOT 'true' is not recognised" "$OPTIN_WORK/bad.log" ||
	fail "the unrecognised-value refusal did not name the flag"
echo "verify: an unrecognised opt-in value fails packaging"

echo "verify: all bundle checks passed"
