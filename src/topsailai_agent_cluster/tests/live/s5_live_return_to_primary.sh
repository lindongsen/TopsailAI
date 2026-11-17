#!/usr/bin/env bash
# Live dual-Server return-to-primary test.
#
# This script proves the one direction the BDD harness cannot prove: an Endpoint
# that is homed on the secondary Server returns to the primary when the secondary
# stops answering. It runs against the real deployment, not the harness.
#
# The scenario has five steps and the middle two are load-bearing. An Endpoint that
# is already on the primary cannot "return" to it, so freezing the secondary while
# every Endpoint is on the primary proves nothing: the first version of this script
# did exactly that, and its "returned" assertion passed trivially while the liveness
# assertion failed. The Endpoints must first be moved onto the secondary, which is
# what stopping the primary does.
#
# The secondary is FROZEN with SIGSTOP, never stopped. A stopped Server closes its
# socket, the Endpoint's read fails immediately, and the reconnect walks the ordered
# address list back to the primary even on a build with no liveness rule at all. Only
# a Server that keeps its socket open and stops replying exercises the heartbeat
# acknowledgement rule, so SIGSTOP is the faithful failure and SIGTERM is not.
#
# Cleanup is guaranteed on every exit path: the secondary is resumed and the primary
# container is started again, because a failed assertion must not leave the
# deployment with a frozen secondary or a stopped primary.
#
# Usage: s5_live_return_to_primary.sh [--dry-run]
set -uo pipefail

SECONDARY_HOST="192.168.2.3"
PRIMARY_CONTAINER="agent-cluster-server-primary"
CLI="/opt/agent-cluster/bin/agent-cluster-cli"
ENDPOINTS=("ai-dev" "topsailai-dev")
ENDPOINT_LOG="/opt/agent-cluster/logs/endpoint"
WINDOW_SECONDS=90
FALLBACK_WINDOW_SECONDS=120
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

SECONDARY_PID=""
FROZEN=0
PRIMARY_STOPPED=0
FAILURES=0

log() { printf '%s %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
fail() { log "ASSERTION FAILED: $*"; FAILURES=$((FAILURES + 1)); }

# cleanup restores the deployment. It runs from the trap on every exit path, so a
# failed assertion cannot leave a frozen secondary or a stopped primary behind.
cleanup() {
	if [ "$FROZEN" -eq 1 ] && [ -n "$SECONDARY_PID" ]; then
		log "cleanup: sending SIGCONT to secondary pid $SECONDARY_PID"
		ssh -o ConnectTimeout=5 -o BatchMode=yes "$SECONDARY_HOST" "kill -CONT $SECONDARY_PID" 2>/dev/null
		FROZEN=0
	fi
	if [ "$PRIMARY_STOPPED" -eq 1 ]; then
		log "cleanup: starting the primary container"
		docker start "$PRIMARY_CONTAINER" >/dev/null 2>&1
		PRIMARY_STOPPED=0
	fi
	if [ -n "$SECONDARY_PID" ]; then
		local state
		state=$(ssh -o ConnectTimeout=5 -o BatchMode=yes "$SECONDARY_HOST" \
			"awk '/^State:/{print \$2}' /proc/$SECONDARY_PID/status" 2>/dev/null)
		if [ "$state" = "T" ] || [ "$state" = "t" ]; then
			log "cleanup: secondary pid $SECONDARY_PID is STILL FROZEN (state=$state)"
			FAILURES=$((FAILURES + 1))
		else
			log "cleanup: secondary pid $SECONDARY_PID state=$state (running)"
		fi
	fi
	local primary_state
	primary_state=$(docker inspect -f '{{.State.Status}}' "$PRIMARY_CONTAINER" 2>/dev/null)
	log "cleanup: primary container status=$primary_state"
	if [ "$primary_state" != "running" ]; then
		log "cleanup: primary container is NOT running"
		FAILURES=$((FAILURES + 1))
	fi
}
trap cleanup EXIT INT TERM

# endpoint_log_path resolves one Endpoint's log file inside its own container.
endpoint_log_path() {
	local name="$1"
	case "$name" in
	ai-dev) echo "ai-dev:$ENDPOINT_LOG/ac.ai-dev.log" ;;
	topsailai-dev) echo "topsailai-dev:$ENDPOINT_LOG/ac.topsailai-dev.log" ;;
	esac
}

log_size() {
	local container="$1" path="$2"
	docker exec "$container" sh -c "wc -c < '$path'" 2>/dev/null | tr -d ' '
}

read_since() {
	local container="$1" path="$2" offset="$3"
	docker exec "$container" sh -c "tail -c +$((offset + 1)) '$path'" 2>/dev/null
}

