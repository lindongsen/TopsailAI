#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Prove on a real Windows host that a deeply nested tree is readable
# through two real processes, and that depth does not weaken the fence.
#
# The Linux script (deep_nesting.sh) cannot exercise the Windows path rules: the
# grammar is shared but the filesystem ceiling is not, and wine is not a
# substitute because it resolves paths through the Linux filesystem. This script
# therefore runs against a Windows Node reached over the network, and it is
# driven from a host that can reach both the Server and the Windows machine.
#
# It is not part of `make check`, because it needs a Windows host. Run it by hand
# when a Windows Node is available, and record the output in the issue or the
# design document.
#
# Every request goes through `connector-server cli`, which signs both proofs. The
# script does not build a proof itself: a second implementation of the signing
# grammar would be a second definition of a valid proof, and the two would
# eventually disagree about a field. The CLI also does not validate the path
# before sending it, so the refusals this script asserts are the Node's answers
# rather than the CLI's.
#
# Environment:
#   WIN_NODE_ID           the Windows Node's node id
#   WIN_NODE_CREDENTIAL   the Node credential the CLI presents, as key_id.secret
#   WIN_CLIENT_CREDENTIAL the Server credential the CLI presents, as key_id.secret
#   WIN_SERVER_URL        the Server's CLI API base, default http://127.0.0.1:8443
#
# Both credentials are the `key_id.secret` strings the operator copied from
# `connector-node credential add` and from the Server's credential file. The secret
# half is what signs; the key id half selects which secret the verifier uses. A
# credential is not a bearer token: it never travels, so a captured request yields
# nothing reusable.
#
# The deep tree and the junction must already exist on the Windows host; the
# companion PowerShell scripts are mkdeep.ps1 and mkjunc.ps1 in this folder.

set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BIN="$ROOT/bin"

NODE_ID="${WIN_NODE_ID:?WIN_NODE_ID is required}"
NODE_CREDENTIAL="${WIN_NODE_CREDENTIAL:?WIN_NODE_CREDENTIAL is required}"
CLIENT_CREDENTIAL="${WIN_CLIENT_CREDENTIAL:?WIN_CLIENT_CREDENTIAL is required}"
BASE="${WIN_SERVER_URL:-http://127.0.0.1:8443}"

# The deepest level the Windows filesystem accepted when the tree was built.
CEILING="${WIN_DEPTH_CEILING:-114}"

pass=0
fail=0

[ -x "$BIN/connector-server" ] || {
	echo "win-deep: $BIN/connector-server is missing; run make build" >&2
	exit 1
}

# cli runs one operation through the real CLI, so both proofs are built by the
# implementation under test rather than by this script.
cli() {
	"$BIN/connector-server" cli \
		--server "$BASE" \
		--client-credential "$CLIENT_CREDENTIAL" \
		--node-credential "$NODE_CREDENTIAL" \
		--node-id "$NODE_ID" \
		"$@"
}

# deep_file prints a relative path of $1 levels, each component "d", ending in
# f.txt. The trailing component is the file, so the path names a file at depth $1.
deep_file() {
	local n=$1 out="" i
	for ((i = 0; i < n; i++)); do out="${out}d/"; done
	printf '%s' "${out}f.txt"
}

# deep_dir prints a relative path of $1 levels with no trailing separator, so it
# names the directory at that depth. A trailing separator would create an empty
# component, which the grammar refuses.
deep_dir() {
	local n=$1 out="" i
	for ((i = 0; i < n; i++)); do
		[ "$i" -gt 0 ] && out="${out}/"
		out="${out}d"
	done
	printf '%s' "$out"
}

# check runs one assertion and records the outcome. The label names the property,
# so a failure says which property broke rather than which command ran.
check() {
	local label=$1
	shift
	if "$@"; then
		echo "win-deep: PASS $label"
		pass=$((pass + 1))
	else
		echo "win-deep: FAIL $label"
		fail=$((fail + 1))
	fi
}

# check_read asserts the file at one depth returns the payload that depth was
# written with. Comparing the content rather than the status code is what makes a
# successful open returning the wrong file a failure.
check_read() {
	local depth=$1 rel want got
	rel=$(deep_file "$depth")
	want="payload-at-$depth"
	got=$(cli --scope project --path "$rel" file.read 2>&1) || {
		echo "win-deep:   depth $depth file.read failed: $got" >&2
		return 1
	}
	if [ "$got" != "$want" ]; then
		echo "win-deep:   depth $depth file.read returned $(printf '%q' "$got"), want $(printf '%q' "$want")" >&2
		return 1
	fi
	return 0
}

# check_stat asserts stat succeeds at one depth.
check_stat() {
	local depth=$1 rel got
	rel=$(deep_file "$depth")
	got=$(cli --scope project --path "$rel" file.stat 2>&1) || {
		echo "win-deep:   depth $depth file.stat failed: $got" >&2
		return 1
	}
	return 0
}

