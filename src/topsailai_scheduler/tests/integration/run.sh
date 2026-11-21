#!/usr/bin/env bash
# Interaction script for the scheduler integration test.
#
# It drives the running daemon through the real CLI and asserts the observable
# behaviour: discovery, strict parsing, locking, timeout kill, hot reload, the
# control contract, and shutdown without orphans.
#
# The daemon is started by startup.sh; this script only interacts and asserts.

set -u

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

# STATUS_OUT captures the last status output for assertions.
STATUS_OUT="${WORKSPACE}/status.out"
# CLI_OUT captures the last CLI output.
CLI_OUT="${WORKSPACE}/cli.out"

# check_discovery verifies nested tasks are discovered under their relative ids.
check_discovery() {
	log "checking discovery"
	scheduler_cli status >"${STATUS_OUT}" 2>&1
	assert_contains "${STATUS_OUT}" "data/work" "nested task data/work is discovered"
	assert_contains "${STATUS_OUT}" "daily/nightly/report" "deeply nested task is discovered"
	assert_contains "${STATUS_OUT}" "0 8 * * *" "the schedule is reported"
}

# check_strict_parsing verifies a missing Markdown file and an unknown YAML key
# are both reported as invalid tasks and never scheduled.
check_strict_parsing() {
	log "checking strict parsing"
	assert_contains "${DAEMON_LOG}" "missing task content file" "a missing .md file is reported"
	assert_contains "${DAEMON_LOG}" "task file rejected" "a rejected task file is logged"
	assert_contains "${DAEMON_LOG}" "schedul" "the unknown key is named in the error"

	scheduler_cli status >"${STATUS_OUT}" 2>&1
	assert_contains "${STATUS_OUT}" "invalid" "a broken task is reported as invalid"
	assert_no_line_with "${DAEMON_LOG}" "task scheduled" "nocontent" "a task without content is never scheduled"
}

# check_launch verifies a launch runs the task and reports its outcome.
check_launch() {
	log "checking launch"
	scheduler_cli launch data/work --wait >"${CLI_OUT}" 2>&1
	assert_equals "0" "$?" "launch --wait exits successfully"
	assert_contains "${CLI_OUT}" "exit code: 0" "the run reports exit code 0"
	assert_run_output_contains "work-ran" "the run output is captured"
	assert_contains "${DAEMON_LOG}" "run finished" "the run is logged as finished"
}

# check_launch_errors verifies the contract errors are reported with a stable
# exit code.
check_launch_errors() {
	log "checking launch errors"
	scheduler_cli launch does/not/exist >"${CLI_OUT}" 2>&1
	assert_equals "1" "$?" "launching an unknown task fails"
	assert_contains "${CLI_OUT}" "task not found" "the unknown task error is reported"

	scheduler_cli launch data/work extra >"${CLI_OUT}" 2>&1
	assert_equals "2" "$?" "launching with two task ids is a usage error"
}

# check_lock verifies a second launch of a running task starts no new run.
check_lock() {
	log "checking the task lock"
	write_task "slow/locked" \
		'schedule: "0 8 * * *"
launcher: command
command: /bin/sh
args: ["-c", "sleep 30"]
' \
		'# Locked task

Sleeps so a second launch overlaps.
'
	wait_for_status "slow/locked" 20

	scheduler_cli launch slow/locked >"${CLI_OUT}" 2>&1
	assert_equals "0" "$?" "the first launch succeeds"
	assert_contains "${CLI_OUT}" "started, pid" "the first launch reports a pid"

	scheduler_cli launch slow/locked >"${CLI_OUT}" 2>&1
	assert_contains "${CLI_OUT}" "already running" "the second launch is skipped"

	assert_file_exists "${TASKS_ROOT}/slow/locked.lock" "the lock file exists"

	scheduler_cli stop slow/locked >"${CLI_OUT}" 2>&1
	assert_equals "0" "$?" "stopping the running task succeeds"
	assert_contains "${CLI_OUT}" "stop requested" "the stop is reported as a request"
	wait_for_status "idle" 20
}