# primary_state prints the primary's view of one Endpoint's connection state.
#
# The table is drawn with box-drawing separators, so field splitting on whitespace
# does not work: the separator itself becomes a field and every column shifts. The
# separator is used as the delimiter instead, and the value is trimmed, so the
# extraction does not depend on column widths.
primary_state() {
	local id="$1"
	timeout 25 "$CLI" endpoints 2>/dev/null \
		| awk -F'│' -v id="$id" '{ gsub(/^[ \t]+|[ \t]+$/, "", $1); if ($1 == id) { gsub(/^[ \t]+|[ \t]+$/, "", $4); print $4 } }'
}

# secondary_state asks the secondary Server directly, so "homed on the secondary" is
# observed rather than inferred from the primary's absence of the Endpoint.
secondary_state() {
	local id="$1"
	ssh -o ConnectTimeout=5 -o BatchMode=yes "$SECONDARY_HOST" \
		"timeout 25 $CLI endpoints 2>/dev/null" \
		| awk -F'│' -v id="$id" '{ gsub(/^[ \t]+|[ \t]+$/, "", $1); if ($1 == id) { gsub(/^[ \t]+|[ \t]+$/, "", $4); print $4 } }'
}

# wait_for polls a state function until it reports the wanted value or the window
# expires, and prints the last observed value.
wait_for() {
	local window="$1" want="$2" fn="$3" id="$4"
	local deadline=$(( $(date +%s) + window ))
	local observed=""
	while [ "$(date +%s)" -lt "$deadline" ]; do
		observed=$("$fn" "$id")
		[ "$observed" = "$want" ] && { echo "$observed"; return 0; }
		sleep 3
	done
	echo "$observed"
	return 1
}

log "=== S5 live return-to-primary test ==="
log "secondary=$SECONDARY_HOST primary=$PRIMARY_CONTAINER window=${WINDOW_SECONDS}s dry_run=$DRY_RUN"

SECONDARY_PID=$(ssh -o ConnectTimeout=5 -o BatchMode=yes "$SECONDARY_HOST" \
	"pgrep -f 'bin/agent-cluster-server' | head -1" 2>/dev/null)
if [ -z "$SECONDARY_PID" ]; then
	log "ABORT: no secondary Server process found on $SECONDARY_HOST"
	exit 1
fi
SECONDARY_STATE=$(ssh -o ConnectTimeout=5 -o BatchMode=yes "$SECONDARY_HOST" \
	"awk '/^State:/{print \$2}' /proc/$SECONDARY_PID/status" 2>/dev/null)
log "secondary pid=$SECONDARY_PID state=$SECONDARY_STATE"
if [ "$SECONDARY_STATE" = "T" ] || [ "$SECONDARY_STATE" = "t" ]; then
	log "ABORT: secondary is already frozen; resume it before running this test"
	exit 1
fi
PRIMARY_STATUS=$(docker inspect -f '{{.State.Status}}' "$PRIMARY_CONTAINER" 2>/dev/null)
log "primary container status=$PRIMARY_STATUS"
if [ "$PRIMARY_STATUS" != "running" ]; then
	log "ABORT: primary container is not running"
	exit 1
fi

# Step 1: every Endpoint must be online on the primary, so the fallback in step 2 is
# a real change rather than a state that was already true.
log "--- step 1: confirm every Endpoint is online on the primary ---"
for name in "${ENDPOINTS[@]}"; do
	state=$(primary_state "ac.$name")
	log "  ac.$name primary_state=$state"
	[ "$state" != "online" ] && fail "ac.$name is not online on the primary before the test (state=$state)"
done
if [ "$FAILURES" -ne 0 ]; then
	log "ABORT: preconditions not met, nothing was changed"
	exit 1
fi

if [ "$DRY_RUN" -eq 1 ]; then
	log "DRY RUN: preconditions met, stopping before any state change"
	exit 0
fi

# Step 2: stop the primary so the Endpoints re-home to the secondary. This is what
# puts them in the position where "return to the primary" is a real transition.
log "--- step 2: stop the primary container ---"
docker stop "$PRIMARY_CONTAINER" >/dev/null 2>&1
PRIMARY_STOPPED=1
log "  primary stopped at $(date -u +%H:%M:%SZ)"
for name in "${ENDPOINTS[@]}"; do
	state=$(wait_for "$FALLBACK_WINDOW_SECONDS" online secondary_state "ac.$name")
	log "  ac.$name secondary_state=$state"
	[ "$state" != "online" ] && fail "ac.$name did not re-home to the secondary within ${FALLBACK_WINDOW_SECONDS}s (state=$state)"
