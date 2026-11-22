#!/usr/bin/env bash
# Shared helpers for the scheduler integration tests.
#
# Every helper is a plain function so the startup script and the interaction
# script can share them without duplicating paths or assertions.

set -u

# PROJECT_ROOT is the repository root, derived from this file's location.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# BINARY is the scheduler built by the Makefile.
BINARY="${PROJECT_ROOT}/bin/topsailai_scheduler"
# WORKSPACE is the temporary project folder the daemon runs in.
WORKSPACE="${PROJECT_ROOT}/.tmp/integration"
# TASKS_ROOT is the task tree under test.
TASKS_ROOT="${WORKSPACE}/tasks"
# MOCK_PROVIDER is the mock provider executable the daemon runs by default.
MOCK_PROVIDER="${PROJECT_ROOT}/providers/mock/bin/mock"
# MOCK_STATE_DIR holds the mock provider's run records, kept out of the source tree.
MOCK_STATE_DIR="${WORKSPACE}/mock-state"
# DAEMON_LOG captures the daemon's stdout and stderr.
DAEMON_LOG="${WORKSPACE}/daemon.log"
# SESSION is the deterministic tmux session name.
SESSION="sched-integration"
# EXIT_FILE records the daemon's exit code, because tmux does not propagate it.
EXIT_FILE="${WORKSPACE}/daemon.exit"

# daemon_pids prints the pid of every running scheduler daemon.
#
# The pattern is anchored to the exact command line on purpose. An unanchored
# `pgrep -f "<binary> run"` also matches the tmux wrapper whose command line
# merely contains that string, and the wrapper appears first. Signalling the
# wrapper kills the shell without forwarding the signal, so the daemon survives
# and never writes its exit code.
daemon_pids() {
	pgrep -f "^${BINARY} run$" 2>/dev/null
}

# FAILURES counts failed assertions so the run can report a summary.
FAILURES=0
# CHECKS counts executed assertions.
CHECKS=0

# log prints a progress line.
log() {
	printf '[integration] %s\n' "$*"
}

# fail records a failed assertion.
fail() {
	CHECKS=$((CHECKS + 1))
	FAILURES=$((FAILURES + 1))
	printf '[integration] FAIL: %s\n' "$*" >&2
}

# pass records a successful assertion.
pass() {
	CHECKS=$((CHECKS + 1))
	printf '[integration] ok: %s\n' "$*"
}

# assert_contains fails unless the file contains the pattern.
assert_contains() {
	local file="$1"
	local pattern="$2"
	local description="$3"
	if grep -qF -- "${pattern}" "${file}"; then
		pass "${description}"
		return 0
	fi
	fail "${description}: ${file} does not contain '${pattern}'"
	return 1
}

# assert_not_contains fails when the file contains the pattern.
assert_not_contains() {
	local file="$1"
	local pattern="$2"
	local description="$3"
	if grep -qF -- "${pattern}" "${file}"; then
		fail "${description}: ${file} unexpectedly contains '${pattern}'"
		return 1
	fi
	pass "${description}"
	return 0
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

# assert_file_exists fails unless the path exists.
assert_file_exists() {
	local path="$1"
	local description="$2"
	if [ -e "${path}" ]; then
		pass "${description}"
		return 0
	fi
	fail "${description}: ${path} does not exist"
	return 1
}

# assert_run_output_contains fails unless some captured run output contains the
# pattern.
#
# The provider owns the run, so the provider owns the run's output. The
# scheduler no longer captures stdout, so a task's own printing is asserted
# against the provider's output files rather than the daemon log.
assert_run_output_contains() {
	local pattern="$1"
	local description="$2"
	if grep -qF -- "${pattern}" "${MOCK_STATE_DIR}"/*.out 2>/dev/null; then
		pass "${description}"
		return 0
	fi
	fail "${description}: no captured run output contains '${pattern}'"
	return 1
}

# assert_process_gone fails while the pid is still alive.
assert_process_gone() {
	local pid="$1"
	local description="$2"
	local waited=0
	while [ "${waited}" -lt 50 ]; do
		if ! kill -0 "${pid}" 2>/dev/null; then
			pass "${description}"
			return 0
		fi
		sleep 0.1
		waited=$((waited + 1))
	done
	fail "${description}: pid ${pid} is still alive"
	return 1
}

# write_task writes the YAML and Markdown files of one task.
#
# Arguments: task id, YAML content, Markdown content.
write_task() {
	local id="$1"
	local yaml_content="$2"
	local markdown_content="$3"
	local dir
	dir="$(dirname "${TASKS_ROOT}/${id}")"
	mkdir -p "${dir}"
	printf '%s' "${yaml_content}" >"${TASKS_ROOT}/${id}.yaml"
	printf '%s' "${markdown_content}" >"${TASKS_ROOT}/${id}.md"
}

# remove_task deletes the YAML and Markdown files of one task.
remove_task() {
	local id="$1"
	rm -f "${TASKS_ROOT}/${id}.yaml" "${TASKS_ROOT}/${id}.md"
	log "removed task ${id}"
}

# scheduler_cli runs the CLI inside the workspace so it finds the same socket.
scheduler_cli() {
	(cd "${WORKSPACE}" && "${BINARY}" "$@")
}

# wait_for_log polls the daemon log for a pattern.
wait_for_log() {
	local pattern="$1"
	local timeout_seconds="${2:-20}"
	local waited=0
	while [ "${waited}" -lt $((timeout_seconds * 10)) ]; do
		if grep -qF -- "${pattern}" "${DAEMON_LOG}" 2>/dev/null; then
			return 0
		fi
		sleep 0.1
		waited=$((waited + 1))
	done
	return 1
}

# wait_for_status polls the CLI status output for a pattern.
wait_for_status() {
	local pattern="$1"
	local timeout_seconds="${2:-20}"
	local waited=0
	while [ "${waited}" -lt $((timeout_seconds * 10)) ]; do
		if scheduler_cli status 2>/dev/null | grep -qF -- "${pattern}"; then
			return 0
		fi
		sleep 0.1
		waited=$((waited + 1))
	done
	return 1
}

# summary prints the assertion summary and returns a non-zero code on failure.
summary() {
	printf '[integration] %d checks, %d failures\n' "${CHECKS}" "${FAILURES}"
	if [ "${FAILURES}" -ne 0 ]; then
		return 1
	fi
	return 0
}

# assert_no_line_with fails when one line contains both patterns.
assert_no_line_with() {
	local file="$1"
	local first="$2"
	local second="$3"
	local description="$4"
	if grep -F -- "${first}" "${file}" 2>/dev/null | grep -qF -- "${second}"; then
		fail "${description}: ${file} has a line with both '${first}' and '${second}'"
		return 1
	fi
	pass "${description}"
	return 0
}

# wait_for_status_absent polls until the CLI status output no longer matches.
wait_for_status_absent() {
	local pattern="$1"
	local timeout_seconds="${2:-20}"
	local waited=0
	while [ "${waited}" -lt $((timeout_seconds * 10)) ]; do
		if ! scheduler_cli status 2>/dev/null | grep -qF -- "${pattern}"; then
			return 0
		fi
		sleep 0.1
		waited=$((waited + 1))
	done
	return 1
}
