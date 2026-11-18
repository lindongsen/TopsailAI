#!/usr/bin/env bash
# Bounded live smoke for the Provider CLI path.
#
# This is the automated counterpart of the interactive tmux procedure: it starts
# the real Server, Endpoint and Provider CLI, waits for an observable readiness
# signal, asserts one real CLI answer, then stops every child by its exact PID.
# Startup stays in start_services.py; this script only orchestrates and asserts,
# so the two responsibilities never merge into one script.
#
# Every bound is explicit: a startup deadline, a run deadline and a stop deadline.
# Nothing is terminated by name, and every temporary file lives under the run
# directory so cleanup is exact.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RUN_DIR="${1:-${PROJECT_DIR}/.tmp/unit8/live-smoke}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-60}"
RUN_TIMEOUT_SECONDS="${RUN_TIMEOUT_SECONDS:-45}"
STOP_TIMEOUT_SECONDS="${STOP_TIMEOUT_SECONDS:-30}"
# The Endpoint credential mode is opt-in. When it is unset the Endpoint keeps the
# permissive configuration it always had, so the default smoke proves exactly what
# it proved before and a mode regression cannot hide behind a changed default.
ENDPOINT_AUTH_MODE="${ENDPOINT_AUTH_MODE:-}"
# The Endpoint credential the probe presents. The pair form is required in HMAC
# mode, because a bare token cannot be signed; bearer mode accepts either.
ENDPOINT_CREDENTIAL="${ENDPOINT_CREDENTIAL:-live-tmux-endpoint-token}"

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

rm -rf "${RUN_DIR}"
mkdir -p "${RUN_DIR}/bin" "${RUN_DIR}/runtime" "${RUN_DIR}/provider-home" "${RUN_DIR}/project"

log "== build =="
( cd "${PROJECT_DIR}" && go build -o "${RUN_DIR}/bin/agent-cluster-server" ./src/main/agent-cluster-server )
( cd "${PROJECT_DIR}" && go build -o "${RUN_DIR}/bin/agent-cluster-endpoint" ./src/main/agent-cluster-endpoint )
( cd "${PROJECT_DIR}" && go build -o "${RUN_DIR}/bin/agent-cluster-cli" ./src/main/agent-cluster-cli )
( cd "${PROJECT_DIR}/providers/topsailai" && go build -o "${RUN_DIR}/bin/agent-cluster-provider-topsailai" ./src )
log "BUILD_OK"

log "== start =="
START_LOG="${RUN_DIR}/start.log"
# The mode arguments are assembled rather than always passed, because an empty
# --endpoint-auth-mode would be rejected by the parser and an omitted flag is what
# keeps the default scenario on the Endpoint's own default.
MODE_ARGS=()
if [ -n "${ENDPOINT_AUTH_MODE}" ]; then
  POLICY_DIR="${RUN_DIR}/policy"
  mkdir -p "${POLICY_DIR}"
  # The policy file is written here rather than shipped as a fixture so the
  # credential the probe presents and the secret the Endpoint verifies cannot
  # drift apart. A fixture would be a second copy of the same secret.
  #
  # The grant is conditional because the two HMAC scenarios need different
  # policies from the same credential. With the grant, a valid signature is
  # accepted; without it, the same valid signature is refused by the policy. That
  # pair is what proves the two refusal classes are distinguishable rather than
  # collapsed into one.
  {
    printf '# Live smoke policy for the Endpoint credential probe.\n'
    printf 'token %s\n' "${ENDPOINT_CREDENTIAL}"
    printf 'endpoints live-tmux-endpoint\n'
    if [ -z "${ENDPOINT_NO_GRANT:-}" ]; then
      printf 'permissions launch.query\n'
    else
      printf '# No grant is declared, so a verified credential is refused by policy.\n'
      printf 'permissions command.exec\n'
    fi
  } >"${POLICY_DIR}/probe.conf"
  MODE_ARGS+=(--endpoint-auth-mode "${ENDPOINT_AUTH_MODE}" --endpoint-policy-dir "${POLICY_DIR}")
  log "endpoint auth mode ${ENDPOINT_AUTH_MODE}"
