#!/usr/bin/env bash
# Live command sweep through CLI -> Server -> Endpoint -> mock Provider.
#
# This drives the real agent-cluster-cli binary against a real Server and a real
# Endpoint whose configured provider is the mock. Every command the CLI exposes is
# invoked once, its exit status and output are captured, and the result is written
# to a report. The mock is used instead of the shipped provider because the mock
# answers every operation deterministically, so a command that fails is a Cluster
# defect rather than a provider-runtime condition.
#
# Startup stays in start_services.py; this script only orchestrates and asserts, so
# the two responsibilities never merge into one script.
#
# Every bound is explicit: a startup deadline, a per-command deadline and a stop
# deadline. Nothing is terminated by name, and every temporary file lives under the
# run directory so cleanup is exact.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RUN_DIR="${1:-${PROJECT_DIR}/.tmp/live-sweep}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-60}"
COMMAND_TIMEOUT_SECONDS="${COMMAND_TIMEOUT_SECONDS:-30}"
STOP_TIMEOUT_SECONDS="${STOP_TIMEOUT_SECONDS:-30}"

CAPABILITIES="${PROJECT_DIR}/tests/manual/live-tmux/mock-capabilities.json"
ALLOWLIST="${RUN_DIR}/allowlist.conf"
CLI="${RUN_DIR}/bin/agent-cluster-cli"

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

rm -rf "${RUN_DIR}"
mkdir -p "${RUN_DIR}/bin" "${RUN_DIR}/runtime" "${RUN_DIR}/provider-home" "${RUN_DIR}/project" "${RUN_DIR}/out"

# The allowlist is written here rather than shipped, because it is the input of
# this sweep and not a product default. `pwd` is the one entry the sweep needs:
# it proves command.exec reaches the Endpoint's own runner without depending on a
# program that may be absent.
printf 'pwd\n' >"${ALLOWLIST}"

log "== build =="
( cd "${PROJECT_DIR}" && go build -o "${RUN_DIR}/bin/agent-cluster-server" ./src/main/agent-cluster-server )
( cd "${PROJECT_DIR}" && go build -o "${RUN_DIR}/bin/agent-cluster-endpoint" ./src/main/agent-cluster-endpoint )
( cd "${PROJECT_DIR}" && go build -o "${RUN_DIR}/bin/agent-cluster-cli" ./src/main/agent-cluster-cli )
( cd "${PROJECT_DIR}/providers/mock" && go build -o "${RUN_DIR}/bin/agent-cluster-provider-mock" ./src )
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
  --allowlist "${ALLOWLIST}" \
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

# run_cli invokes the CLI with the isolated environment. Inherited AGENT_CLUSTER_*
# variables take precedence over .env.local, so they are cleared exactly as the
# documented launch command does.
run_cli() {
  env -u AGENT_CLUSTER_CLI_SERVER_URL -u AGENT_CLUSTER_CLI_SERVER_TOKEN \
    "${CLI}" --no-color --no-progress "$@"
}

# capture runs one command with a bounded deadline and records its exact result.
# The output is written to a per-command file so a long answer never truncates the
# report, and the exit status is taken from the command itself rather than from a
# pipeline stage. The command is passed as arguments rather than as a shell string,
# so no word is re-split and no quoting is lost.
capture() {
  local name="$1"
  shift
  local out="${RUN_DIR}/out/${name}.txt"
  local start end status
  start=$(date +%s)
  set +e
  timeout "${COMMAND_TIMEOUT_SECONDS}" env -u AGENT_CLUSTER_CLI_SERVER_URL -u AGENT_CLUSTER_CLI_SERVER_TOKEN \
    "${CLI}" --no-color --no-progress "$@" >"${out}" 2>&1
  status=$?
  set -e
  end=$(date +%s)
  printf '%s\t%s\t%s\n' "${name}" "${status}" "$(( end - start ))" >>"${RUN_DIR}/results.tsv"
  log "CMD ${name} exit=${status} elapsed=$(( end - start ))s"
}

: >"${RUN_DIR}/results.tsv"

# The Endpoint registers asynchronously after the API port answers, so the first
# command polls until the Endpoint appears. This is the same readiness fact the
# bounded smoke asserts, reused here instead of a fixed sleep.
assert_deadline=$(( $(date +%s) + STARTUP_TIMEOUT_SECONDS ))
while :; do
  set +e
  ENDPOINTS_OUT="$(run_cli endpoints --json 2>&1)"
  ENDPOINTS_STATUS=$?
  set -e
  case "${ENDPOINTS_OUT}" in
    *live-tmux-endpoint*) break ;;
  esac
  if [ "$(date +%s)" -ge "${assert_deadline}" ]; then
    log "endpoints exit ${ENDPOINTS_STATUS}"
    log "endpoints output: ${ENDPOINTS_OUT}"
    log "--- endpoint.log ---"
    tail -30 "${RUN_DIR}/runtime/endpoint.log" 2>/dev/null || true
    die "the Endpoint did not register within ${STARTUP_TIMEOUT_SECONDS}s"
  fi
  sleep 0.5
