#!/usr/bin/env bash
set -euo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "$EXE_FILE")
workspace_dir=$(cd "$EXE_FOLDER/../.." && pwd)
cli_path=${AGENT_CLUSTER_CLI:-"$workspace_dir/.tmp/u124/unit-b/bin/agent-cluster-cli"}
server_url=${AGENT_CLUSTER_SERVER_URL:?set AGENT_CLUSTER_SERVER_URL}
token=${AGENT_CLUSTER_TOKEN:-${AGENT_CLUSTER_AUTH_TOKEN:-}}
if [[ -z "$token" ]]; then printf '%s\n' 'start failed: set AGENT_CLUSTER_TOKEN or AGENT_CLUSTER_AUTH_TOKEN' >&2; exit 1; fi
session_name=${AGENT_CLUSTER_TMUX_SESSION:-u124-numeric-selection}
artifact_dir=${AGENT_CLUSTER_ARTIFACT_DIR:-"$workspace_dir/.tmp/u124/unit-b/manual"}
session_id_file=${AGENT_CLUSTER_SESSION_ID_FILE:-"$artifact_dir/session-id"}
handoff_marker=${AGENT_CLUSTER_HANDOFF_MARKER:-}
handoff_ack=${AGENT_CLUSTER_HANDOFF_ACK:-}
timeout_seconds=${AGENT_CLUSTER_START_TIMEOUT_SECONDS:-10}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  cat <<'HELP'
Usage: u124_numeric_selection_start.sh

Launch the numeric-selection CLI in a new test-owned tmux session.
HELP
  exit 0
fi

mkdir -p "$artifact_dir"
if tmux has-session -t "$session_name" 2>/dev/null; then
  printf 'start failed: tmux session already exists: %s\n' "$session_name" >&2
  exit 1
fi
if [[ ! -x "$cli_path" ]]; then printf 'start failed: CLI is not executable: %s\n' "$cli_path" >&2; exit 1; fi
runner_path="$artifact_dir/u124-runner.sh"
exit_marker="$artifact_dir/cli-exit"
: > "$exit_marker"
cat > "$runner_path" <<'RUNNER'
#!/usr/bin/env bash
set -u
cli_path=$1; server_url=$2; token=$3; exit_marker=$4
"$cli_path" --server-url "$server_url" --token "$token" interactive
status=$?
printf '%s\n' "$status" > "$exit_marker"
sleep 2
exit "$status"
RUNNER
chmod 700 "$runner_path"

owned_session_id=""
cleanup() {
  local status=0
  [[ -n "$owned_session_id" ]] || return 0
  printf 'cleanup: removing owned tmux session %s\n' "$owned_session_id" >&2
  if tmux kill-session -t "$owned_session_id"; then
    if tmux has-session -t "$owned_session_id" 2>/dev/null; then
      printf 'cleanup: session still exists after kill attempt %s\n' "$owned_session_id" >&2
      status=1
    else
      printf 'cleanup: confirmed session absent %s\n' "$owned_session_id" >&2
    fi
  else
    printf 'cleanup: kill-session failed for %s\n' "$owned_session_id" >&2
    status=1
  fi
  return "$status"
}
trap cleanup EXIT INT TERM

owned_session_id=$(tmux new-session -d -P -F '#{session_id}' -s "$session_name" "$runner_path" "$cli_path" "$server_url" "$token" "$exit_marker")
if [[ ! "$owned_session_id" =~ ^\$[0-9]+$ ]]; then
  printf 'start failed: tmux returned invalid session id\n' >&2
  owned_session_id=""
  exit 1
fi
if ! printf '%s\n' "$owned_session_id" > "$session_id_file"; then
  printf 'start failed: unable to record session identity\n' >&2
  exit 1
fi
if ! tmux resize-window -t "$owned_session_id" -x "${AGENT_CLUSTER_TMUX_WIDTH:-240}" -y "${AGENT_CLUSTER_TMUX_HEIGHT:-40}"; then
  printf 'start failed: unable to resize owned session\n' >&2
  exit 1
fi
capture_path="$artifact_dir/start-pane.txt"
deadline=$((SECONDS + timeout_seconds))
while (( SECONDS < deadline )); do
  tmux capture-pane -p -t "$owned_session_id" > "$capture_path" 2>/dev/null || true
  if grep -Fq 'cluster>' "$capture_path"; then
    printf 'interactive session ready: %s (%s)\n' "$session_name" "$owned_session_id"
    printf 'pane pid: %s\n' "$(tmux display-message -p -t "$owned_session_id" '#{pane_pid}')"
    if [[ -n "$handoff_marker" ]]; then
      printf '%s\n' "$owned_session_id" > "$handoff_marker" || {
        printf 'start failed: unable to publish handoff marker\n' >&2
        exit 1
      }
      if [[ -z "$handoff_ack" ]]; then
        printf 'start failed: handoff acknowledgement path is missing\n' >&2
        exit 1
      fi
      ack_deadline=$((SECONDS + timeout_seconds))
      while (( SECONDS < ack_deadline )); do
        if [[ -s "$handoff_ack" ]] && [[ "$(cat "$handoff_ack")" == "$owned_session_id" ]]; then
          trap - EXIT INT TERM
          exit 0
        fi
        sleep 0.1
      done
      printf 'start failed: handoff acknowledgement timed out\n' >&2
      exit 1
    fi
    exit 0
  fi
  if [[ -s "$exit_marker" ]]; then
    printf 'start failed: CLI exited before ready (code %s)\n' "$(cat "$exit_marker")" >&2
    cat "$capture_path" >&2
    exit 1
  fi
  sleep 0.1
done
printf 'start failed: prompt not ready within %ss\n' "$timeout_seconds" >&2
cat "$capture_path" >&2
exit 1
