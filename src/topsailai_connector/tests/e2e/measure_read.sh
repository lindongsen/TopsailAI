#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Measure the resources one file.read consumes, on both sides.
#
# The claim this harness exists to support is "a read consumes as few resources as
# practical". That claim is only checkable if the numbers are produced the same way
# every time, so this script measures and reports; it does not decide whether a
# number is good. A threshold belongs to a target that compares against a recorded
# baseline, because a threshold with no baseline is a guess with a test around it.
#
# It measures two real processes started by start.sh, so the harness never becomes a
# second launcher with its own idea of readiness. It stops only the PIDs recorded by
# start.sh, never a process matched by name.
#
# Several sizes are measured in one invocation, in ascending order, because the
# question "does memory grow with the file" is a comparison between sizes and a
# comparison needs one process lifetime. Measuring each size in a separate run would
# compare a warm process against a cold one and call the difference a property of the
# file size.
#
# Peak RSS is the kernel's high-water mark (VmHWM), which is cumulative: the value
# after the second size includes the peak of the first. That is the right quantity
# for this question, because it answers "did the process ever exceed this", and a
# bounded read is exactly a read whose high-water mark stops rising. The baseline is
# reported next to it so a reader can see how much of the peak the reads caused.
#
# What it deliberately does not report: any credential secret, any proof signature,
# any nonce, any file content, and any absolute scope path. A measurement report is
# the kind of file that gets pasted into a ticket, so it names the scope and the file
# rather than where they live on this machine.
#
# Usage:
#   tests/e2e/measure_read.sh [SIZE_MIB...]
#
# Sizes default to 16. Generated files live under .tmp/e2e/ and are removed with the
# work directory on the next start.sh run.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK="$ROOT/.tmp/e2e"
ENV_FILE="$WORK/env.sh"
BIN="$ROOT/bin"
REPORT="$WORK/measure-report.txt"

if [ "$#" -gt 0 ]; then
	SIZES=("$@")
else
	SIZES=(16)
fi

fail() {
	echo "measure: $*" >&2
	exit 1
}

[ -f "$ENV_FILE" ] || fail "$ENV_FILE is missing; run start.sh first"
# shellcheck source=/dev/null
. "$ENV_FILE"

[ -n "${E2E_SERVER_PID:-}" ] || fail "no Server PID recorded; run start.sh first"
[ -n "${E2E_NODE_PID:-}" ] || fail "no Node PID recorded; run start.sh first"
[ -n "${E2E_CLIENT_CREDENTIAL:-}" ] || fail "no client credential recorded; run start.sh first"
[ -n "${E2E_NODE_CREDENTIAL:-}" ] || fail "no node credential recorded; run start.sh first"
[ -n "${E2E_NODE_ID:-}" ] || fail "no node id recorded; run start.sh first"

for pid in "$E2E_SERVER_PID" "$E2E_NODE_PID"; do
	kill -0 "$pid" 2>/dev/null || fail "pid $pid is not running; run start.sh first"
done

# stop_processes stops the two processes by exact PID.
#
# A signal goes to the PID this run was told about, never to a name, because a name
# match would also stop an unrelated process the operator happens to be running.
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
			echo "measure: pid $pid did not exit within 10s" >&2
		fi
	done
}

trap stop_processes EXIT

# cpu_seconds prints the CPU time one process has consumed, in seconds.
#
# utime and stime are fields 14 and 15 of /proc/<pid>/stat, counted in clock ticks.
# The field numbers are read from the kernel's own layout rather than from a parsed
# command line, because the process name in field 2 can contain spaces and would
# shift a naive split.
cpu_seconds() {
	local pid=$1
	local ticks
	ticks=$(awk '{print $14 + $15}' "/proc/$pid/stat" 2>/dev/null) ||
		fail "could not read CPU time for pid $pid"
	[ -n "$ticks" ] || fail "CPU time for pid $pid was empty"
	awk -v t="$ticks" -v h="$CLK_TCK" 'BEGIN { printf "%.3f", t / h }'
}

# peak_rss_kb prints the peak resident memory of one process, in kilobytes.
#
# VmHWM is the kernel's high-water mark, so a peak between two samples cannot be
# missed. Sampling VmRSS would report whatever the value happened to be at the
# moment of the read, which is a different question.
peak_rss_kb() {
	local pid=$1
	local value
	value=$(awk '/^VmHWM:/ {print $2}' "/proc/$pid/status" 2>/dev/null) ||
		fail "could not read peak RSS for pid $pid"
	[ -n "$value" ] || fail "peak RSS for pid $pid was empty"
	echo "$value"
}

CLK_TCK=$(getconf CLK_TCK)
[ -n "$CLK_TCK" ] || fail "could not determine CLK_TCK"

