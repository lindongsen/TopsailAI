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
# Environment:
#   WIN_NODE_ID     the node-id half of the Windows Node's pair
#   WIN_NODE_TOKEN  the node-token half
#   WIN_CLIENT_TOKEN the Server's client_token
#   WIN_SERVER_URL  the Server's CLI API base, default http://127.0.0.1:8443
#
# The deep tree and the junction must already exist on the Windows host; the
# companion PowerShell scripts are mkdeep.ps1 and mkjunc.ps1 in this folder.

set -uo pipefail

NODE_ID="${WIN_NODE_ID:?WIN_NODE_ID is required}"
NODE_TOKEN="${WIN_NODE_TOKEN:?WIN_NODE_TOKEN is required}"
CLIENT_TOKEN="${WIN_CLIENT_TOKEN:?WIN_CLIENT_TOKEN is required}"
BASE="${WIN_SERVER_URL:-http://127.0.0.1:8443}"

# The deepest level the Windows filesystem accepted when the tree was built.
CEILING="${WIN_DEPTH_CEILING:-114}"

pass=0
fail=0

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

# call posts one operation and prints the response body.
call() {
	local op=$1 scope=$2 path=$3
	curl -s -X POST "$BASE/v1/nodes/$NODE_ID/operations" \
		-H "Authorization: Bearer $CLIENT_TOKEN" \
		-H "X-Connector-Node-Token: $NODE_TOKEN" \
		-H "Content-Type: application/json" \
		-d "{\"operation\":\"$op\",\"scope\":\"$scope\",\"path\":\"$path\"}"
}

# field prints a numeric field from a flat JSON body.
field() {
	printf '%s' "$1" | sed -n "s/.*\"$2\":\([0-9]*\).*/\1/p" | head -1
}

# content decodes data.content, which is base64. Comparing the decoded bytes
# rather than the status code is what makes a wrong-file success a failure.
content() {
	printf '%s' "$1" | sed -n 's/.*"content":"\([^"]*\)".*/\1/p' | head -1 | base64 -d 2>/dev/null
}

echo "=== read at increasing depth ==="
for depth in 1 2 3 5 10 20 50 100 "$CEILING"; do
	p=$(deep_file "$depth")
	body=$(call file.read project "$p")
	code=$(field "$body" code)
	got=$(content "$body")
	want="payload-at-$depth"
	if [ "$code" = "0" ] && [ "$got" = "$want" ]; then
		echo "win-deep: PASS depth $depth read content=$got"
		pass=$((pass + 1))
	else
		echo "win-deep: FAIL depth $depth code=$code got=$got want=$want"
		fail=$((fail + 1))
	fi
done

echo "=== stat at depth ==="
for depth in 1 20 100 "$CEILING"; do
	p=$(deep_file "$depth")
	body=$(call file.stat project "$p")
	code=$(field "$body" code)
	if [ "$code" = "0" ]; then
		echo "win-deep: PASS depth $depth stat"
		pass=$((pass + 1))
	else
		echo "win-deep: FAIL depth $depth stat code=$code"
		fail=$((fail + 1))
	fi
done

echo "=== list at depth ==="
for depth in 1 20 100 "$CEILING"; do
	p=$(deep_dir "$depth")
	body=$(call file.list project "$p")
	code=$(field "$body" code)
	if [ "$code" = "0" ]; then
		echo "win-deep: PASS depth $depth list"
		pass=$((pass + 1))
	else
		echo "win-deep: FAIL depth $depth list code=$code"
		fail=$((fail + 1))
	fi
done

echo "=== one level past the ceiling ==="
p=$(deep_file $((CEILING + 1)))
body=$(call file.read project "$p")
code=$(field "$body" code)
if [ "$code" = "1006" ]; then
	echo "win-deep: PASS depth $((CEILING + 1)) not_found"
	pass=$((pass + 1))
else
	echo "win-deep: FAIL depth $((CEILING + 1)) code=$code want=1006"
	fail=$((fail + 1))
fi

echo "=== junction at depth escapes the scope ==="
p=$(deep_dir 20)
body=$(call file.read project "${p}/escape/identity")
code=$(field "$body" code)
if [ "$code" = "1005" ]; then
	echo "win-deep: PASS junction at depth refused"
	pass=$((pass + 1))
else
	echo "win-deep: FAIL junction at depth code=$code want=1005"
	fail=$((fail + 1))
fi

echo "=== junction at depth is reported without being followed ==="
body=$(call file.stat project "${p}/escape")
code=$(field "$body" code)
if [ "$code" = "0" ]; then
	echo "win-deep: PASS junction at depth stat reports the link"
	pass=$((pass + 1))
else
	echo "win-deep: FAIL junction at depth stat code=$code"
	fail=$((fail + 1))
fi

echo "=== over-long path ==="
long=$(printf 'a%.0s' $(seq 1 5000))
body=$(call file.read project "$long")
code=$(field "$body" code)
if [ "$code" = "1001" ]; then
	echo "win-deep: PASS over-long path refused as invalid_argument"
	pass=$((pass + 1))
else
	echo "win-deep: FAIL over-long path code=$code want=1001"
	fail=$((fail + 1))
fi

echo "=== traversal at depth ==="
p=$(deep_dir 20)
body=$(call file.read project "${p}/../../../../../../../../../../../../../../../../../../../../f.txt")
code=$(field "$body" code)
if [ "$code" = "1001" ]; then
	echo "win-deep: PASS traversal at depth refused"
	pass=$((pass + 1))
else
	echo "win-deep: FAIL traversal at depth code=$code want=1001"
	fail=$((fail + 1))
fi

echo "win-deep: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
