#!/usr/bin/env bash
set -euo pipefail

workspace_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cli_path=${AGENT_CLUSTER_CLI:-"$workspace_dir/.tmp/u84/bin/agent-cluster-cli"}
server_url=${AGENT_CLUSTER_SERVER_URL:?set AGENT_CLUSTER_SERVER_URL}
token=${AGENT_CLUSTER_TOKEN:?set AGENT_CLUSTER_TOKEN}
session_name=${AGENT_CLUSTER_TMUX_SESSION:-interactive-manual}
artifact_dir=${AGENT_CLUSTER_ARTIFACT_DIR:-"$workspace_dir/.tmp/u84/manual"}
ready_text=${AGENT_CLUSTER_READY_TEXT:-'cluster>'}
timeout_seconds=${AGENT_CLUSTER_START_TIMEOUT_SECONDS:-10}

mkdir -p "$artifact_dir"
if tmux has-session -t "$session_name" 2>/dev/null; then
  printf 'start failed: tmux session already exists: %s\n' "$session_name" >&2
  exit 1
fi
if [[ ! -x "$cli_path" ]]; then
  mkdir -p "$(dirname "$cli_path")"
  (cd "$workspace_dir" && go build -o "$cli_path" ./src/main/agent-cluster-cli)
fi
if [[ ! -x "$cli_path" ]]; then
  printf 'start failed: CLI is not executable: %s\n' "$cli_path" >&2
  exit 1
fi

runner_path="$artifact_dir/interactive-runner.sh"
exit_marker="$artifact_dir/cli-exit"
rm -f "$exit_marker"
cat > "$runner_path" <<'RUNNER'
#!/usr/bin/env bash
set -u
cli_path=$1
server_url=$2
token=$3
exit_marker=$4
"$cli_path" --server-url "$server_url" --token "$token" interactive
status=$?
printf '%s\n' "$status" > "$exit_marker"
sleep 2
exit "$status"
RUNNER
chmod 700 "$runner_path"

tmux new-session -d -s "$session_name" "$runner_path" "$cli_path" "$server_url" "$token" "$exit_marker"
tmux resize-window -t "$session_name" -x "${AGENT_CLUSTER_TMUX_WIDTH:-240}" -y "${AGENT_CLUSTER_TMUX_HEIGHT:-40}"

capture_path="$artifact_dir/start-pane.txt"
deadline=$((SECONDS + timeout_seconds))
while (( SECONDS < deadline )); do
  tmux capture-pane -p -t "$session_name" > "$capture_path" 2>/dev/null || true
  if grep -Fq "$ready_text" "$capture_path"; then
    printf 'interactive session ready: %s\n' "$session_name"
    printf 'pane pid: %s\n' "$(tmux display-message -p -t "$session_name" '#{pane_pid}')"
    exit 0
  fi
  if [[ -f "$exit_marker" ]]; then
    printf 'start failed: CLI exited before ready (code %s)\n' "$(cat "$exit_marker")" >&2
    cat "$capture_path" >&2
    exit 1
  fi
  sleep 0.1
done
printf 'start failed: prompt not ready within %ss\n' "$timeout_seconds" >&2
cat "$capture_path" >&2
exit 1
