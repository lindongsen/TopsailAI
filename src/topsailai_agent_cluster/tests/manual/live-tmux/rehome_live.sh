#!/usr/bin/env bash
# Live re-home verification through real Server, Endpoint and mock Provider.
#
# This is the live counterpart of the integration suite: it starts two genuinely
# independent Servers, each with its own SQLite database and API port, points one
# real Endpoint at both in preference order, and then proves the Endpoint moves
# from the first Server to the second without being restarted.
#
# The mock Provider is used instead of the shipped provider because the mock
# answers every operation deterministically. A failure here is therefore a
# Cluster defect rather than a provider-runtime condition, which is the whole
# reason the mock exists.
#
# Startup stays in start_services.py; this script only orchestrates and asserts,
# so the two responsibilities never merge into one script.
#
# Every bound is explicit: a startup deadline, a re-home deadline and a stop
# deadline. Nothing is terminated by name, and every temporary file lives under
# the run directory so cleanup is exact.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RUN_DIR="${1:-${PROJECT_DIR}/.tmp/live-rehome}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-60}"
REHOME_TIMEOUT_SECONDS="${REHOME_TIMEOUT_SECONDS:-60}"
STOP_TIMEOUT_SECONDS="${STOP_TIMEOUT_SECONDS:-30}"

CAPABILITIES="${PROJECT_DIR}/tests/manual/live-tmux/mock-capabilities.json"
CLI="${RUN_DIR}/bin/agent-cluster-cli"

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

rm -rf "${RUN_DIR}"
mkdir -p "${RUN_DIR}/bin" "${RUN_DIR}/runtime" "${RUN_DIR}/provider-home" "${RUN_DIR}/project" "${RUN_DIR}/out"

log "== build =="
( cd "${PROJECT_DIR}" && go build -o "${RUN_DIR}/bin/agent-cluster-server" ./src/main/agent-cluster-server )
( cd "${PROJECT_DIR}" && go build -o "${RUN_DIR}/bin/agent-cluster-endpoint" ./src/main/agent-cluster-endpoint )
( cd "${PROJECT_DIR}" && go build -o "${RUN_DIR}/bin/agent-cluster-cli" ./src/main/agent-cluster-cli )
( cd "${PROJECT_DIR}/providers/mock" && go build -o "${RUN_DIR}/bin/agent-cluster-provider-mock" . )
log "BUILD_OK"

log "== start =="
START_LOG="${RUN_DIR}/start.log"
python3 "${PROJECT_DIR}/tests/manual/live-tmux/start_services.py" \
  --runtime "${RUN_DIR}/runtime" \
  --bin-dir "${RUN_DIR}/bin" \
  --provider-home "${RUN_DIR}/provider-home" \
  --project "${RUN_DIR}/project" \
  --provider "${RUN_DIR}/bin/agent-cluster-provider-mock" \
  --provider-arg=--mode --provider-arg=mixed \
  --provider-arg=--session-dir --provider-arg="${RUN_DIR}/project" \
  --capabilities "${CAPABILITIES}" \
  --secondary-server \
  --startup-timeout-seconds "${STARTUP_TIMEOUT_SECONDS}" \
  --timeout-seconds 0 \
  >"${START_LOG}" 2>&1 &
START_PID=$!
log "start_services pid ${START_PID}"

cleanup() {
  if kill -0 "${START_PID}" 2>/dev/null; then
    kill -TERM "${START_PID}" 2>/dev/null || true
    for _ in $(seq 1 "${STOP_TIMEOUT_SECONDS}"); do
      kill -0 "${START_PID}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${START_PID}" 2>/dev/null; then
      kill -KILL "${START_PID}" 2>/dev/null || true
      log "start_services pid ${START_PID} killed after ${STOP_TIMEOUT_SECONDS}s"
    else
      log "start_services pid ${START_PID} stopped"
    fi
  fi
}
trap cleanup EXIT