fi
python3 "${PROJECT_DIR}/tests/manual/live-tmux/start_services.py" \
  --runtime "${RUN_DIR}/runtime" \
  --bin-dir "${RUN_DIR}/bin" \
  --provider-home "${RUN_DIR}/provider-home" \
  --project "${RUN_DIR}/project" \
  --provider "${RUN_DIR}/bin/agent-cluster-provider-topsailai" \
  --startup-timeout-seconds "${STARTUP_TIMEOUT_SECONDS}" \
  --timeout-seconds "${RUN_TIMEOUT_SECONDS}" \
  ${MODE_ARGS[@]+"${MODE_ARGS[@]}"} \
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

# Readiness is the READY line the startup script prints after the API port
# accepts a connection, never a fixed sleep.
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

API_PORT="$(sed -n 's/^READY .*api_port=\([0-9]*\).*/\1/p' "${START_LOG}" | head -1)"
[ -n "${API_PORT}" ] || die "could not read api_port from the READY line"

log "== assert =="
# The CLI reads .env.local beside its own executable, which start_services.py
# wrote. Inherited AGENT_CLUSTER_* variables would take precedence, so they are
# cleared exactly as the documented launch command does.
#
# The API port answering is not the same fact as the Endpoint having registered:
# the Endpoint dials the channel after it starts and retries until the Server
# accepts. So the assertion polls the real CLI answer until it names the
# Endpoint, bounded by the same startup deadline, instead of sleeping a guessed
# amount and hoping the registration landed.
assert_deadline=$(( $(date +%s) + STARTUP_TIMEOUT_SECONDS ))
CLI_EXIT=1
CLI_OUTPUT=""
while :; do
  set +e
  CLI_OUTPUT="$(env -u AGENT_CLUSTER_CLI_SERVER_URL -u AGENT_CLUSTER_CLI_SERVER_TOKEN \
    "${RUN_DIR}/bin/agent-cluster-cli" endpoints --json 2>&1)"
  CLI_EXIT=$?
  set -e
  case "${CLI_OUTPUT}" in
    *live-tmux-endpoint*) break ;;
  esac
  if [ "$(date +%s)" -ge "${assert_deadline}" ]; then
    log "cli exit ${CLI_EXIT}"
    log "cli output: ${CLI_OUTPUT}"
    log "--- endpoint.log ---"
    tail -20 "${RUN_DIR}/runtime/endpoint.log" 2>/dev/null || true
    die "the Endpoint did not register within ${STARTUP_TIMEOUT_SECONDS}s"
  fi
  sleep 0.5
done
log "cli exit ${CLI_EXIT}"
log "cli output: ${CLI_OUTPUT}"
[ "${CLI_EXIT}" -eq 0 ] || die "agent-cluster-cli endpoints exited ${CLI_EXIT}"
log "ASSERT_OK endpoint advertised"

# The credential probe runs only when a mode was requested, because the default
# scenario has no policy directory and therefore no credential to prove. Running it
# unconditionally would either fail on a permissive Endpoint or force every existing
# scenario to adopt a policy it never needed.
if [ -n "${ENDPOINT_AUTH_MODE}" ]; then
  log "== endpoint credential probe =="
  PROBE_MODE="${ENDPOINT_AUTH_MODE}"
  if [ "${ENDPOINT_AUTH_MODE}" = "hmac" ] && [ -n "${ENDPOINT_NO_GRANT:-}" ]; then
    PROBE_MODE="hmac-no-grant"
  fi
  python3 "${PROJECT_DIR}/tests/manual/live-tmux/endpoint_credential_probe.py" \
    --runtime "${RUN_DIR}/runtime" \
    --mode "${PROBE_MODE}" \
    --credential "${ENDPOINT_CREDENTIAL}" \
    || die "the Endpoint credential probe failed in ${PROBE_MODE} mode"
  log "PROBE_ASSERT_OK ${PROBE_MODE}"
fi

log "== stop =="
PIDS_FILE="${RUN_DIR}/runtime/pids-both.json"
[ -f "${PIDS_FILE}" ] || die "pids file missing: ${PIDS_FILE}"
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

log "SMOKE_OK"
