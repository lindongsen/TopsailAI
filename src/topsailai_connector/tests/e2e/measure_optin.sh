#!/usr/bin/env bash
# Author: DawsonLin
# Purpose: Measure the Server-to-caller wire ratio on the raw byte stream.
#
# `measure_read.sh` drives the CLI, and the CLI sends no Accept header, so that
# harness can only observe the JSON envelope. The envelope base64-encodes the file,
# which is the cost Unit 4a removed from the opt-in path. A harness that cannot send
# the opt-in header therefore cannot measure the change it is supposed to verify, and
# reporting the envelope ratio as the result of this unit would be reporting a number
# that did not move.
#
# This script sends the same signed request the CLI sends, with one difference: it
# adds `Accept: application/octet-stream`. It then reads the Server's own `wchar`
# counter across the request, so the ratio is the bytes the Server actually wrote,
# not a number derived from the response the script happened to receive.
#
# It measures one size and prints one block. It does not judge: the comparison
# against the recorded baseline belongs to check_budget.sh, because a threshold
# separated from the baseline it implements is a guess with a test around it.
#
# What it deliberately does not print: any credential secret, any proof signature,
# any nonce, any file content, or any absolute scope path.
#
# Usage:
#   tests/e2e/measure_optin.sh [SIZE_MIB] [raw|legacy]
#
# `raw` sends `Accept: application/octet-stream` and receives the file bytes.
# `legacy` sends no Accept header, which is what the CLI does today, and receives
# the documented JSON envelope. Both modes are measured by the same program against
# the same processes, so the difference between the two reports is the cost of the
# envelope and nothing else.
#
# Requires start.sh to have run, because it reuses the two processes and the
# credentials that script recorded. It stops only the PIDs start.sh recorded.

set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WORK="$ROOT/.tmp/e2e"
ENV_FILE="$WORK/env.sh"
REPORT="$WORK/measure-optin-report.txt"

SIZE_MIB=${1:-16}
MODE=${2:-raw}

fail() {
	echo "measure-optin: $*" >&2
	exit 1
}

case "$MODE" in
raw | legacy) ;;
*) fail "mode $MODE is not raw or legacy" ;;
esac

[ -f "$ENV_FILE" ] || fail "$ENV_FILE is missing; run start.sh first"
# shellcheck source=/dev/null
. "$ENV_FILE"

[ -n "${E2E_SERVER_PID:-}" ] || fail "no Server PID recorded; run start.sh first"
[ -n "${E2E_BASE_URL:-}" ] || fail "no base URL recorded; run start.sh first"
[ -n "${E2E_CLIENT_CREDENTIAL:-}" ] || fail "no client credential recorded; run start.sh first"
[ -n "${E2E_NODE_CREDENTIAL:-}" ] || fail "no node credential recorded; run start.sh first"
[ -n "${E2E_NODE_ID:-}" ] || fail "no node id recorded; run start.sh first"

kill -0 "$E2E_SERVER_PID" 2>/dev/null || fail "pid $E2E_SERVER_PID is not running; run start.sh first"
[ -n "${E2E_NODE_PID:-}" ] || fail "no Node PID recorded; run start.sh first"
kill -0 "$E2E_NODE_PID" 2>/dev/null || fail "pid $E2E_NODE_PID is not running; run start.sh first"

case "$SIZE_MIB" in
'' | *[!0-9]*) fail "size $SIZE_MIB is not a whole number of MiB" ;;
esac
[ "$SIZE_MIB" -gt 0 ] || fail "size $SIZE_MIB must be at least 1 MiB"

# wire_bytes prints the bytes one process has written to its file descriptors.
#
# wchar counts bytes written, including bytes written to a socket, so the delta
# across one request is the protocol bytes that process put on the wire. It is the
# only per-process wire counter the kernel exposes without a packet capture, and a
# packet capture would need privileges this harness must not require.
wire_bytes() {
	local pid=$1
	local value
	value=$(awk '/^wchar:/ {print $2}' "/proc/$pid/io" 2>/dev/null) ||
		fail "could not read wire bytes for pid $pid"
	[ -n "$value" ] || fail "wire bytes for pid $pid was empty"
	echo "$value"
}

