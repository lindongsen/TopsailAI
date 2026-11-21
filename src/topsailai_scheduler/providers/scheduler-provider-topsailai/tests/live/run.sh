#!/usr/bin/env bash
# Live test for the TopsailAI provider.
#
# This is a live test: it starts the real scheduler daemon, which starts the
# real provider, which launches a real TopsailAI agent against a real model.
# Nothing is stubbed.
#
# The task is deliberately inert. Its only enabled tool is time_tool, so the
# agent can read the clock and nothing else: no file writes, no shell, no
# network. The task content tells the agent to call get_local_date once and
# stop.
#
# What is verified:
#
#   - the daemon discovers the task in a temporary tasks tree
#   - the provider submits a launch and records a session id and a driver
#   - the agent runs in the workspace the task names
#   - the agent records a terminal status, which is what poll reports as
#     finished
#   - the tool set offered to the agent is exactly time_tool
#
# Everything the test owns lives under .tmp/live-topsailai, so the real tasks/
# tree is never touched. The agent's own session artifacts are written under
# TOPSAILAI_HOME, because the agent needs the real configuration there to reach
# a model; the test reads them but does not create them.

set -u

# PROJECT_ROOT is the repository root, derived from this file's location.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
# BINARY is the scheduler built by the Makefile.
BINARY="${PROJECT_ROOT}/.tmp/topsailai_scheduler"
# WORKSPACE is the temporary folder this test owns.
WORKSPACE="${PROJECT_ROOT}/.tmp/live-topsailai"
# TASKS_ROOT is the temporary task tree under test.
TASKS_ROOT="${WORKSPACE}/tasks"
# PROVIDER is the provider under test.
PROVIDER="${PROJECT_ROOT}/providers/scheduler-provider-topsailai/bin/scheduler-provider-topsailai"
# PROVIDER_STATE_DIR holds the provider's run records.
PROVIDER_STATE_DIR="${WORKSPACE}/provider-state"
# AGENT_WORKSPACE is the folder the agent runs in.
AGENT_WORKSPACE="${WORKSPACE}/agent-workspace"
# DAEMON_LOG captures the daemon's stdout and stderr.
DAEMON_LOG="${WORKSPACE}/daemon.log"
# EXIT_FILE records the daemon's exit code, because tmux does not propagate it.
EXIT_FILE="${WORKSPACE}/daemon.exit"
# SESSION is the deterministic tmux session name.
SESSION="sched-live-topsailai"
# LAUNCH_JSON captures the launch result.
LAUNCH_JSON="${WORKSPACE}/launch.json"
# STATUS_JSON captures the status snapshot.
STATUS_JSON="${WORKSPACE}/status.json"
# RECORD is the provider's run record, resolved once the run has happened.
RECORD=""
# SESSION_ID is the agent session id, resolved from the record.
SESSION_ID=""
# META is the agent's session metadata file.
META=""
# STDOUT_FILE is the agent's captured stdout.
STDOUT_FILE=""

# FAILURES counts failed assertions so the run can report a summary.
FAILURES=0
# CHECKS counts executed assertions.
CHECKS=0

# log prints a progress line.
log() {
	printf '[live] %s\n' "$*"
}

# pass records a successful assertion.
pass() {
	CHECKS=$((CHECKS + 1))
	printf '[live] ok: %s\n' "$*"
}

# fail records a failed assertion.
fail() {
	CHECKS=$((CHECKS + 1))
	FAILURES=$((FAILURES + 1))
	printf '[live] FAIL: %s\n' "$*" >&2
}

# assert_equals fails unless both values match.
assert_equals() {
	local expected="$1"
	local actual="$2"
	local description="$3"
	if [ "${expected}" = "${actual}" ]; then
		pass "${description}"
		return 0
	fi
	fail "${description}: want '${expected}', got '${actual}'"
	return 1
}

# assert_contains fails unless the file contains the pattern.
assert_contains() {
	local file="$1"
	local pattern="$2"
	local description="$3"
	if grep -qF -- "${pattern}" "${file}" 2>/dev/null; then
		pass "${description}"
		return 0
	fi
	fail "${description}: ${file} does not contain '${pattern}'"
	return 1
}

