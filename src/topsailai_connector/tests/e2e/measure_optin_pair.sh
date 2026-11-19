#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Run measure_optin.sh in both modes against one pair of processes.
#
# `measure_optin.sh` measures one mode and deliberately owns no lifetime, because
# the comparison it exists for needs the same two processes for both modes. That
# makes it the wrong thing for a Make target to call directly: a target that runs
# it once leaves the Server and the Node behind, and a target that runs it twice
# still leaves them behind on any failure.
#
# This wrapper is the caller that owns the lifetime. It starts the processes,
# measures `raw` and `legacy` at the same size, and stops the exact PIDs that
# `start.sh` recorded, on every exit path including a failure.
#
# The two modes are measured against the same processes on purpose. The difference
# between the two reports is then the cost of the JSON envelope and nothing else,
# which is the claim Unit 4a and Unit 4b make. Measuring them in separate runs
# would mix that difference with process startup, page cache and host load.
#
# It prints both blocks and does not judge. The comparison against the recorded
# baseline belongs to check_budget.sh, because a threshold separated from the
# baseline it implements is a guess with a test around it.
#
# Usage:
#   tests/e2e/measure_optin_pair.sh [SIZE_MIB]
#
# Requires nothing to be running: it starts what it needs and stops what it
# started. It never stops a process by name, so it cannot stop an unrelated one.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK="$ROOT/.tmp/e2e"
ENV_FILE="$WORK/env.sh"

SIZE_MIB=${1:-16}

fail() {
	echo "measure-optin-pair: $*" >&2
	exit 1
}

case "$SIZE_MIB" in
'' | *[!0-9]*) fail "size $SIZE_MIB is not a whole number of MiB" ;;
esac
[ "$SIZE_MIB" -gt 0 ] || fail "size $SIZE_MIB must be at least 1 MiB"

# stop_processes stops the two processes by exact PID.
#
# A signal goes to the PID this run was told about, never to a name, because a name
# match would also stop an unrelated process the operator happens to be running.
# The PIDs are read from the env file `start.sh` wrote, so this function can only
# ever stop the pair this run started.
stop_processes() {
	local pid
	[ -f "$ENV_FILE" ] || return 0
	# shellcheck source=/dev/null
	. "$ENV_FILE"
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
			echo "measure-optin-pair: pid $pid did not exit within 10s" >&2
		fi
	done
}

trap stop_processes EXIT

bash "$ROOT/tests/e2e/start.sh" 2>&1 | sed 's/^/start: /'

echo "measure-optin-pair: measuring raw at ${SIZE_MIB} MiB"
bash "$ROOT/tests/e2e/measure_optin.sh" "$SIZE_MIB" raw

echo "measure-optin-pair: measuring legacy at ${SIZE_MIB} MiB"
bash "$ROOT/tests/e2e/measure_optin.sh" "$SIZE_MIB" legacy

echo "measure-optin-pair: both modes measured at ${SIZE_MIB} MiB"
