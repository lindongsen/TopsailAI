#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Start the Node from an unpacked bundle, on Linux or macOS.
#
# The bundle is self-contained: the binary, the identity, the Server address and
# the scope list all sit next to this script. Starting it is one command, and the
# operator can address the Node with the CLI as soon as it connects.
#
# This script exists because a policy file requires absolute paths and the
# packaging machine's paths are not the user's paths. The bundle therefore ships
# a human-editable `scopes.txt` and this script turns it into `policy.yaml` on the
# machine that will actually serve the files. Editing `scopes.txt` and restarting
# is the whole configuration workflow.
#
# Every refusal below is a refusal the Node would also make, moved earlier so the
# message appears next to the person who can fix it. The one exception is the
# config-directory overlap check, which the Node does not yet perform; it is
# enforced here because the bundle keeps its credentials inside its own folder,
# which is exactly the layout that check exists to refuse.

set -euo pipefail

# HERE is resolved physically, not logically. The scope paths below are resolved
# with `pwd -P`, so a logical HERE would compare a symlinked bundle path against a
# physical scope path and the config-overlap guard would never match. A bundle
# reached through a symlink is a normal way to install one, so the two sides of
# that comparison must be in the same form.
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
CONFIG_DIR="$HERE/config"
POLICY="$CONFIG_DIR/policy.yaml"
SCOPES="$HERE/scopes.txt"
SERVER_URL_FILE="$HERE/server_url"
TOKEN_FILE="$CONFIG_DIR/tunnel_token"

fail() {
	echo "start: $*" >&2
	exit 1
}

[ -x "$HERE/connector-node" ] || fail "$HERE/connector-node is missing or not executable"
[ -f "$SCOPES" ] || fail "$SCOPES is missing; it lists the folders this Node exposes"
[ -f "$SERVER_URL_FILE" ] || fail "$SERVER_URL_FILE is missing; it holds the Server address"
mkdir -p "$CONFIG_DIR"

SERVER_URL=$(tr -d '\r\n' <"$SERVER_URL_FILE")
[ -n "$SERVER_URL" ] || fail "$SERVER_URL_FILE is empty"

# The tunnel token comes from the bundle when the operator provisioned one, and
# from the environment otherwise. It is never echoed: the only thing printed is
# whether it was found, because a token in a terminal is a token in a scrollback
# buffer.
if [ -f "$TOKEN_FILE" ]; then
	TUNNEL_TOKEN=$(tr -d '\r\n' <"$TOKEN_FILE")
else
	TUNNEL_TOKEN=${CONNECTOR_NODE_TUNNEL_TOKEN:-}
fi
[ -n "$TUNNEL_TOKEN" ] ||
	fail "no tunnel token: the bundle has no config/tunnel_token and CONNECTOR_NODE_TUNNEL_TOKEN is unset"