# check_timeout verifies a run exceeding its timeout is killed.
check_timeout() {
	log "checking the timeout"
	scheduler_cli launch slow/timeout --wait >"${CLI_OUT}" 2>&1
	assert_contains "${CLI_OUT}" "timed out: yes" "the run reports a timeout"
	assert_contains "${DAEMON_LOG}" "run timed out" "the timeout is logged"
}

# check_grandchild verifies the whole process group is killed, so no orphan
# survives the timeout.
check_grandchild() {
	log "checking the process group kill"
	scheduler_cli launch slow/grandchild --wait >"${CLI_OUT}" 2>&1
	assert_contains "${CLI_OUT}" "timed out: yes" "the run reports a timeout"
	assert_run_output_contains "grandchild-started" "the grandchild started"

	# A surviving grandchild would still be sleeping; count the sleepers that
	# belong to this workspace's task.
	local survivors
	survivors="$(pgrep -f 'sleep 120' 2>/dev/null | wc -l)"
	assert_equals "0" "${survivors}" "no grandchild survived the timeout"
}

# check_hot_reload verifies adding and removing task files takes effect without
# a restart.
check_hot_reload() {
	log "checking hot reload"
	write_task "hot/added" \
		'schedule: "0 4 * * *"
launcher: command
command: /bin/sh
args: ["-c", "echo hot-ran"]
' \
		'# Hot task

Added while the daemon runs.
'
	if wait_for_status "hot/added" 20; then
		pass "a task added while running is scheduled"
	else
		fail "a task added while running was not scheduled"
	fi

	scheduler_cli launch hot/added --wait >"${CLI_OUT}" 2>&1
	assert_contains "${CLI_OUT}" "exit code: 0" "the added task runs"

	remove_task "hot/added"
	if wait_for_status_absent "hot/added" 20; then
		pass "a removed task is unscheduled"
	else
		fail "a removed task is still reported"
	fi
	assert_contains "${DAEMON_LOG}" "task removed" "the removal is logged"
}

# check_status_json verifies the JSON snapshot is machine readable.
check_status_json() {
	log "checking the JSON snapshot"
	scheduler_cli status --json >"${STATUS_OUT}" 2>&1
	assert_equals "0" "$?" "status --json exits successfully"
	assert_contains "${STATUS_OUT}" '"tasks_root"' "the snapshot reports the tasks root"
	assert_contains "${STATUS_OUT}" '"state"' "the snapshot reports task states"
}

# check_shutdown verifies SIGTERM stops the daemon and leaves no orphan.
check_shutdown() {
	log "checking shutdown"
	local daemon_pid
	daemon_pid="$(daemon_pids | head -1)"
	if [ -z "${daemon_pid}" ]; then
		fail "the daemon pid was not found"
		return 1
	fi

	kill -TERM "${daemon_pid}"
	assert_process_gone "${daemon_pid}" "the daemon exited after SIGTERM"

	local waited=0
	while [ "${waited}" -lt 100 ]; do
		if [ -s "${EXIT_FILE}" ]; then
			break
		fi
		sleep 0.1
		waited=$((waited + 1))
	done
	assert_equals "0" "$(cat "${EXIT_FILE}" 2>/dev/null)" "the daemon exited with code 0"
	assert_contains "${DAEMON_LOG}" "scheduler stopped" "the shutdown is logged"
	assert_not_contains "${DAEMON_LOG}" "grace period expired" "the shutdown was graceful"

	local orphans
	orphans="$(daemon_pids | wc -l)"
	assert_equals "0" "${orphans}" "no daemon process survived"
}

# cleanup removes the tmux session and the temporary workspace.
cleanup() {
	tmux kill-session -t "${SESSION}" 2>/dev/null && log "killed session ${SESSION}"
	if [ -d "${WORKSPACE}" ]; then
		rm -rf "${WORKSPACE}"
		log "removed workspace ${WORKSPACE}"
	fi
}

main() {
	check_discovery
	check_strict_parsing
	check_launch
	check_launch_errors
	check_lock
	check_timeout
	check_grandchild
	check_hot_reload
	check_status_json
	check_shutdown

	if summary; then
		cleanup
		exit 0
	fi
	# Keep the workspace on failure so the evidence can be inspected.
	tmux kill-session -t "${SESSION}" 2>/dev/null
	exit 1
}

main "$@"