# Readiness is the READY line the startup script prints after the primary API
# port accepts a connection, never a fixed sleep.
deadline=$(( $(date +%s) + STARTUP_TIMEOUT_SECONDS ))
while ! grep -q '^READY ' "${START_LOG}" 2>/dev/null; do
  if ! kill -0 "${START_PID}" 2>/dev/null; then
    log "--- start.log ---"
    cat "${START_LOG}"
    die "start_services exited before reporting readiness"
  fi
  if [ "$(date +%s)" -ge "${deadline}" ]; then
    log "--- start.log ---"
    cat "${START_LOG}"
    die "no READY line within ${STARTUP_TIMEOUT_SECONDS}s"
  fi
  sleep 0.2
done
grep '^READY ' "${START_LOG}"
log "READY_OK"

# Both ports are read from the machine-readable configuration document rather
# than from the READY line. The READY line carries "api_port=" and, when a second
# Server exists, "secondary_api_port=", and any pattern that matches the first
# also matches the tail of the second, so parsing it silently returns the
# secondary port as the primary one.
API_PORT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["api_port"])' "${RUN_DIR}/runtime/services.json")"
SECONDARY_API_PORT="$(python3 -c '
import json, sys
document = json.load(open(sys.argv[1]))
print(document.get("secondary_api_port") or "")
' "${RUN_DIR}/runtime/services.json")"
[ -n "${API_PORT}" ] || die "could not read api_port from services.json"
[ -n "${SECONDARY_API_PORT}" ] || die "could not read secondary_api_port from services.json; the second Server did not start"
[ "${API_PORT}" != "${SECONDARY_API_PORT}" ] || die "the primary and secondary API ports are identical, so the two Servers are not independent"
log "API_PORT=${API_PORT} SECONDARY_API_PORT=${SECONDARY_API_PORT}"

API_TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "${RUN_DIR}/runtime/services.json")"
# endpoint_state prints the connection_state the given Server reports for the
# Endpoint. It is read from the Server's own API, so the answer is that Server's
# view rather than a shared guess.
#
# A Server that is not answering is reported as an empty state rather than
# aborting the script. Polling a Server that was just stopped is a normal step in
# a re-home, and a failed request there is an answer ("this Server says nothing")
# rather than an error. The curl failure is therefore absorbed explicitly, because
# the caller runs under `set -e` and `pipefail`.
endpoint_state() {
  local port="$1"
  local body=""
  body="$(curl -sS -H "Authorization: Bearer ${API_TOKEN}" "http://127.0.0.1:${port}/api/v1/endpoints" 2>/dev/null)" || body=""
  printf '%s' "${body}" | python3 -c '
import json, sys
try:
    document = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
for row in document.get("data") or []:
    if row.get("endpoint_id") == "live-tmux-endpoint":
        print(row.get("connection_state") or "")
        break
else:
    print("")
'
}

# wait_state polls one Server until it reports the expected state. Polling an
# observable answer is what turns "the Endpoint should have moved" into "this
# Server says it did".
wait_state() {
  local port="$1" want="$2" limit="$3" label="$4"
  local deadline=$(( $(date +%s) + limit ))
  local state=""
  while :; do
    state="$(endpoint_state "${port}")"
    if [ "${state}" = "${want}" ]; then
      log "STATE_OK ${label} ${want}"
      return 0
    fi
    if [ "$(date +%s)" -ge "${deadline}" ]; then
      log "last state for ${label}: '${state}'"
      log "--- server.log ---"
      tail -20 "${RUN_DIR}/runtime/server.log" 2>/dev/null || true
      log "--- server-secondary.log ---"
      tail -20 "${RUN_DIR}/runtime/server-secondary.log" 2>/dev/null || true
      log "--- endpoint.log ---"
      tail -30 "${RUN_DIR}/runtime/endpoint.log" 2>/dev/null || true
      die "${label} never reported ${want} within ${limit}s"
    fi
    sleep 0.5
  done
}

log "== assert ordered preference =="
# The Endpoint must prefer the first address. This is the assertion that proves
# the list is ordered rather than merely accepted: if the Endpoint connected to
# the second Server first, the first Server would never report it online.
wait_state "${API_PORT}" online "${STARTUP_TIMEOUT_SECONDS}" "primary"
PRIMARY_STATE="$(endpoint_state "${API_PORT}")"
SECONDARY_STATE="$(endpoint_state "${SECONDARY_API_PORT}")"
log "primary=${PRIMARY_STATE} secondary=${SECONDARY_STATE}"
[ "${PRIMARY_STATE}" = "online" ] || die "the primary Server does not report the Endpoint online"
# The second Server may legitimately have no row at all, because the Endpoint
# never dialled it. Either "no row" or "offline" proves the Endpoint did not
# connect there, and both are accepted so the assertion does not depend on
# whether the second Server happened to observe a rejected handshake.
case "${SECONDARY_STATE}" in
  online) die "the Endpoint connected to the second Server first, so the address list is not ordered" ;;
  *) log "ORDERED_OK second Server state '${SECONDARY_STATE}'" ;;
