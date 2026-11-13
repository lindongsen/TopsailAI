#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Assemble a distributable Node bundle for the Makefile's `package`
# target: one zip that a user unzips and starts, and that the operator can
# address with the CLI immediately.
#
# Three decisions shape this script, and each one exists because the obvious
# alternative does not work:
#
#   - The scope paths are NOT baked into a policy file here. A policy requires
#     absolute paths, and the packaging machine's paths are not the user's
#     paths. The bundle therefore carries a human-editable `scopes.txt` and the
#     start script turns it into `policy.yaml` on the machine that will serve it.
#   - The identity pair IS generated here, with the Node's own `id` command. If
#     the Node generated it on the user's machine, the operator would have to ask
#     the user to read the pair back before the CLI could address the Node, which
#     defeats the point of handing over a bundle.
#   - The tunnel token is written to a 0600 file that the start script exports as
#     the documented environment variable. The Node still reads the token from
#     the environment; the file is the operator's provisioning store, the same
#     shape as a systemd `EnvironmentFile=`.
#
# The bundle is a credential bundle. It carries the Node's identity pair and,
# when the operator supplies one, the tunnel token. That is stated in the bundle
# README and in the summary this script prints, rather than left to be
# discovered.
#
# Every input arrives as an environment variable from the Makefile, so the
# Makefile stays the single place a caller looks for the knobs.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

PACKAGE_NAME=${PACKAGE_NAME:-}
PACKAGE_GOOS=${PACKAGE_GOOS:-}
PACKAGE_GOARCH=${PACKAGE_GOARCH:-}
PACKAGE_SERVER_URL=${PACKAGE_SERVER_URL:-}
PACKAGE_SCOPES=${PACKAGE_SCOPES:-}
PACKAGE_SCOPES_FILE=${PACKAGE_SCOPES_FILE:-}
PACKAGE_TUNNEL_TOKEN=${PACKAGE_TUNNEL_TOKEN:-}
PACKAGE_ALLOW_FILESYSTEM_ROOT=${PACKAGE_ALLOW_FILESYSTEM_ROOT:-}
BIN_DIR=${BIN_DIR:-bin}
TMP_DIR=${TMP_DIR:-.tmp}

fail() {
	echo "package: $*" >&2
	exit 1
}

# absolute turns a possibly relative directory into an absolute one, so every
# path this script prints can be pasted into another shell.
absolute() {
	local value=$1
	case "$value" in
	/*) echo "$value" ;;
	*) echo "$ROOT/$value" ;;
	esac
}

BIN_PATH=$(absolute "$BIN_DIR")
TMP_PATH=$(absolute "$TMP_DIR")

# normalize_channel_url turns whatever the operator typed into the WebSocket
# address the Node dials.
#
# The Node validates the scheme at startup and refuses anything that is not
# `ws` or `wss`, so an operator who pastes the HTTP address they use for the CLI
# gets a startup failure on the user's machine instead of a bundle that works.
# Accepting the HTTP form here and converting it is the difference between a
# bundle that starts and one that fails on the user's first attempt.
normalize_channel_url() {
	local value=$1
	local scheme rest host path

	case "$value" in
	ws://*) scheme=ws; rest=${value#ws://} ;;
	wss://*) scheme=wss; rest=${value#wss://} ;;
	http://*) scheme=ws; rest=${value#http://} ;;
	https://*) scheme=wss; rest=${value#https://} ;;
	*) fail "PACKAGE_SERVER_URL '$value' is not an http, https, ws or wss URL" ;;
	esac

	host=${rest%%/*}
	if [ "$host" = "$rest" ]; then
		path=""
	else
		path="/${rest#*/}"
	fi

	[ -n "$host" ] || fail "PACKAGE_SERVER_URL '$value' has no host"
	case "$host" in
	*" "*) fail "PACKAGE_SERVER_URL '$value' has a space in the host" ;;
	esac

	if [ -z "$path" ] || [ "$path" = "/" ]; then
		path=/channel
	fi

	echo "$scheme://$host$path"
}