# check_list asserts list succeeds at one depth and reports the file.
check_list() {
	local depth=$1 dir got
	dir=$(deep_dir "$depth")
	got=$(cli --scope project --path "$dir" file.list 2>&1) || {
		echo "win-deep:   depth $depth file.list failed: $got" >&2
		return 1
	}
	case "$got" in
	*f.txt*) ;;
	*)
		echo "win-deep:   depth $depth file.list returned $(printf '%q' "$got"), want an entry named f.txt" >&2
		return 1
		;;
	esac
	return 0
}

# check_past_ceiling asserts one level past the filesystem ceiling is not_found.
#
# The kernel reports an over-long path as missing, so the refusal is not_found
# rather than invalid_argument. Asserting the code the implementation actually
# produces keeps the script from demanding a classification the design does not
# promise.
check_past_ceiling() {
	local depth=$((CEILING + 1)) rel got
	rel=$(deep_file "$depth")
	if got=$(cli --scope project --path "$rel" file.read 2>&1); then
		echo "win-deep:   depth $depth was read: $got" >&2
		return 1
	fi
	case "$got" in
	*not_found*) ;;
	*)
		echo "win-deep:   depth $depth reported $(printf '%q' "$got"), want not_found" >&2
		return 1
		;;
	esac
	return 0
}

# check_junction_refused asserts a junction at depth 20 pointing at the Node's own
# config directory is refused for a read.
check_junction_refused() {
	local dir got
	dir=$(deep_dir 20)
	if got=$(cli --scope project --path "${dir}/escape/identity" file.read 2>&1); then
		echo "win-deep:   a junction at depth was read: $got" >&2
		return 1
	fi
	case "$got" in
	*denied*) ;;
	*)
		echo "win-deep:   a junction at depth reported $(printf '%q' "$got"), want denied" >&2
		return 1
		;;
	esac
	return 0
}

# check_junction_stat asserts stat refuses the junction rather than reporting it.
#
# mkjunc.ps1 points the junction at the Node's own config directory, and the deny
# list answers by identity: a link that resolves to a denied directory is refused
# by every operation, including file.stat. Reporting the link instead would
# disclose the layout, because a symlink's reported size is the length of its
# target.
#
# An escaping junction that does not resolve to a denied directory is a different
# case and is still reported as a link without being followed. That case is
# covered by the Linux script, where the escape target is an ordinary directory.
check_junction_stat() {
	local dir got
	dir=$(deep_dir 20)
	if got=$(cli --scope project --path "${dir}/escape" file.stat 2>&1); then
		echo "win-deep:   file.stat on a junction to the config directory succeeded: $got" >&2
		return 1
	fi
	case "$got" in
	*denied*) ;;
	*)
		echo "win-deep:   file.stat on a junction to the config directory reported $(printf '%q' "$got"), want denied" >&2
		return 1
		;;
	esac
	return 0
}

# check_over_long asserts a path over the grammar limit is refused as
# invalid_argument before it reaches the filesystem.
check_over_long() {
	local long got
	long=$(printf 'a%.0s' $(seq 1 5000))
	if got=$(cli --scope project --path "$long" file.read 2>&1); then
		echo "win-deep:   an over-long path was read: $got" >&2
		return 1
	fi
	case "$got" in
	*invalid_argument*) ;;
	*)
		echo "win-deep:   an over-long path reported $(printf '%q' "$got"), want invalid_argument" >&2
		return 1
		;;
	esac
	return 0
}

# check_traversal asserts a traversal at depth is refused as invalid_argument.
check_traversal() {
	local dir got
	dir=$(deep_dir 20)
	if got=$(cli --scope project --path "${dir}/../../../../../../../../../../../../../../../../../../../../f.txt" file.read 2>&1); then
		echo "win-deep:   a traversal at depth was read: $got" >&2
		return 1
	fi
	case "$got" in
	*invalid_argument*) ;;
	*)
		echo "win-deep:   a traversal at depth reported $(printf '%q' "$got"), want invalid_argument" >&2
		return 1
		;;
	esac
	return 0
}

# depths prints each distinct depth once, so a ceiling that repeats a value
# already in the list is not asserted twice. A duplicate would inflate the pass
# count and make the summary claim more coverage than the run had.
depths() {
	local d seen=" "
	for d in "$@"; do
		case "$seen" in
		*" $d "*) continue ;;
		esac
		seen="$seen$d "
		printf '%s\n' "$d"
	done
}

echo "=== read at increasing depth ==="
while read -r depth; do
	check "depth $depth read" check_read "$depth"
done < <(depths 1 2 3 5 10 20 50 100 "$CEILING")

echo "=== stat at depth ==="
while read -r depth; do
	check "depth $depth stat" check_stat "$depth"
done < <(depths 1 20 100 "$CEILING")

echo "=== list at depth ==="
while read -r depth; do
	check "depth $depth list" check_list "$depth"
done < <(depths 1 20 100 "$CEILING")

echo "=== one level past the ceiling ==="
check "depth $((CEILING + 1)) not_found" check_past_ceiling

echo "=== junction at depth escapes the scope ==="
check "junction at depth refused" check_junction_refused

echo "=== junction at depth is refused by stat too ==="
check "junction at depth stat refused" check_junction_stat

echo "=== over-long path ==="
check "over-long path refused as invalid_argument" check_over_long

echo "=== traversal at depth ==="
check "traversal at depth refused" check_traversal

echo "win-deep: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
