#!/usr/bin/env bash
# Startup script for the scheduler integration test.
#
# It prepares a temporary project folder, writes the initial task tree, and
# starts the daemon inside a deterministic tmux session. Readiness is polled from
# the daemon log, never assumed from a sleep.
#
# The interaction script (run.sh) drives the assertions; this script only
# prepares and launches.

set -u

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

# prepare_workspace recreates the temporary project folder.
prepare_workspace() {
	if [ -d "${WORKSPACE}" ]; then
		rm -rf "${WORKSPACE}"
		log "removed previous workspace ${WORKSPACE}"
	fi
	mkdir -p "${TASKS_ROOT}"
	: >"${DAEMON_LOG}"
	: >"${EXIT_FILE}"
}

# write_initial_tasks writes the task tree the daemon starts with.
write_initial_tasks() {
	# A nested task that succeeds quickly.
	write_task "data/work" \
		'schedule: "0 8 * * *"
launcher: command
command: /bin/sh
args: ["-c", "echo work-ran"]
' \
		'# Work task

Print a line so the run is observable.
'

	# A deeply nested task, to prove nesting depth is unlimited.
	write_task "daily/nightly/report" \
		'schedule: "0 3 * * *"
launcher: command
command: /bin/sh
args: ["-c", "echo report-ran"]
' \
		'# Report task

Print a line so the run is observable.
'

	# A task whose Markdown file is missing, to prove a broken task is reported
	# and never runs.
	mkdir -p "${TASKS_ROOT}/broken"
	printf 'schedule: "0 8 * * *"\n' >"${TASKS_ROOT}/broken/nocontent.yaml"

	# A task with an unknown YAML key, to prove strict parsing.
	write_task "broken/typo" \
		'schedule: "0 8 * * *"
schedul: "0 9 * * *"
' \
		'# Typo task

The unknown key must be rejected.
'

	# A task that ignores SIGTERM, to prove a timeout kills the whole group.
	write_task "slow/timeout" \
		'schedule: "0 8 * * *"
launcher: command
command: /bin/sh
args: ["-c", "sleep 120"]
timeout: 2s
' \
		'# Timeout task

Sleeps far longer than its timeout.
'

	# A task that spawns a grandchild, to prove the process group is killed.
	write_task "slow/grandchild" \
		'schedule: "0 8 * * *"
launcher: command
command: /bin/sh
args: ["-c", "sleep 120 & echo grandchild-started; wait"]
timeout: 2s
' \
		'# Grandchild task

Spawns a child that must not survive the timeout.
'
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
SCHEDULER_DEFAULT_TIMEOUT=30s \
SCHEDULER_DEFAULT_PROVIDER_PATH='${MOCK_PROVIDER}' \
SCHEDULER_POLL_INTERVAL=200ms \
MOCK_PROVIDER_STATE_DIR='${MOCK_STATE_DIR}' \
'${BINARY}' run; echo \$? >'${EXIT_FILE}'"

	tmux new-session -d -s "${SESSION}" "${command}"
	log "started session ${SESSION}"
}

# wait_for_ready polls the log for the readiness line.
wait_for_ready() {
	if wait_for_log "scheduler starting" 20; then
		pass "daemon reported startup"
		return 0
	fi
	fail "daemon did not report startup"
	return 1
}

# wait_for_socket polls until the control socket answers.
wait_for_socket() {
	local waited=0
	while [ "${waited}" -lt 200 ]; do
		if scheduler_cli status >/dev/null 2>&1; then
			pass "control socket answered"
			return 0
		fi
		sleep 0.1
		waited=$((waited + 1))
	done
	fail "control socket did not answer"
	return 1
}

main() {
	if ! "${PROJECT_ROOT}/tests/binary_fresh.sh"; then
		fail "the scheduler binary is stale or missing"
		summary
		exit 1
	fi

	prepare_workspace
	write_initial_tasks
	start_daemon
	wait_for_ready
	wait_for_socket
	summary
}

main "$@"