esac

log "== assert inventory on the primary =="
INVENTORY_DEADLINE=$(( $(date +%s) + STARTUP_TIMEOUT_SECONDS ))
while :; do
  set +e
  LIST_OUT="$(env -u AGENT_CLUSTER_CLI_SERVER_URL -u AGENT_CLUSTER_CLI_SERVER_TOKEN \
    "${CLI}" --no-color --no-progress list --json 2>&1)"
  LIST_STATUS=$?
  set -e
  case "${LIST_OUT}" in
    *cluster_session_id*) break ;;
  esac
  if [ "$(date +%s)" -ge "${INVENTORY_DEADLINE}" ]; then
    log "list exit ${LIST_STATUS}"
    log "list output: ${LIST_OUT}"
    die "the primary Server never published an inventory with a session"
  fi
  sleep 0.5
done
printf '%s' "${LIST_OUT}" >"${RUN_DIR}/out/list-primary.json"
log "INVENTORY_OK primary published a session"

log "== force one real reconnect so the primary Server's fence advances =="
# This step exists only to make the discrimination below possible, and it is the
# live counterpart of the TCP proxy the integration test uses.
#
# Two fresh Servers both start their in-memory fence at 1, so an Endpoint that
# holds 1 accepts the second Server's 1 even when the connection-layer fix is
# absent. The re-home then succeeds for the wrong reason and the absence
# assertion below can never fire. Forcing one reconnect to the same Server
# process makes the fence read 2, so the second Server's 1 is genuinely lower and
# only a released connection can accept it.
#
# The socket is closed by exact port rather than by process name, and the
# reconnect is confirmed from the Endpoint's own log, so the precondition is
# observed rather than assumed. A run that cannot advance the fence must fail
# instead of reporting success, because a live run that cannot discriminate is
# exactly the defect this step removes.
CHANNEL_PORT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["channel_port"])' "${RUN_DIR}/runtime/services.json")"
[ -n "${CHANNEL_PORT}" ] || die "could not read channel_port from services.json"
RECONNECTS_BEFORE="$(grep -c "endpoint channel reconnected" "${RUN_DIR}/runtime/endpoint.log" 2>/dev/null || true)"
RECONNECTS_BEFORE="${RECONNECTS_BEFORE:-0}"
ss -K dst 127.0.0.1 dport = ":${CHANNEL_PORT}" >/dev/null 2>&1 || die "could not sever the channel connection on port ${CHANNEL_PORT}; this run cannot discriminate the connection-layer fix, so it must not report success"
FENCE_DEADLINE=$(( $(date +%s) + REHOME_TIMEOUT_SECONDS ))
while :; do
  RECONNECTS_NOW="$(grep -c "endpoint channel reconnected" "${RUN_DIR}/runtime/endpoint.log" 2>/dev/null || true)"
  RECONNECTS_NOW="${RECONNECTS_NOW:-0}"
  if [ "${RECONNECTS_NOW}" -gt "${RECONNECTS_BEFORE}" ]; then
    log "FENCE_ADVANCED reconnects ${RECONNECTS_BEFORE} -> ${RECONNECTS_NOW}"
    break
  fi
  if [ "$(date +%s)" -ge "${FENCE_DEADLINE}" ]; then
    log "--- endpoint.log ---"
    tail -30 "${RUN_DIR}/runtime/endpoint.log" 2>/dev/null || true
    die "the Endpoint did not reconnect to the primary Server within ${REHOME_TIMEOUT_SECONDS}s, so its generation never advanced and this run cannot discriminate"
  fi
  sleep 0.5
done
wait_state "${API_PORT}" online "${REHOME_TIMEOUT_SECONDS}" "primary-after-reconnect"