# cpu_ticks prints the CPU time one process has consumed, in clock ticks.
#
# The value is utime plus stime from /proc/<pid>/stat. The comm field is stripped
# before the fields are counted, because a process name may contain a space or a
# closing parenthesis and would otherwise shift every field after it. After the
# strip the remainder starts at field 3, so utime is field 12 and stime is 13.
#
# Ticks rather than seconds, because the conversion needs CLK_TCK and doing it once
# at the end keeps the arithmetic in one place.
cpu_ticks() {
	local pid=$1
	local value
	value=$(sed 's/.*) //' "/proc/$pid/stat" 2>/dev/null | awk '{print $12 + $13}') ||
		fail "could not read cpu ticks for pid $pid"
	[ -n "$value" ] || fail "cpu ticks for pid $pid was empty"
	echo "$value"
}

# rss_kb prints the resident set size one process holds right now, in KiB.
rss_kb() {
	local pid=$1
	local value
	value=$(awk '/^VmRSS:/ {print $2}' "/proc/$pid/status" 2>/dev/null) ||
		fail "could not read rss for pid $pid"
	[ -n "$value" ] || fail "rss for pid $pid was empty"
	echo "$value"
}

# peak_rss_kb prints the highest resident set size one process has reached since it
# started, in KiB.
#
# VmHWM is the kernel's own high-water mark, so it needs no sampling and cannot miss
# a spike between two polls. It covers the whole life of the process rather than one
# request, which is why the report also carries the sampled peak: a Node that has
# served a larger file earlier would report a high-water mark this run did not set.
peak_rss_kb() {
	local pid=$1
	local value
	value=$(awk '/^VmHWM:/ {print $2}' "/proc/$pid/status" 2>/dev/null) ||
		fail "could not read peak rss for pid $pid"
	[ -n "$value" ] || fail "peak rss for pid $pid was empty"
	echo "$value"
}

# sample_peak_rss polls two processes and records the highest RSS each one reached
# during the run.
#
# A background poller is used because VmHWM answers a different question: it is the
# peak over the process's whole life, so a Node that served a bigger file an hour ago
# reports that peak and not this run's. The poller answers "what did this run cost",
# and the two numbers are reported side by side so a reader can tell them apart.
#
# The interval is 50 ms. A read of 16 MiB takes seconds, so 50 ms gives dozens of
# samples; a shorter interval would add measurable load to the processes being
# measured, which is the one thing a measurement harness must not do.
sample_peak_rss() {
	local first=$1
	local second=$2
	local out=$3
	local first_peak=0
	local second_peak=0
	local value
	while :; do
		value=$(awk '/^VmRSS:/ {print $2}' "/proc/$first/status" 2>/dev/null) || value=""
		if [ -n "$value" ] && [ "$value" -gt "$first_peak" ]; then
			first_peak=$value
		fi
		value=$(awk '/^VmRSS:/ {print $2}' "/proc/$second/status" 2>/dev/null) || value=""
		if [ -n "$value" ] && [ "$value" -gt "$second_peak" ]; then
			second_peak=$value
		fi
		printf '%s %s\n' "$first_peak" "$second_peak" >"$out"
		sleep 0.05
	done
}

PLATFORM=$(uname -s -m)
GO_VERSION=$(go version 2>/dev/null | awk '{print $3}') || GO_VERSION="unknown"
REVISION=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null) || REVISION="unknown"
if ! git -C "$ROOT" diff --quiet 2>/dev/null; then
	REVISION="$REVISION+dirty"
fi

TRANSPORT=$(sed -n 's/.*file_transport=\([^ ]*\).*/\1/p' "$WORK/server.log" | head -n 1)
[ -n "$TRANSPORT" ] || fail "the Server log has no file_transport field; run start.sh first"