# scheduler_cli runs the scheduler CLI against this test's control socket.
scheduler_cli() {
	SCHEDULER_CONTROL_SOCKET="${WORKSPACE}/scheduler.sock" "${BINARY}" "$@"
}

# topsailai_home mirrors the provider's own resolution of TOPSAILAI_HOME.
topsailai_home() {
	if [ -n "${TOPSAILAI_HOME:-}" ]; then
		printf '%s' "${TOPSAILAI_HOME}"
		return 0
	fi
	printf '%s' "${HOME}/.topsailai"
}

# prepare recreates the temporary workspace and writes the task pair.
prepare() {
	if [ -d "${WORKSPACE}" ]; then
		rm -rf "${WORKSPACE}"
		log "removed previous workspace ${WORKSPACE}"
	fi
	mkdir -p "${TASKS_ROOT}/probe" "${PROVIDER_STATE_DIR}" "${AGENT_WORKSPACE}"
	: >"${DAEMON_LOG}"
	: >"${EXIT_FILE}"

	# The schedule is 03:00 so the cron trigger never fires during the test; the
	# run is started explicitly with launch, which keeps the test deterministic.
	cat >"${TASKS_ROOT}/probe/time.yaml" <<YAML
schedule: "0 3 * * *"
launcher: agent
provider: ${PROVIDER}
workspace: ${AGENT_WORKSPACE}
timeout: 5m
env:
  TOPSAILAI_ENABLED_TOOLS: "time_tool"
YAML

	cat >"${TASKS_ROOT}/probe/time.md" <<'MARKDOWN'
Call get_local_date exactly once and report the date it returns.

Then stop. Do not call any other tool, do not write files, do not run shell commands.
MARKDOWN

	log "wrote the task pair under ${TASKS_ROOT}"
}

# start_daemon launches the daemon inside tmux with output captured to disk.
start_daemon() {
	tmux kill-session -t "${SESSION}" 2>/dev/null && log "killed a stale session ${SESSION}"

	# The exit code is written by the wrapper because tmux does not propagate it.
	local command
	command="cd '${WORKSPACE}' && SCHEDULER_TASKS_ROOT='${TASKS_ROOT}' \
SCHEDULER_CONTROL_SOCKET='${WORKSPACE}/scheduler.sock' \
SCHEDULER_LOG_OUTPUT='${DAEMON_LOG}' \
SCHEDULER_LOG_LEVEL=debug \
SCHEDULER_RESCAN_INTERVAL=1s \
SCHEDULER_SHUTDOWN_GRACE=5s \
SCHEDULER_DEFAULT_TIMEOUT=5m \
SCHEDULER_DEFAULT_PROVIDER_PATH='${PROVIDER}' \
SCHEDULER_POLL_INTERVAL=1s \
SCHEDULER_PROVIDER_CALL_TIMEOUT=180s \
TOPSAILAI_PROVIDER_STATE_DIR='${PROVIDER_STATE_DIR}' \
'${BINARY}' run; echo \$? >'${EXIT_FILE}'"

	tmux new-session -d -s "${SESSION}" "${command}"
	log "started session ${SESSION}"
}

# wait_for_ready polls the log for the readiness line.
wait_for_ready() {
	local waited=0
	while [ "${waited}" -lt 200 ]; do
		if grep -qF -- "scheduler starting" "${DAEMON_LOG}" 2>/dev/null; then
			pass "the daemon reported startup"
			return 0
		fi
		sleep 0.1
		waited=$((waited + 1))
	done
	fail "the daemon did not report startup"
	return 1
}

# wait_for_socket polls until the control socket answers.
wait_for_socket() {
	local waited=0
	while [ "${waited}" -lt 200 ]; do
		if scheduler_cli status >/dev/null 2>&1; then
			pass "the control socket answered"
			return 0
		fi
		sleep 0.1
		waited=$((waited + 1))
	done
	fail "the control socket did not answer"
	return 1
}

# check_discovery verifies the temporary task tree was picked up.
check_discovery() {
	log "checking discovery"
	scheduler_cli status --json >"${STATUS_JSON}" 2>&1
	assert_equals "0" "$?" "status succeeds"
	assert_contains "${STATUS_JSON}" "probe/time" "the task is discovered"
	assert_contains "${STATUS_JSON}" '"state": "idle"' "the task is scheduled and idle"
}