done
if [ "$FAILURES" -ne 0 ]; then
	log "ABORT: fallback did not complete, the return direction cannot be tested"
	exit 1
fi

# Step 3: restart the primary and confirm the Endpoints STAY on the secondary. This
# is the confirmed behaviour: a restored primary does not pull them back.
log "--- step 3: restart the primary and confirm no automatic switch-back ---"
docker start "$PRIMARY_CONTAINER" >/dev/null 2>&1
PRIMARY_STOPPED=0
log "  primary started at $(date -u +%H:%M:%SZ)"
sleep 25
for name in "${ENDPOINTS[@]}"; do
	state=$(secondary_state "ac.$name")
	log "  ac.$name secondary_state=$state after the primary returned"
	[ "$state" != "online" ] && fail "ac.$name left the secondary after the primary was restored (state=$state), so the confirmed no-switch-back behaviour is broken"
done
if [ "$FAILURES" -ne 0 ]; then
	log "ABORT: the Endpoints are not on the secondary, so the return direction cannot be tested"
	exit 1
fi

# Record each Endpoint's log offset so the assertions read only this run's lines.
declare -A OFFSETS CONTAINERS PATHS
for name in "${ENDPOINTS[@]}"; do
	spec=$(endpoint_log_path "$name")
	CONTAINERS[$name]="${spec%%:*}"
	PATHS[$name]="${spec#*:}"
	OFFSETS[$name]=$(log_size "${CONTAINERS[$name]}" "${PATHS[$name]}")
	log "  $name log offset=${OFFSETS[$name]}"
done

# Step 4: freeze the secondary. SIGSTOP keeps the socket open and the kernel
# acknowledging, so the Endpoint sees a live TCP connection that never answers.
log "--- step 4: SIGSTOP the secondary pid $SECONDARY_PID ---"
ssh -o ConnectTimeout=5 -o BatchMode=yes "$SECONDARY_HOST" "kill -STOP $SECONDARY_PID" 2>/dev/null
FROZEN=1
FROZEN_AT=$(date +%s)
log "  frozen at $(date -u +%H:%M:%SZ)"

declare -A SAW_TIMEOUT RETURNED
for name in "${ENDPOINTS[@]}"; do
	SAW_TIMEOUT[$name]=0
	RETURNED[$name]=0
done

while [ $(( $(date +%s) - FROZEN_AT )) -lt "$WINDOW_SECONDS" ]; do
	all_done=1
	for name in "${ENDPOINTS[@]}"; do
		if [ "${SAW_TIMEOUT[$name]}" -eq 0 ]; then
			if read_since "${CONTAINERS[$name]}" "${PATHS[$name]}" "${OFFSETS[$name]}" \
				| grep -q "heartbeat acknowledgement timed out"; then
				SAW_TIMEOUT[$name]=1
				log "  $name logged the liveness decision at $(date -u +%H:%M:%SZ)"
			fi
		fi
		if [ "${RETURNED[$name]}" -eq 0 ]; then
			if [ "$(primary_state "ac.$name")" = "online" ]; then
				RETURNED[$name]=1
				log "  $name is online on the primary at $(date -u +%H:%M:%SZ)"
			fi
		fi
		if [ "${SAW_TIMEOUT[$name]}" -eq 0 ] || [ "${RETURNED[$name]}" -eq 0 ]; then
			all_done=0
		fi
	done
	[ "$all_done" -eq 1 ] && break
	sleep 3
done

ELAPSED=$(( $(date +%s) - FROZEN_AT ))
log "  elapsed=${ELAPSED}s"

for name in "${ENDPOINTS[@]}"; do
	[ "${SAW_TIMEOUT[$name]}" -eq 0 ] && fail "$name never logged 'heartbeat acknowledgement timed out' within ${WINDOW_SECONDS}s, so the liveness rule did not run"
	[ "${RETURNED[$name]}" -eq 0 ] && fail "$name did not return to the primary within ${WINDOW_SECONDS}s (primary_state=$(primary_state "ac.$name"))"
done

# Step 5: resume the secondary and confirm the Endpoints stay on the primary. A
# flapping loop would move them back, which is the failure this step catches.
log "--- step 5: SIGCONT the secondary and confirm the return is stable ---"
cleanup
sleep 20
for name in "${ENDPOINTS[@]}"; do
	state=$(primary_state "ac.$name")
	log "  ac.$name primary_state=$state after resume"
	[ "$state" != "online" ] && fail "$name left the primary after the secondary resumed (state=$state), so the return is not stable"
done

log "=== result: failures=$FAILURES ==="
[ "$FAILURES" -eq 0 ] && log "PASS" || log "FAIL"
exit "$FAILURES"