# http_base_from_channel derives the CLI's base URL from the channel URL, so the
# summary can print a command the operator can paste without editing.
http_base_from_channel() {
	local value=$1
	local scheme=${value%%://*}
	local rest=${value#*://}
	local host=${rest%%/*}

	case "$scheme" in
	wss) echo "https://$host" ;;
	ws) echo "http://$host" ;;
	*) fail "internal: '$value' is not a channel URL" ;;
	esac
}

# validate_scope_name applies the Node's own scope-name rule at packaging time.
#
# The rule is a whitelist: letters, digits, `-` and `_`, and the first character
# must not be `-` or `_`. Checking it here means a typo fails while the operator
# is still looking at the command, instead of on the user's machine at startup
# where the error is far from the person who can fix it.
validate_scope_name() {
	local name=$1
	[ -n "$name" ] || fail "a scope entry has an empty name; write name=path"
	[ "${#name}" -le 64 ] || fail "scope name '$name' is longer than 64 bytes"
	case "$name" in
	[A-Za-z0-9]*) ;;
	*) fail "scope name '$name' must start with a letter or a digit" ;;
	esac
	case "$name" in
	*[!A-Za-z0-9_-]*) fail "scope name '$name' may contain only letters, digits, '-' and '_'" ;;
	esac
}

[ -n "$PACKAGE_NAME" ] || fail "PACKAGE_NAME is empty"
[ -n "$PACKAGE_GOOS" ] || fail "PACKAGE_GOOS is empty"
[ -n "$PACKAGE_GOARCH" ] || fail "PACKAGE_GOARCH is empty"
[ -n "$PACKAGE_SERVER_URL" ] || fail "PACKAGE_SERVER_URL is required; pass the Server address, for example https://connector.example.com:8443"
[ -n "$PACKAGE_SCOPES$PACKAGE_SCOPES_FILE" ] ||
	fail "PACKAGE_SCOPES is required; pass one or more name=path entries, for example PACKAGE_SCOPES='project=/home/me/project tool=/opt/tool'"

# PACKAGE_ALLOW_FILESYSTEM_ROOT is a security decision, so it accepts exactly two
# spellings and refuses everything else. A value such as `true`, `yes` or `1 ` that
# was silently treated as "off" would produce a bundle that refuses the volume root
# the operator asked for, and the operator would debug the scope path instead of
# the flag. Refusing an unrecognised value names the flag.
case "$PACKAGE_ALLOW_FILESYSTEM_ROOT" in
'' | 0) ALLOW_FILESYSTEM_ROOT=0 ;;
1) ALLOW_FILESYSTEM_ROOT=1 ;;
*)
	fail "PACKAGE_ALLOW_FILESYSTEM_ROOT '$PACKAGE_ALLOW_FILESYSTEM_ROOT' is not recognised; use 1 to allow a volume root, or leave it unset"
	;;
esac

CHANNEL_URL=$(normalize_channel_url "$PACKAGE_SERVER_URL")
HTTP_BASE=$(http_base_from_channel "$CHANNEL_URL")

# The identity is generated by the host build of the Node, because a binary
# cross-compiled for another platform cannot run here. The identity file format
# is platform independent, so a pair generated on this host is valid on the
# target: it is two random strings and a newline.
HOST_NODE="$BIN_PATH/connector-node"
[ -x "$HOST_NODE" ] || fail "$HOST_NODE is missing; run make build-node first"

STAGE_PARENT="$TMP_PATH/package"
STAGE="$STAGE_PARENT/$PACKAGE_NAME"
ZIP_PATH="$BIN_PATH/$PACKAGE_NAME.zip"

# A stale stage directory would let a previous bundle's identity answer for this
# one, which is the kind of mistake that surfaces as an authentication failure
# nobody can explain. The removal is logged because a silent delete is
# indistinguishable from a directory that was never there.
if [ -e "$STAGE" ]; then
	echo "package: removing the previous stage directory $STAGE" >&2
	rm -rf "$STAGE"
fi
mkdir -p "$STAGE/config" "$BIN_PATH"

echo "package: building connector-node for $PACKAGE_GOOS/$PACKAGE_GOARCH" >&2
NODE_BINARY=connector-node
if [ "$PACKAGE_GOOS" = "windows" ]; then
	NODE_BINARY=connector-node.exe
fi
(
	cd "$ROOT"
	GOOS="$PACKAGE_GOOS" GOARCH="$PACKAGE_GOARCH" go build -o "$STAGE/$NODE_BINARY" ./cmd/connector-node
)

# The pair is generated with the Node's own command rather than by a second
# implementation here. A second implementation would be a second definition of
# the pair format, and the two would eventually disagree.
echo "package: generating the node identity" >&2
PAIR=$(CONNECTOR_NODE_CONFIG_DIR="$STAGE/config" "$HOST_NODE" id)
[ -n "$PAIR" ] || fail "the Node printed no identity"
[ -f "$STAGE/config/identity" ] || fail "the Node did not write $STAGE/config/identity"

# scopes.txt is the bundle's editable surface. It is written from the command
# line when the operator knows the target paths, and from a file when the paths
# contain spaces or when the list is long.
SCOPES_OUT="$STAGE/scopes.txt"
if [ -n "$PACKAGE_SCOPES_FILE" ]; then
	[ -f "$PACKAGE_SCOPES_FILE" ] || fail "PACKAGE_SCOPES_FILE '$PACKAGE_SCOPES_FILE' does not exist"
	cp "$PACKAGE_SCOPES_FILE" "$SCOPES_OUT"
else
	: >"$SCOPES_OUT"
	SEEN_NAMES=" "
	for entry in $PACKAGE_SCOPES; do
		case "$entry" in
		*=*) ;;
		*) fail "scope entry '$entry' is not name=path" ;;
		esac
		name=${entry%%=*}
		path=${entry#*=}
		validate_scope_name "$name"
		[ -n "$path" ] || fail "scope '$name' has an empty path"
		case "$SEEN_NAMES" in
		*" $name "*) fail "scope '$name' is listed twice" ;;
		esac
		SEEN_NAMES="$SEEN_NAMES$name "
		printf '%s=%s\n' "$name" "$path" >>"$SCOPES_OUT"
	done
fi

# The scope list is validated once more after it is written, so a file supplied
# through PACKAGE_SCOPES_FILE gets the same check as a list typed on the command
# line. A bundle whose scopes.txt is unusable is a bundle that fails on the
# user's machine, which is the failure this check exists to move earlier.
SCOPE_COUNT=0
while IFS= read -r line || [ -n "$line" ]; do
	trimmed=$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
	case "$trimmed" in
	''|'#'*) continue ;;
	esac
	case "$trimmed" in
	*=*) ;;
	*) fail "scopes.txt line '$trimmed' is not name=path" ;;
	esac
	validate_scope_name "${trimmed%%=*}"
	[ -n "${trimmed#*=}" ] || fail "scopes.txt scope '${trimmed%%=*}' has an empty path"
	SCOPE_COUNT=$((SCOPE_COUNT + 1))
done <"$SCOPES_OUT"
[ "$SCOPE_COUNT" -gt 0 ] || fail "scopes.txt defines no scope; a bundle that exposes nothing serves nothing"

# server_url is a file rather than a value baked into the start script, so the
# user can point the bundle at a different Server without editing a script.
printf '%s\n' "$CHANNEL_URL" >"$STAGE/server_url"

# The opt-in is recorded in the bundle as a file rather than baked into the start
# script, for the same reason server_url is: the start script is a copy of a
# repository file, and a value baked into it would be lost the next time the
# script is updated. The file always exists and always holds 0 or 1, so "the
# operator did not enable it" is a recorded decision rather than a missing file
# that a later reader has to interpret.
printf '%s\n' "$ALLOW_FILESYSTEM_ROOT" >"$STAGE/allow_filesystem_root"

if [ -n "$PACKAGE_TUNNEL_TOKEN" ]; then
	printf '%s\n' "$PACKAGE_TUNNEL_TOKEN" >"$STAGE/config/tunnel_token"
	chmod 600 "$STAGE/config/tunnel_token"
else
	echo "package: no PACKAGE_TUNNEL_TOKEN given; the bundle will require CONNECTOR_NODE_TUNNEL_TOKEN in the environment" >&2
fi

cp "$ROOT/packaging/start.sh" "$STAGE/start.sh"
cp "$ROOT/packaging/start.ps1" "$STAGE/start.ps1"
cp "$ROOT/packaging/bundle-README.md" "$STAGE/README.md"
chmod +x "$STAGE/start.sh"

echo "package: writing $ZIP_PATH" >&2
rm -f "$ZIP_PATH"
(
	cd "$STAGE_PARENT"
	zip -r -q "$ZIP_PATH" "$PACKAGE_NAME"
)

FIRST_SCOPE=$(sed -n 's/^[[:space:]]*\([A-Za-z0-9][A-Za-z0-9_-]*\)=.*/\1/p' "$SCOPES_OUT" | head -1)

cat <<SUMMARY

package: wrote $ZIP_PATH
package: platform $PACKAGE_GOOS/$PACKAGE_GOARCH, scopes $SCOPE_COUNT, channel $CHANNEL_URL
package: filesystem root opt-in $ALLOW_FILESYSTEM_ROOT (0 means a volume root is refused)

The bundle carries a credential. Hand it over the way you would hand over a
password, and regenerate the pair if it leaks.

node pair (copy this whole value into the CLI):

  $PAIR
CLI example, runnable as soon as the user starts the bundle. The flags come
before the operation because the CLI stops parsing flags at the first positional
argument, so the operation must be last:

  CONNECTOR_CLI_SERVER_URL=$HTTP_BASE \\
  CONNECTOR_CLI_CLIENT_TOKEN=<client_token> \\
    connector-server cli --node '$PAIR' --scope $FIRST_SCOPE --path '' file.list

SUMMARY