SCOPE_FILE="optin-$SIZE_MIB.bin"
SOURCE="$WORK/scope/$SCOPE_FILE"
# The destination carries the mode, so a raw run and a legacy run of the same size
# cannot overwrite each other's output and be compared against the wrong source.
DEST="$WORK/optin-output-$MODE.bin"

echo "measure-optin: generating $SIZE_MIB MiB in scope project as $SCOPE_FILE" >&2
# The file is generated from /dev/urandom so a partial read cannot accidentally
# match: a file of zeros would compare equal after a truncated transfer.
head -c $((SIZE_MIB * 1024 * 1024)) /dev/urandom >"$SOURCE" ||
	fail "could not generate the source file"
SIZE_BYTES=$(wc -c <"$SOURCE")
[ "$SIZE_BYTES" -gt 0 ] || fail "the generated file is empty"

# Both processes are measured, because the requirement is about the Node's own
# resources as much as the Server's. A harness that reported only the Server would
# miss the machine the user actually cares about.
SERVER_WIRE_BEFORE=$(wire_bytes "$E2E_SERVER_PID")
NODE_WIRE_BEFORE=$(wire_bytes "$E2E_NODE_PID")
SERVER_CPU_BEFORE=$(cpu_ticks "$E2E_SERVER_PID")
NODE_CPU_BEFORE=$(cpu_ticks "$E2E_NODE_PID")
SERVER_RSS_BEFORE=$(rss_kb "$E2E_SERVER_PID")
NODE_RSS_BEFORE=$(rss_kb "$E2E_NODE_PID")

# The poller writes the running peak to a file rather than to a variable, because a
# background subshell cannot assign to its parent. It is stopped by PID, never by
# name, so it cannot kill an unrelated process.
RSS_SAMPLE="$WORK/optin-rss-sample.txt"
sample_peak_rss "$E2E_SERVER_PID" "$E2E_NODE_PID" "$RSS_SAMPLE" &
RSS_POLLER_PID=$!
# The poller is stopped on every exit path, including a failure, so a failed run
# does not leave a loop behind that keeps reading /proc forever.
trap 'kill "$RSS_POLLER_PID" 2>/dev/null || true' EXIT

START_NS=$(date +%s%N)

# The request is built and sent by a small Python program rather than by curl,
# because the two proofs are HMACs over a canonical string with a fixed field order.
# Reimplementing that order in shell would be a second definition of the signing
# contract, and a second definition is the defect this project keeps recording.
#
# The program is written to a file under the work directory rather than piped through
# a heredoc, because a heredoc cannot carry a failure status back to the caller: the
# `||` that would report a failure has to sit on the command that runs the program,
# and a heredoc body is not a command. A file also keeps the program readable in the
# work directory when a run fails.
PROBE="$WORK/optin_probe.py"
cat >"$PROBE" <<'PY'
import base64
import hashlib
import hmac
import http.client
import json
import secrets
import sys
import time
from urllib.parse import urlsplit

base_url, node_id, client_credential, node_credential, scope_file, dest, mode = sys.argv[1:8]

SCHEME_CLIENT = "CONNECTOR-CLIENT-HMAC-SHA256"
SCHEME_NODE = "CONNECTOR-NODE-HMAC-SHA256"
VERSION = 1

# CHUNK_BYTES mirrors the Node's response cap and the CLI's own chunk size. The
# probe asks for exactly this much so it makes the same number of requests the CLI
# makes. Asking for the whole file in one request receives one capped chunk, which
# is how the first version of this probe reported 262985 wire bytes for a 16 MiB
# file and then failed its own content check: the probe was wrong, not the product.
CHUNK_BYTES = 256 * 1024