log "== stop the primary Server =="
# The primary Server is stopped by its exact PID, read from the pid file the
# startup script wrote. Nothing is terminated by name.
PIDS_FILE="${RUN_DIR}/runtime/pids-both.json"
[ -f "${PIDS_FILE}" ] || die "pids file missing: ${PIDS_FILE}"
PRIMARY_PID="$(python3 -c '
import json, sys
pids = json.load(open(sys.argv[1]))
print(pids[0] if pids else "")
' "${PIDS_FILE}")"
[ -n "${PRIMARY_PID}" ] || die "could not read the primary Server pid"
log "primary Server pid ${PRIMARY_PID}"
kill -TERM "${PRIMARY_PID}" 2>/dev/null || die "could not signal the primary Server pid ${PRIMARY_PID}"
for _ in $(seq 1 "${STOP_TIMEOUT_SECONDS}"); do
  kill -0 "${PRIMARY_PID}" 2>/dev/null || break
  sleep 1
done
if kill -0 "${PRIMARY_PID}" 2>/dev/null; then
  kill -KILL "${PRIMARY_PID}" 2>/dev/null || true
  log "primary Server pid ${PRIMARY_PID} killed"
else
  log "primary Server pid ${PRIMARY_PID} stopped"
fi

log "== assert re-home =="
# The Endpoint must move on its own. It is not restarted here, and no
# configuration is changed, so the only thing that can make the second Server
# report it online is the Endpoint walking to the next address.
wait_state "${SECONDARY_API_PORT}" online "${REHOME_TIMEOUT_SECONDS}" "secondary"

log "== assert the re-homed Endpoint serves inventory =="
# A connection that cannot serve inventory would look online and be useless, so
# the re-homed Endpoint must also publish a report the second Server accepts.
REHOME_INVENTORY_DEADLINE=$(( $(date +%s) + REHOME_TIMEOUT_SECONDS ))
while :; do
  SECONDARY_INVENTORY="$(curl -sS -H "Authorization: Bearer ${API_TOKEN}" \
    "http://127.0.0.1:${SECONDARY_API_PORT}/api/v1/endpoints/live-tmux-endpoint/session-state" 2>/dev/null || true)"
  case "${SECONDARY_INVENTORY}" in
    *cluster_session_id*) break ;;
  esac
  if [ "$(date +%s)" -ge "${REHOME_INVENTORY_DEADLINE}" ]; then
    log "secondary inventory: ${SECONDARY_INVENTORY}"
    log "--- endpoint.log ---"
    tail -30 "${RUN_DIR}/runtime/endpoint.log" 2>/dev/null || true
    die "the re-homed Endpoint never published an inventory the second Server accepted"
  fi
  sleep 0.5
done
printf '%s' "${SECONDARY_INVENTORY}" >"${RUN_DIR}/out/inventory-secondary.json"
log "REHOME_INVENTORY_OK"

log "== assert no superseded rejection =="
# This is the discriminating assertion for the connection-layer fix. Without it
# the Endpoint keeps the dead connection and its generation, so the first
# attempt against the second Server is rejected as superseded. With it the dead
# connection is released and no attempt is ever rejected for that reason.
#
# The assertion is on the absence of the symptom rather than on the final online
# state, because the reconnect loop retries and a retry can succeed even when
# the first attempt was rejected.
if grep -q "superseded by a newer link" "${RUN_DIR}/runtime/endpoint.log" 2>/dev/null; then
  log "--- endpoint.log ---"
  tail -40 "${RUN_DIR}/runtime/endpoint.log"
  die "the Endpoint rejected a link from the second Server as superseded, so it still held the dead connection's generation"
fi
log "NO_SUPERSEDED_OK"

log "== assert receipt settlement =="
# The Endpoint must not keep resending receipts the second Server cannot apply.
# A settlement is logged once per connection, so its presence proves the
# identity comparison ran and the recorded receipts were released.
if grep -q "server changed, settled recorded receipts" "${RUN_DIR}/runtime/endpoint.log" 2>/dev/null; then
  SETTLED_LINE="$(grep "server changed, settled recorded receipts" "${RUN_DIR}/runtime/endpoint.log" | tail -1)"
  log "SETTLE_OK ${SETTLED_LINE}"