done
log "ENDPOINT_REGISTERED"

# The session identity is read from the real inventory rather than assumed, so a
# command that addresses a session uses the identifier the Cluster actually minted.
SESSION_JSON="$(run_cli list --json)"
SESSION_ID="$(printf '%s' "${SESSION_JSON}" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(rows[0]["cluster_session_id"] if rows else "")')"
GENERATION="$(printf '%s' "${SESSION_JSON}" | python3 -c 'import json,sys; rows=json.load(sys.stdin); print(rows[0]["provider_generation"] if rows else "")')"
[ -n "${SESSION_ID}" ] || die "no session in the inventory; the mock discovery did not reach the Cluster"
log "SESSION_ID=${SESSION_ID} GENERATION=${GENERATION}"

# The stopped session is the only target resume can accept: resume authorizes on
# the absence of a live generation, so a running session is refused by design.
# Its identifier is read from the same inventory rather than assumed.
STOPPED_SESSION_ID="$(printf '%s' "${SESSION_JSON}" | python3 -c '
import json, sys
rows = json.load(sys.stdin)
stopped = [r for r in rows if not r.get("provider_generation")]
print(stopped[0]["cluster_session_id"] if stopped else "")
')"
[ -n "${STOPPED_SESSION_ID}" ] || die "no stopped session; the mock mixed mode did not reach the Cluster"
log "STOPPED_SESSION_ID=${STOPPED_SESSION_ID}"
PROVIDER_SESSION_ID="$(printf '%s' "${SESSION_JSON}" | python3 -c '
import json, sys
rows = json.load(sys.stdin)
print(rows[0]["provider_session_id"] if rows else "")
')"
[ -n "${PROVIDER_SESSION_ID}" ] || die "no provider session id in the inventory"
log "PROVIDER_SESSION_ID=${PROVIDER_SESSION_ID}"

# The launch profile identifier is minted by the Endpoint, so it is read from the
# launch-options answer instead of being guessed.
API_PORT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["api_port"])' "${RUN_DIR}/runtime/services.json")"
API_TOKEN="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "${RUN_DIR}/runtime/services.json")"
LAUNCH_JSON="$(curl -sS -H "Authorization: Bearer ${API_TOKEN}" "http://127.0.0.1:${API_PORT}/api/v1/launch-options?endpoint_id=live-tmux-endpoint")"
PROFILE_ID="$(printf '%s' "${LAUNCH_JSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); h=(d.get("data") or {}).get("handlers") or []; print(h[0]["launch_profile_id"] if h else "")')"
PROFILE_REVISION="$(printf '%s' "${LAUNCH_JSON}" | python3 -c 'import json,sys; d=json.load(sys.stdin); h=(d.get("data") or {}).get("handlers") or []; print(h[0]["revision"] if h else "")')"
[ -n "${PROFILE_ID}" ] || die "no launch handler; the mock launch-options query did not reach the Cluster"
log "PROFILE_ID=${PROFILE_ID} PROFILE_REVISION=${PROFILE_REVISION}"

log "== sweep =="

# Read surface. Each command is invoked once with --json so the answer is
# machine-readable and the assertion can name the field it checked.
capture endpoints endpoints --json
capture list list --json
capture list_full list --full --json
capture list_brief list --brief --json
capture list_clean list --clean --json
capture refresh refresh --json
capture show show live-tmux-endpoint --json
capture info info "${SESSION_ID}" --json
capture history history live-tmux-endpoint --json
capture messages messages live-tmux-endpoint "${PROVIDER_SESSION_ID}" --json
capture model model live-tmux-endpoint "${SESSION_ID}" --json
capture logs logs live-tmux-endpoint "${SESSION_ID}" --json
capture help help
capture help_drive help drive