# RAW is the opt-in shape and LEGACY is the documented JSON envelope. Both are
# measured by this one program so the two numbers come from the same host, the same
# processes and the same file, which is the only way the comparison means anything.
RAW = "raw"
LEGACY = "legacy"
if mode not in (RAW, LEGACY):
    raise SystemExit(f"mode = {mode!r}, want {RAW} or {LEGACY}")


def split_credential(value):
    """Split key_id.secret on the first dot, which is the documented rule."""
    key_id, _, secret = value.partition(".")
    if not key_id or not secret:
        raise SystemExit("a credential is not key_id.secret")
    return key_id, secret


def sign(secret, canonical):
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def format_proof(scheme, key_id, timestamp_ms, nonce, signature):
    return (
        f"{scheme} version={VERSION},key_id={key_id},timestamp_ms={timestamp_ms},"
        f"nonce={nonce},signature={signature}"
    )


client_key_id, client_secret = split_credential(client_credential)
node_key_id, node_secret = split_credential(node_credential)

parts = urlsplit(base_url)
target = f"/v1/nodes/{node_id}/operations"


def read_chunk(offset, length):
    """Send one signed file.read and return (content, truncated).

    Every chunk is a separately signed request with its own nonce, timestamp and
    request id, exactly as the CLI does it. The node proof binds the offset and the
    length, so a chunk cannot be replayed at a different position.
    """
    body = json.dumps(
        {
            "operation": "file.read",
            "scope": "project",
            "path": scope_file,
            "offset": offset,
            "length": length,
        },
        separators=(",", ":"),
    ).encode()

    request_id = "req_" + secrets.token_hex(16)
    now_ms = int(time.time() * 1000)

    node_nonce = secrets.token_hex(16)
    node_canonical = "\n".join(
        [
            SCHEME_NODE,
            str(VERSION),
            node_id,
            node_key_id,
            "file.read",
            "project",
            scope_file,
            str(offset),
            str(length),
            request_id,
            str(now_ms),
            node_nonce,
        ]
    )
    node_header = format_proof(
        SCHEME_NODE, node_key_id, now_ms, node_nonce, sign(node_secret, node_canonical)
    )

    body_digest = hashlib.sha256(body).hexdigest()
    node_proof_digest = hashlib.sha256(node_header.encode()).hexdigest()

    client_nonce = secrets.token_hex(16)
    client_canonical = "\n".join(
        [
            SCHEME_CLIENT,
            str(VERSION),
            "POST",
            target,
            body_digest,
            node_proof_digest,
            request_id,
            str(now_ms),
            client_nonce,
        ]
    )
    client_header = format_proof(
        SCHEME_CLIENT, client_key_id, now_ms, client_nonce, sign(client_secret, client_canonical)
    )

    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=300)
    headers = {
        "Content-Type": "application/json",
        "Authorization": client_header,
        "X-Connector-Node-Auth": node_header,
        "X-Request-Id": request_id,
    }
    # The legacy mode deliberately sends no Accept header, which is what the CLI does
    # today. The two modes therefore differ in exactly one header, so a difference in
    # the measured bytes is attributable to the response shape and not to the request.
    if mode == RAW:
        headers["Accept"] = "application/octet-stream"
    try:
        connection.request("POST", target, body=body, headers=headers)
        response = connection.getresponse()
        payload = response.read()
        status = response.status
        content_type = response.getheader("Content-Type") or ""
        declared = response.getheader("Content-Length")
        truncated_header = response.getheader("X-Connector-Truncated")
    finally:
        connection.close()

    if status != 200:
        raise SystemExit(f"the read failed: status {status} body {payload[:200]!r}")
    if declared is not None and int(declared) != len(payload):
        raise SystemExit(f"Content-Length {declared} disagrees with {len(payload)} bytes")

    if mode == RAW:
        if content_type != "application/octet-stream":
            raise SystemExit(f"content type = {content_type!r}, want application/octet-stream")
        if declared is None:
            raise SystemExit("the response has no Content-Length")
        if truncated_header is None:
            raise SystemExit("the response has no X-Connector-Truncated header")
        if truncated_header not in ("true", "false"):
            raise SystemExit(f"X-Connector-Truncated = {truncated_header!r}, want true or false")
        return payload, truncated_header == "true"

    # The legacy shape is the documented envelope: a JSON object whose data field
    # carries the base64 content. It is decoded here so the content check compares
    # file bytes rather than an encoding of them.
    if not content_type.startswith("application/json"):
        raise SystemExit(f"content type = {content_type!r}, want application/json")
    envelope = json.loads(payload)
    if envelope.get("code") != 0:
        raise SystemExit(f"the read failed: code {envelope.get('code')} message {envelope.get('message')!r}")
    data = envelope.get("data") or {}
    content = base64.b64decode(data.get("content") or "")
    return content, bool(data.get("truncated"))