# The transport is read from the Server's own ready line rather than assumed, so a
# report cannot claim binary-v1 while the processes negotiated JSON.
TRANSPORT=$(sed -n 's/.*file_transport=\([^ ]*\).*/\1/p' "$WORK/server.log" | head -n 1)
[ -n "$TRANSPORT" ] || fail "the Server log has no file_transport field; run start.sh first"

PLATFORM=$(uname -s -m)
GO_VERSION=$(go version 2>/dev/null | awk '{print $3}') || GO_VERSION="unknown"
REVISION=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null) || REVISION="unknown"
if ! git -C "$ROOT" diff --quiet 2>/dev/null; then
	REVISION="$REVISION+dirty"
fi

SERVER_RSS_BASELINE=$(peak_rss_kb "$E2E_SERVER_PID")
NODE_RSS_BASELINE=$(peak_rss_kb "$E2E_NODE_PID")

: >"$REPORT"

# measure_one measures one size and appends its report block.
measure_one() {
	local size_mib=$1
	local scope_file="measure-$size_mib.bin"
	local source="$WORK/scope/$scope_file"
	local dest="$WORK/measure-output.bin"

	echo "measure: generating $size_mib MiB in scope project as $scope_file" >&2
	# The file is generated from /dev/urandom so a partial read cannot accidentally
	# match: a file of zeros would compare equal after a truncated transfer.
	head -c $((size_mib * 1024 * 1024)) /dev/urandom >"$source" ||
		fail "could not generate the source file"
	local size_bytes
	size_bytes=$(wc -c <"$source")
	[ "$size_bytes" -gt 0 ] || fail "the generated file is empty"

	local server_cpu_before node_cpu_before
	server_cpu_before=$(cpu_seconds "$E2E_SERVER_PID")
	node_cpu_before=$(cpu_seconds "$E2E_NODE_PID")

	echo "measure: reading $size_bytes bytes through the CLI" >&2
	local start_ns end_ns
	start_ns=$(date +%s%N)
	"$BIN/connector-server" cli \
		--server "$E2E_BASE_URL" \
		--client-credential "$E2E_CLIENT_CREDENTIAL" \
		--node-credential "$E2E_NODE_CREDENTIAL" \
		--node-id "$E2E_NODE_ID" \
		--scope project --path "$scope_file" \
		-o "$dest" --force file.read >/dev/null 2>"$WORK/measure-cli.err" ||
		fail "the read failed: $(cat "$WORK/measure-cli.err")"
	end_ns=$(date +%s%N)

	local server_cpu_after node_cpu_after
	server_cpu_after=$(cpu_seconds "$E2E_SERVER_PID")
	node_cpu_after=$(cpu_seconds "$E2E_NODE_PID")

	local wall_seconds server_cpu node_cpu throughput
	wall_seconds=$(awk -v s="$start_ns" -v e="$end_ns" 'BEGIN { printf "%.3f", (e - s) / 1000000000 }')
	server_cpu=$(awk -v a="$server_cpu_before" -v b="$server_cpu_after" 'BEGIN { printf "%.3f", b - a }')
	node_cpu=$(awk -v a="$node_cpu_before" -v b="$node_cpu_after" 'BEGIN { printf "%.3f", b - a }')
	throughput=$(awk -v bytes="$size_bytes" -v wall="$wall_seconds" \
		'BEGIN { if (wall <= 0) { print "0.00" } else { printf "%.2f", (bytes / 1048576) / wall } }')

	# The content check is a byte comparison, not a size comparison. A truncated
	# transfer of the right length is not a correct transfer, and only cmp can tell
	# the difference.
	local content_verified="no"
	if cmp -s "$source" "$dest"; then
		content_verified="yes"
	fi

	{
		echo "platform=$PLATFORM"
		echo "go_version=$GO_VERSION"
		echo "revision=$REVISION"
		echo "transport=$TRANSPORT"
		echo "scope=project"
		echo "file=$scope_file"
		echo "size_bytes=$size_bytes"
		echo "wall_seconds=$wall_seconds"
		echo "throughput_mib_s=$throughput"
		echo "server_cpu_seconds=$server_cpu"
		echo "node_cpu_seconds=$node_cpu"
		echo "server_rss_baseline_kb=$SERVER_RSS_BASELINE"
		echo "node_rss_baseline_kb=$NODE_RSS_BASELINE"
		echo "server_peak_rss_kb=$(peak_rss_kb "$E2E_SERVER_PID")"
		echo "node_peak_rss_kb=$(peak_rss_kb "$E2E_NODE_PID")"
		echo "content_verified=$content_verified"
		echo
	} | tee -a "$REPORT"

	if [ "$content_verified" != "yes" ]; then
		fail "the read content does not match the source file for $size_mib MiB"
	fi
}

for size in "${SIZES[@]}"; do
	case "$size" in
	'' | *[!0-9]*) fail "size $size is not a whole number of MiB" ;;
	esac
	[ "$size" -gt 0 ] || fail "size $size must be at least 1 MiB"
	measure_one "$size"
done

echo "measure: report written to $REPORT" >&2