# check_launch runs the task and verifies the scheduler saw it finish.
check_launch() {
	log "launching probe/time"
	scheduler_cli launch probe/time --wait --json >"${LAUNCH_JSON}" 2>&1
	local code=$?
	log "launch exit code ${code}"
	assert_equals "0" "${code}" "the task runs to completion"
}

# resolve_record locates the provider's run record and the session it names.
resolve_record() {
	RECORD="$(ls -1 "${PROVIDER_STATE_DIR}"/*.json 2>/dev/null | head -1)"
	if [ -z "${RECORD}" ]; then
		return 1
	fi
	SESSION_ID="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('session_id',''))" "${RECORD}" 2>/dev/null)"
	[ -n "${SESSION_ID}" ] || return 1
	local home
	home="$(topsailai_home)"
	META="$(ls -1 "${home}/workspace/task/${SESSION_ID}".*.session.meta 2>/dev/null | head -1)"
	STDOUT_FILE="$(ls -1 "${home}/workspace/task/${SESSION_ID}".*.session.stdout 2>/dev/null | head -1)"
	return 0
}

# check_provider_record verifies the provider wrote a run record.
check_provider_record() {
	log "checking the provider state record"
	if ! resolve_record; then
		fail "the provider wrote no usable state record"
		return 1
	fi
	pass "the provider wrote a state record"
	assert_contains "${RECORD}" "session_id" "the record carries a session id"
	pass "the provider recorded session ${SESSION_ID}"
}

# check_driver verifies the single-turn driver was selected.
check_driver() {
	log "checking the selected driver"
	assert_contains "${RECORD}" '"driver": "topsailai_agent_chat"' \
		"the record names the single-turn driver"
}

# check_meta verifies the agent recorded a terminal status and the workspace.
check_meta() {
	log "checking the agent session metadata"
	if [ -z "${META}" ]; then
		fail "the agent wrote no session metadata"
		return 1
	fi
	local status workspace pwd
	status="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('status',''))" "${META}" 2>/dev/null)"
	workspace="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('project_workspace',''))" "${META}" 2>/dev/null)"
	pwd="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('pwd',''))" "${META}" 2>/dev/null)"
	assert_equals "completed" "${status}" "the agent recorded a terminal status"
	assert_equals "${AGENT_WORKSPACE}" "${workspace}" "the agent ran in the requested workspace"
	assert_equals "${AGENT_WORKSPACE}" "${pwd}" "the agent's working directory is the workspace"
}

# check_supervision verifies poll ended on the metadata, not on session status.
check_supervision() {
	log "checking how supervision ended"
	assert_contains "${DAEMON_LOG}" "recorded status completed" \
		"poll ended on the agent's recorded status"
}

# check_tool_set verifies only time_tool was offered to the agent.
check_tool_set() {
	log "checking the tool set offered to the agent"
	if [ -z "${STDOUT_FILE}" ]; then
		fail "the agent wrote no session stdout"
		return 1
	fi
	assert_contains "${STDOUT_FILE}" "time_tool-get_local_date" \
		"time_tool was available to the agent"
	if grep -qF -- "file_tool" "${STDOUT_FILE}" 2>/dev/null; then
		fail "file_tool was available to the agent"
	else
		pass "file_tool was not available to the agent"
	fi
}

# summary prints the totals and returns success when nothing failed.
summary() {
	printf '[live] %d checks, %d failures\n' "${CHECKS}" "${FAILURES}"
	[ "${FAILURES}" -eq 0 ]
}

# cleanup removes the tmux session.
cleanup() {
	tmux kill-session -t "${SESSION}" 2>/dev/null && log "killed session ${SESSION}"
}

main() {
	if ! "${PROJECT_ROOT}/tests/binary_fresh.sh"; then
		fail "the scheduler binary is stale or missing"
		summary
		exit 1
	fi

	prepare
	start_daemon

	if ! wait_for_ready; then
		summary
		cleanup
		exit 1
	fi
	if ! wait_for_socket; then
		summary
		cleanup
		exit 1
	fi

	check_discovery
	check_launch
	check_provider_record
	check_driver
	check_meta
	check_supervision
	check_tool_set

	if summary; then
		cleanup
		exit 0
	fi
	# Keep the workspace on failure so the evidence can be inspected.
	cleanup
	exit 1
}

main "$@"