# Mutating surface. Every one of these is confirmed explicitly, because the
# Endpoint refuses an unconfirmed mutation and a sweep that relied on a default
# would prove the refusal rather than the operation.
capture send send --yes live-tmux-endpoint "${SESSION_ID}" "sweep message" "${GENERATION}"
# The command identifier is read from the receipt rather than assumed, so status
# addresses the command the Cluster actually recorded.
SEND_COMMAND_ID="$(sed -n 's/^command_id: //p' "${RUN_DIR}/out/send.txt" | head -1)"
[ -n "${SEND_COMMAND_ID}" ] || die "send produced no command_id; status cannot be addressed"
log "SEND_COMMAND_ID=${SEND_COMMAND_ID}"
capture status status "${SEND_COMMAND_ID}" --json
capture btw btw --yes live-tmux-endpoint "${SESSION_ID}" "sweep context" "${GENERATION}"
capture interrupt interrupt --yes live-tmux-endpoint "${SESSION_ID}" hard "${GENERATION}"
capture drive_start drive start --yes live-tmux-endpoint "${SESSION_ID}" "${GENERATION}"
capture drive_stop drive stop --yes live-tmux-endpoint "${SESSION_ID}" "${GENERATION}"
capture drive_status drive status live-tmux-endpoint "${SESSION_ID}"
capture model_select model --yes --generation "${GENERATION}" live-tmux-endpoint "${SESSION_ID}" fixture-model-b
capture resume resume --yes live-tmux-endpoint "${STOPPED_SESSION_ID}"
capture stop stop --yes live-tmux-endpoint "${SESSION_ID}" "${GENERATION}"
capture clean clean --yes live-tmux-endpoint "${SESSION_ID}" "${GENERATION}"
capture start start --yes --profile "${PROFILE_ID}" --profile-revision "${PROFILE_REVISION}" --task "sweep task" live-tmux-endpoint "${SESSION_ID}"
capture ctl_heartbeat ctl --yes live-tmux-endpoint "${SESSION_ID}" heartbeat '{}' "${GENERATION}"
capture ctl_messages ctl --yes live-tmux-endpoint "${SESSION_ID}" get_session_messages '{}' "${GENERATION}"
capture ctl_probe ctl --yes live-tmux-endpoint "${SESSION_ID}" fixture_probe '{}' "${GENERATION}"
capture exec exec --yes live-tmux-endpoint "${SESSION_ID}" "${GENERATION}" -- pwd

# A refusal is a result too. These two commands must fail, and the sweep records
# the refusal so a silently accepted invalid command is visible.
capture refuse_unknown_command table
capture refuse_unadvertised_ctl ctl --yes live-tmux-endpoint "${SESSION_ID}" not_advertised '{}' "${GENERATION}"

log "== report =="
set +e
python3 - "${RUN_DIR}" <<'PY'
import pathlib
import sys

run = pathlib.Path(sys.argv[1])
results = []
for line in (run / "results.tsv").read_text().splitlines():
    name, status, elapsed = line.split("\t")
    results.append({"name": name, "status": int(status), "elapsed": int(elapsed)})

# The expected outcome of each command. A mutating command must succeed; the two
# refusal probes must fail. Anything else is a defect and is reported as such.
expect_success = {
    "endpoints", "list", "list_full", "list_brief", "list_clean", "refresh",
    "show", "info", "history", "messages", "model", "logs", "status", "help",
    "help_drive", "send", "btw", "interrupt", "drive_start", "drive_stop",
    "drive_status", "model_select", "resume", "stop", "clean", "start",
    "ctl_heartbeat", "ctl_messages", "ctl_probe", "exec",
}
expect_failure = {"refuse_unknown_command", "refuse_unadvertised_ctl"}

# A receipt can report a failure while the process still exits zero, so the exit
# status alone is not evidence that the operation succeeded. These markers are the
# receipt's own statement that the effect was not applied, and any of them turns a
# zero exit into a failure. The marker list is deliberately narrow: a successful
# receipt legitimately carries "not_applied" nowhere, and a read command carries no
# receipt at all.
FAILURE_MARKERS = (
    "Status: rejected",
    "phase: failed",
    "effect_certainty: not_applied",
    "error_code:",
    "server request failed",
)

def receipt_failure(text):
    """Return the first failure marker the receipt states, or an empty string."""
    for marker in FAILURE_MARKERS:
        if marker in text:
            return marker
    return ""

lines = []
failures = 0
for item in results:
    name = item["name"]
    status = item["status"]
    output = (run / "out" / f"{name}.txt").read_text(errors="replace")
    marker = receipt_failure(output)
    if name in expect_success:
        ok = status == 0 and not marker
    elif name in expect_failure:
        ok = status != 0
    else:
        ok = False
    if not ok:
        failures += 1
    detail = f"exit={status}"
    if marker:
        detail += f' receipt="{marker}"'
    lines.append(f"{'PASS' if ok else 'FAIL'}\t{name}\t{detail}\telapsed={item['elapsed']}s")

report = "\n".join(lines) + f"\n\ncommands={len(results)} failures={failures}\n"
(run / "report.txt").write_text(report)
print(report)
sys.exit(1 if failures else 0)
PY
REPORT_STATUS=$?
set -e
log "REPORT_EXIT=${REPORT_STATUS}"

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

[ "${REPORT_STATUS}" -eq 0 ] || die "the sweep reported failures; see ${RUN_DIR}/report.txt"
log "SWEEP_OK"