# resolve_scope_path turns one entry into an absolute path.
#
# A relative path is resolved against the bundle directory rather than refused.
# The Node refuses a relative path because it would resolve against whatever
# directory the process inherited, which differs per launch; resolving against
# the bundle directory is deterministic, because the bundle directory is fixed by
# where the user unzipped it. The resolved value is printed so the user can see
# what the entry became instead of having to infer it.
resolve_scope_path() {
	local value=$1
	case "$value" in
	/*) echo "$value" ;;
	*) echo "$HERE/$value" ;;
	esac
}

# is_within reports whether the first path is the second path or sits inside it.
is_within() {
	local child=$1 parent=$2
	case "$child" in
	"$parent"|"$parent"/*) return 0 ;;
	*) return 1 ;;
	esac
}

# write_policy rebuilds policy.yaml from scopes.txt.
#
# The file is rebuilt on every start rather than merged, so scopes.txt is the
# only source of truth and a scope removed from it stops being served. A policy
# that accumulated entries across restarts would be a policy nobody could read
# back from the file they edited.
write_policy() {
	local temporary="$POLICY.tmp"
	local count=0
	local line trimmed name path resolved

	{
		echo "version: 1"
		echo "scopes:"
	} >"$temporary"

	local grants=""
	while IFS= read -r line || [ -n "$line" ]; do
		trimmed=$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
		case "$trimmed" in
		''|'#'*) continue ;;
		esac
		case "$trimmed" in
		*=*) ;;
		*) fail "scopes.txt line '$trimmed' is not name=path" ;;
		esac

		name=${trimmed%%=*}
		path=${trimmed#*=}
		[ -n "$path" ] || fail "scope '$name' has an empty path"

		# The scope name rule is the Node's own whitelist. It is repeated here
		# because scopes.txt is edited after packaging, so a name that was valid
		# when the bundle was built can be broken by the user.
		case "$name" in
		[A-Za-z0-9]*) ;;
		*) fail "scope name '$name' must start with a letter or a digit" ;;
		esac
		case "$name" in
		*[!A-Za-z0-9_-]*) fail "scope name '$name' may contain only letters, digits, '-' and '_'" ;;
		esac

		resolved=$(resolve_scope_path "$path")
		[ -d "$resolved" ] || fail "scope '$name' path '$resolved' is not a directory on this machine"
		resolved=$(cd "$resolved" && pwd -P)

		# The Node refuses these at startup. Checking them here names the scope
		# and the reason, which a startup failure from inside the binary does
		# not do as clearly.
		[ "$resolved" != "/" ] || fail "scope '$name' is '/', whose blast radius is the whole machine"
		[ "$resolved" != "${HOME:-/nonexistent}" ] ||
			fail "scope '$name' is the home directory, whose blast radius is every file you own"

		# The bundle keeps its credentials in ./config. A scope that contains
		# that directory lets a caller list the names and sizes of the identity
		# and policy files, so the overlap is refused rather than denied per
		# request.
		if is_within "$resolved" "$CONFIG_DIR" || is_within "$CONFIG_DIR" "$resolved"; then
			fail "scope '$name' path '$resolved' overlaps the bundle's config directory $CONFIG_DIR; move the folder or the bundle"
		fi

		# The path is written as a double-quoted YAML scalar. A plain scalar
		# breaks on a path containing ' #', ': ' or a leading special character,
		# and a policy that fails to parse is a Node that refuses to start on the
		# user's machine. Backslashes and double quotes are escaped because a
		# Windows path reaches this file when the bundle is edited on Windows.
		escaped=${resolved//\\/\\\\}
		escaped=${escaped//\"/\\\"}
		printf '  %s:\n    path: "%s"\n' "$name" "$escaped" >>"$temporary"
		grants="$grants  - scope: $name
    permissions: [read, list, stat]
"
		count=$((count + 1))
		echo "start: scope $name -> $resolved" >&2
	done <"$SCOPES"

	[ "$count" -gt 0 ] || fail "scopes.txt defines no scope; a Node that exposes nothing serves nothing"

	{
		echo "grants:"
		printf '%s' "$grants"
	} >>"$temporary"

	chmod 600 "$temporary"
	mv "$temporary" "$POLICY"
}

write_policy

echo "start: server $SERVER_URL" >&2
echo "start: config $CONFIG_DIR" >&2

# The four variables are the documented Node surface. The token is exported here
# and nowhere else, so the Node reads it from the environment exactly as
# docs/Environment_Variables.md describes, and the bundle does not introduce a
# second configuration mechanism.
export CONNECTOR_NODE_SERVER_URL="$SERVER_URL"
export CONNECTOR_NODE_TUNNEL_TOKEN="$TUNNEL_TOKEN"
export CONNECTOR_NODE_CONFIG_DIR="$CONFIG_DIR"
export CONNECTOR_NODE_POLICY_FILE="$POLICY"

exec "$HERE/connector-node" run
