#!/usr/bin/env bash
set -euo pipefail

workspace_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
start_script="$workspace_dir/tests/manual/interactive-start.sh"
server_url=${AGENT_CLUSTER_SERVER_URL:?set AGENT_CLUSTER_SERVER_URL}
token=${AGENT_CLUSTER_TOKEN:?set AGENT_CLUSTER_TOKEN}
session_name=${AGENT_CLUSTER_TMUX_SESSION:-interactive-manual}
artifact_dir=${AGENT_CLUSTER_ARTIFACT_DIR:-"$workspace_dir/.tmp/u84/manual"}
endpoint_id=${AGENT_CLUSTER_FIXTURE_ENDPOINT:-endpoint-1}
session_id=${AGENT_CLUSTER_FIXTURE_SESSION:-res_21bf07e992bf467d18db9d4a8ea8bd68}
timeout_seconds=${AGENT_CLUSTER_INTERACTION_TIMEOUT_SECONDS:-10}

mkdir -p "$artifact_dir"
capture_path="$artifact_dir/interactive-pane.txt"
exit_marker="$artifact_dir/cli-exit"
cleanup_status=0
cleanup() {
  if tmux has-session -t "$session_name" 2>/dev/null; then
    printf 'cleanup: killing owned tmux session %s\n' "$session_name" >&2
    tmux kill-session -t "$session_name" || cleanup_status=1
  fi
}
trap cleanup EXIT INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  tmux capture-pane -p -t "$session_name" 2>/dev/null || true
  exit 1
}

capture() {
  tmux capture-pane -p -t "$session_name" > "$capture_path" 2>/dev/null || fail 'owned tmux session disappeared'
}

wait_for_text() {
  local text=$1
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    capture
    if grep -Fq "$text" "$capture_path"; then
      return 0
    fi
    sleep 0.1
  done
  fail "timed out waiting for: $text"
}

pane_snapshot() {
  tmux capture-pane -p -t "$session_name" 2>/dev/null || true
}

new_lines() {
  local baseline=$1
  awk 'NR==FNR { seen[$0]++; next } { if (seen[$0] > 0) { seen[$0]-- } else { print } }' \
    <(printf '%s\n' "$baseline") "$capture_path"
}

wait_for_new_text() {
  local text=$1
  local baseline=$2
  local deadline=$((SECONDS + timeout_seconds))
  while (( SECONDS < deadline )); do
    capture
    if new_lines "$baseline" | grep -Fq "$text"; then
      return 0
    fi
    sleep 0.1
  done
  fail "timed out waiting for new text: $text"
}

send_line() {
  tmux send-keys -t "$session_name" -l -- "$1"
  tmux send-keys -t "$session_name" Enter
}

AGENT_CLUSTER_CLI=${AGENT_CLUSTER_CLI:-"$workspace_dir/.tmp/u84/bin/agent-cluster-cli"} \
AGENT_CLUSTER_SERVER_URL="$server_url" \
AGENT_CLUSTER_TOKEN="$token" \
AGENT_CLUSTER_TMUX_SESSION="$session_name" \
AGENT_CLUSTER_ARTIFACT_DIR="$artifact_dir" \
"$start_script"

wait_for_text 'cluster>'
# The startup inventory renders the table before the first prompt.
wait_for_text 'ENDPOINT'
wait_for_text 'ADAPTER'
wait_for_text 'SESSION'
wait_for_text 'STATE'
wait_for_text 'STALE'
wait_for_text 'UNKNOWN'
wait_for_text 'COLLECTION'
wait_for_text 'LAST_SUCCESS'

# Workspace scope rejects send before any payload parsing.
baseline=$(pane_snapshot)
send_line 'send {}'
wait_for_new_text 'command "send" is unavailable in workspace scope' "$baseline"

# Endpoint scope is entered by endpoint id and still rejects send.
baseline=$(pane_snapshot)
send_line "cd $endpoint_id"
wait_for_new_text "/$endpoint_id]>" "$baseline"
baseline=$(pane_snapshot)
send_line 'send {}'
wait_for_new_text 'command "send" is unavailable in endpoint scope' "$baseline"

# Session scope accepts status and the scope-grouped help.
baseline=$(pane_snapshot)
send_line "cd $session_id"
wait_for_new_text "/$session_id]>" "$baseline"
baseline=$(pane_snapshot)
send_line 'status'
wait_for_new_text 'running' "$baseline"
baseline=$(pane_snapshot)
send_line 'help'
wait_for_new_text 'Commands by scope:' "$baseline"

# Bare cd returns to workspace scope.
baseline=$(pane_snapshot)
send_line 'cd'
wait_for_new_text 'cluster>' "$baseline"
send_line 'quit'

deadline=$((SECONDS + timeout_seconds))
while (( SECONDS < deadline )); do
  if [[ -f "$exit_marker" ]]; then
    exit_code=$(cat "$exit_marker")
    [[ "$exit_code" == 0 ]] || fail "CLI exit code was $exit_code, expected 0"
    capture
    printf 'PASS: startup list, scope navigation, matrix restriction, status, help and quit assertions\n'
    printf 'CLI_EXIT=%s\n' "$exit_code"
    exit 0
  fi
  sleep 0.1
done
fail 'CLI did not report exit after quit'