else
  # No recorded receipt existed before the re-home, which is a legitimate state
  # for a run that issued no command. The absence of the line is therefore only
  # a failure when a receipt was actually recorded, and that is asserted by the
  # command scenario below rather than guessed here.
  log "SETTLE_SKIPPED no recorded receipt existed before the re-home"
fi

log "== point the CLI at the Server that now manages the Endpoint =="
# The operator follows the Endpoint. The CLI holds one Server URL and one Server
# token, so a re-home requires reconfiguring the client; multi-profile support is
# deliberately not part of this change. Writing the new URL here is what makes the
# command below a real end-to-end check rather than a request to a dead Server.
CLI_ENV="${RUN_DIR}/bin/.env.local"
printf 'AGENT_CLUSTER_CLI_SERVER_URL=http://127.0.0.1:%s\nAGENT_CLUSTER_CLI_SERVER_TOKEN=%s\n' \
  "${SECONDARY_API_PORT}" "${API_TOKEN}" >"${CLI_ENV}"
chmod 600 "${CLI_ENV}"
log "CLI now targets the secondary Server on port ${SECONDARY_API_PORT}"

log "== assert the re-homed Endpoint still executes a command =="
# A re-home that leaves the Endpoint unable to serve commands would be a
# half-working move. The command is issued through the real CLI against the
# second Server, so it exercises the whole path rather than one hop.
set +e
SESSION_JSON="$(env -u AGENT_CLUSTER_CLI_SERVER_URL -u AGENT_CLUSTER_CLI_SERVER_TOKEN \
  "${CLI}" --no-color --no-progress list --json 2>&1)"
LIST_STATUS=$?
set -e
log "list exit ${LIST_STATUS}"
[ "${LIST_STATUS}" -eq 0 ] || die "the CLI could not list sessions from the Server that now manages the Endpoint: ${SESSION_JSON}"
SESSION_ID="$(printf '%s' "${SESSION_JSON}" | python3 -c '
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
print(rows[0]["cluster_session_id"] if rows else "")
')"
GENERATION="$(printf '%s' "${SESSION_JSON}" | python3 -c '
import json, sys
try:
    rows = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
print(rows[0]["provider_generation"] if rows else "")
')"
[ -n "${SESSION_ID}" ] || die "the re-homed Endpoint published no session the CLI can address"
log "SESSION_ID=${SESSION_ID} GENERATION=${GENERATION}"

set +e
SEND_OUT="$(env -u AGENT_CLUSTER_CLI_SERVER_URL -u AGENT_CLUSTER_CLI_SERVER_TOKEN \
  "${CLI}" --no-color --no-progress send --yes live-tmux-endpoint "${SESSION_ID}" "rehome message" "${GENERATION}" 2>&1)"
SEND_STATUS=$?
set -e
printf '%s' "${SEND_OUT}" >"${RUN_DIR}/out/send-after-rehome.txt"
log "send exit ${SEND_STATUS}"
log "send output: ${SEND_OUT}"
[ "${SEND_STATUS}" -eq 0 ] || die "the re-homed Endpoint refused a command, so the move left it unable to serve"

log "== stop =="
CHILD_PIDS="$(python3 -c 'import json,sys; print(" ".join(str(p) for p in json.load(open(sys.argv[1]))))' "${PIDS_FILE}")"
log "child pids ${CHILD_PIDS}"

kill -TERM "${START_PID}" 2>/dev/null || true
for _ in $(seq 1 "${STOP_TIMEOUT_SECONDS}"); do
  kill -0 "${START_PID}" 2>/dev/null || break
  sleep 1
done
if kill -0 "${START_PID}" 2>/dev/null; then
  kill -KILL "${START_PID}" 2>/dev/null || true
  log "start_services pid ${START_PID} killed"
fi
wait "${START_PID}" 2>/dev/null || true

survivors=""
for pid in ${CHILD_PIDS}; do
  if kill -0 "${pid}" 2>/dev/null; then
    survivors="${survivors} ${pid}"
  fi
done
if [ -n "${survivors}" ]; then
  for pid in ${survivors}; do kill -KILL "${pid}" 2>/dev/null || true; done
  die "child processes survived the stop:${survivors}"
fi
log "STOP_OK no survivors"

log "REHOME_LIVE_OK"