# The loop is the CLI's loop, copied deliberately rather than invented: request the
# cap, write what arrived, advance by the bytes received, and stop when the Node
# reports end of file or delivers nothing. The second condition is not redundant,
# because a response that claims more remains but delivers nothing would otherwise
# spin forever, and a spin is a hang rather than an error.
total = 0
offset = 0
chunks = 0
with open(dest, "wb") as handle:
    while True:
        content, truncated = read_chunk(offset, CHUNK_BYTES)
        chunks += 1
        if content:
            handle.write(content)
            total += len(content)
            offset += len(content)
        if not content or not truncated:
            break

print(f"chunks={chunks} bytes={total}", file=sys.stderr)
PY

python3 "$PROBE" "$E2E_BASE_URL" "$E2E_NODE_ID" "$E2E_CLIENT_CREDENTIAL" \
	"$E2E_NODE_CREDENTIAL" "$SCOPE_FILE" "$DEST" "$MODE" ||
	fail "the $MODE request failed"

END_NS=$(date +%s%N)
SERVER_WIRE_AFTER=$(wire_bytes "$E2E_SERVER_PID")
NODE_WIRE_AFTER=$(wire_bytes "$E2E_NODE_PID")
SERVER_CPU_AFTER=$(cpu_ticks "$E2E_SERVER_PID")
NODE_CPU_AFTER=$(cpu_ticks "$E2E_NODE_PID")

# The poller is stopped before its file is read, so the last sample is the final
# peak rather than a value still being rewritten.
kill "$RSS_POLLER_PID" 2>/dev/null || true
wait "$RSS_POLLER_PID" 2>/dev/null || true
SERVER_RSS_PEAK=$(awk '{if ($1 > peak) peak = $1} END {print peak + 0}' "$RSS_SAMPLE" 2>/dev/null) ||
	SERVER_RSS_PEAK=0
NODE_RSS_PEAK=$(awk '{if ($2 > peak) peak = $2} END {print peak + 0}' "$RSS_SAMPLE" 2>/dev/null) ||
	NODE_RSS_PEAK=0
SERVER_RSS_HWM=$(peak_rss_kb "$E2E_SERVER_PID")
NODE_RSS_HWM=$(peak_rss_kb "$E2E_NODE_PID")

# CLK_TCK is read from the system rather than assumed to be 100. It is 100 on every
# Linux this project runs on, but a harness that hardcodes it reports a CPU time that
# is wrong by a constant factor on a system where it is not.
CLK_TCK=$(getconf CLK_TCK 2>/dev/null) || CLK_TCK=100
[ -n "$CLK_TCK" ] || CLK_TCK=100

WALL_SECONDS=$(awk -v s="$START_NS" -v e="$END_NS" 'BEGIN { printf "%.3f", (e - s) / 1000000000 }')
SERVER_WIRE_BYTES=$((SERVER_WIRE_AFTER - SERVER_WIRE_BEFORE))
NODE_WIRE_BYTES=$((NODE_WIRE_AFTER - NODE_WIRE_BEFORE))
SERVER_WIRE_RATIO=$(awk -v w="$SERVER_WIRE_BYTES" -v b="$SIZE_BYTES" \
	'BEGIN { printf "%.4f", w / b }')
NODE_WIRE_RATIO=$(awk -v w="$NODE_WIRE_BYTES" -v b="$SIZE_BYTES" \
	'BEGIN { printf "%.4f", w / b }')
SERVER_CPU_SECONDS=$(awk -v t="$((SERVER_CPU_AFTER - SERVER_CPU_BEFORE))" -v h="$CLK_TCK" \
	'BEGIN { printf "%.3f", t / h }')
NODE_CPU_SECONDS=$(awk -v t="$((NODE_CPU_AFTER - NODE_CPU_BEFORE))" -v h="$CLK_TCK" \
	'BEGIN { printf "%.3f", t / h }')
THROUGHPUT=$(awk -v bytes="$SIZE_BYTES" -v wall="$WALL_SECONDS" \
	'BEGIN { if (wall <= 0) { print "0.00" } else { printf "%.2f", (bytes / 1048576) / wall } }')
# CPU per MiB is the number the budget is stated in, because it does not move with
# the file size the way a total does. A total answers "what did this run cost"; a
# per-MiB figure answers "what does this cost per unit of work", which is the one a
# regression can be compared against.
SERVER_CPU_PER_MIB=$(awk -v c="$SERVER_CPU_SECONDS" -v m="$SIZE_MIB" \
	'BEGIN { printf "%.4f", c / m }')
NODE_CPU_PER_MIB=$(awk -v c="$NODE_CPU_SECONDS" -v m="$SIZE_MIB" \
	'BEGIN { printf "%.4f", c / m }')

# The content check is a byte comparison, not a size comparison. A truncated
# transfer of the right length is not a correct transfer, and only cmp can tell
# the difference.
CONTENT_VERIFIED="no"
if cmp -s "$SOURCE" "$DEST"; then
	CONTENT_VERIFIED="yes"
fi

{
	echo "platform=$PLATFORM"
	echo "go_version=$GO_VERSION"
	echo "revision=$REVISION"
	echo "transport=$TRANSPORT"
	echo "mode=$MODE"
	if [ "$MODE" = "raw" ]; then
		echo "accept=application/octet-stream"
	else
		echo "accept=none"
	fi
	echo "scope=project"
	echo "file=$SCOPE_FILE"
	echo "size_bytes=$SIZE_BYTES"
	echo "size_mib=$SIZE_MIB"
	echo "wall_seconds=$WALL_SECONDS"
	echo "throughput_mib_s=$THROUGHPUT"
	echo "server_wire_bytes=$SERVER_WIRE_BYTES"
	echo "server_wire_ratio=$SERVER_WIRE_RATIO"
	echo "node_wire_bytes=$NODE_WIRE_BYTES"
	echo "node_wire_ratio=$NODE_WIRE_RATIO"
	echo "server_cpu_seconds=$SERVER_CPU_SECONDS"
	echo "server_cpu_per_mib=$SERVER_CPU_PER_MIB"
	echo "node_cpu_seconds=$NODE_CPU_SECONDS"
	echo "node_cpu_per_mib=$NODE_CPU_PER_MIB"
	echo "server_rss_before_kb=$SERVER_RSS_BEFORE"
	echo "server_rss_peak_kb=$SERVER_RSS_PEAK"
	echo "server_rss_hwm_kb=$SERVER_RSS_HWM"
	echo "node_rss_before_kb=$NODE_RSS_BEFORE"
	echo "node_rss_peak_kb=$NODE_RSS_PEAK"
	echo "node_rss_hwm_kb=$NODE_RSS_HWM"
	echo "content_verified=$CONTENT_VERIFIED"
	echo
} | tee -a "$REPORT"

if [ "$CONTENT_VERIFIED" != "yes" ]; then
	fail "the streamed content does not match the source file for $SIZE_MIB MiB"
fi

echo "measure-optin: report written to $REPORT" >&2
