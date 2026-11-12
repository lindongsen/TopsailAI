#!/usr/bin/env bash
set -euo pipefail

EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "$EXE_FILE")
workspace_dir=$(cd "$EXE_FOLDER/../.." && pwd)
start_script=${AGENT_CLUSTER_START_SCRIPT:-"$workspace_dir/tests/manual/u124_numeric_selection_start.sh"}
server_url=${AGENT_CLUSTER_CLI_SERVER_URL:?set AGENT_CLUSTER_CLI_SERVER_URL}
token=${AGENT_CLUSTER_CLI_SERVER_TOKEN:-${AGENT_CLUSTER_SERVER_AUTH_TOKEN:-}}
if [[ -z "$token" ]]; then printf '%s\n' 'start failed: set AGENT_CLUSTER_CLI_SERVER_TOKEN or AGENT_CLUSTER_SERVER_AUTH_TOKEN' >&2; exit 1; fi
cli_path=${AGENT_CLUSTER_CLI:-"$workspace_dir/.tmp/u124/unit-b/bin/agent-cluster-cli"}
session_name=${AGENT_CLUSTER_TMUX_SESSION:-u124-numeric-selection}
artifact_dir=${AGENT_CLUSTER_ARTIFACT_DIR:-"$workspace_dir/.tmp/u124/unit-b/manual"}
timeout_seconds=${AGENT_CLUSTER_INTERACTION_TIMEOUT_SECONDS:-10}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  cat <<'HELP'
Usage: u124_numeric_selection_tmux.sh

Run the owned numeric-selection tmux interaction and capture its output.
HELP
  exit 0
fi
mkdir -p "$artifact_dir"
capture_path="$artifact_dir/interaction-pane.txt"
verification_log="$artifact_dir/verification.log"
exit_marker="$artifact_dir/cli-exit"
session_id_file="$artifact_dir/session-id"
handoff_marker="$artifact_dir/handoff-ready"
handoff_ack="$artifact_dir/handoff-ack"
: > "$verification_log"
: > "$capture_path"
: > "$exit_marker"
: > "$session_id_file"
: > "$handoff_marker"
: > "$handoff_ack"
owned_session_id=""
handoff_invalid=0

cleanup() {
  local status=0
  if (( handoff_invalid )); then
    printf 'cleanup: refusing unvalidated session handoff\n' >&2
    return 1
  fi
  [[ -n "$owned_session_id" ]] || return 0
  if ! tmux has-session -t "$owned_session_id" 2>/dev/null; then
    printf 'cleanup: owned session already absent %s\n' "$owned_session_id" >&2
    return 0
  fi
  printf 'cleanup: removing owned tmux session %s\n' "$owned_session_id" >&2
  if ! tmux kill-session -t "$owned_session_id"; then
    printf 'cleanup: kill-session failed for %s\n' "$owned_session_id" >&2
    status=1
  elif tmux has-session -t "$owned_session_id" 2>/dev/null; then
    printf 'cleanup: session still exists after kill attempt %s\n' "$owned_session_id" >&2
    status=1
  else
    printf 'cleanup: confirmed session absent %s\n' "$owned_session_id" >&2
  fi
  return "$status"
}
fail() { printf 'FAIL: %s\n' "$1" >&2; [[ -n "$owned_session_id" ]] && tmux capture-pane -p -t "$owned_session_id" >> "$capture_path" 2>/dev/null || true; exit 1; }

snapshot() { tmux capture-pane -p -S - -E - -t "$owned_session_id" 2>/dev/null || fail 'owned tmux session disappeared'; }
delta() {
  local before=$1 after
  after=$(snapshot)
  if [[ "$after" == "$before" ]]; then return 1; fi
  if [[ "$after" == "$before"* ]]; then printf '%s' "${after#"$before"}"; return 0; fi
  fail 'tmux pane changed without preserving the prior snapshot prefix'
}
wait_delta_regex() {
  local before=$1 pattern=$2 deadline=$((SECONDS + timeout_seconds)) text
  while (( SECONDS < deadline )); do
    text=$(delta "$before" 2>/dev/null || true)
    if [[ -n "$text" ]] && grep -Eq -- "$pattern" <<< "$text"; then printf '%s' "$text"; return 0; fi
    sleep 0.1
  done
  fail "timed out waiting for new output matching: $pattern"
}
wait_delta_fixed() {
  local before=$1 text=$2 deadline=$((SECONDS + timeout_seconds)) new
  while (( SECONDS < deadline )); do
    new=$(delta "$before" 2>/dev/null || true)
    if [[ -n "$new" ]] && grep -Fq -- "$text" <<< "$new"; then printf '%s' "$new"; return 0; fi
    sleep 0.1
  done
  fail "timed out waiting for new exact line: $text"
}
last_prompt() { grep -Eo 'cluster\[[^]]+\]>|cluster>' | tail -n 1; }
send_line() { tmux send-keys -t "$owned_session_id" -l -- "$1"; tmux send-keys -t "$owned_session_id" Enter; }
escape_ere() { sed 's/[.[\*^$(){}?+|/\\]/\\&/g'; }
trap cleanup EXIT INT TERM

if tmux has-session -t "$session_name" 2>/dev/null; then printf 'start refused: tmux session already exists: %s\n' "$session_name" >&2; exit 1; fi
trap cleanup EXIT INT TERM

AGENT_CLUSTER_CLI="$cli_path" AGENT_CLUSTER_CLI_SERVER_URL="$server_url" AGENT_CLUSTER_CLI_SERVER_TOKEN="$token" AGENT_CLUSTER_TMUX_SESSION="$session_name" AGENT_CLUSTER_ARTIFACT_DIR="$artifact_dir" AGENT_CLUSTER_SESSION_ID_FILE="$session_id_file" AGENT_CLUSTER_HANDOFF_MARKER="$handoff_marker" AGENT_CLUSTER_HANDOFF_ACK="$handoff_ack" "$start_script" &
start_pid=$!
handoff_deadline=$((SECONDS + timeout_seconds))
while [[ ! -s "$handoff_marker" || ! -s "$session_id_file" ]]; do
  if ! kill -0 "$start_pid" 2>/dev/null; then
    wait "$start_pid" || true
    handoff_invalid=1
    fail 'launcher exited before publishing a complete cleanup handoff'
  fi
  if (( SECONDS >= handoff_deadline )); then
    handoff_invalid=1
    kill "$start_pid" 2>/dev/null || true
    wait "$start_pid" || true
    fail 'launcher did not publish a complete cleanup handoff before timeout'
  fi
  sleep 0.1
done
recorded_session_id=$(cat "$session_id_file")
recorded_handoff_id=$(cat "$handoff_marker")
if [[ ! "$recorded_session_id" =~ ^\$[0-9]+$ || "$recorded_handoff_id" != "$recorded_session_id" ]]; then
  handoff_invalid=1
  kill "$start_pid" 2>/dev/null || true
  wait "$start_pid" || true
  fail 'launcher published a mismatched or invalid session identity'
fi
owned_session_id="$recorded_session_id"
# Keep the receiver cleanup trap armed across validated ownership publication.
trap cleanup EXIT INT TERM
printf '%s\n' "$owned_session_id" > "$handoff_ack" || fail 'unable to acknowledge cleanup handoff'
if ! wait "$start_pid"; then
  fail 'launcher failed after cleanup handoff acknowledgement'
fi

before=$(snapshot); send_line list; list_text=$(wait_delta_regex "$before" '^[[:space:]]*1[[:space:]]+')
row_count=$(awk '/^[[:space:]]*[0-9]+[[:space:]]+/{value=$1+0; if(value>max)max=value} END{print max+0}' <<< "$list_text")
[[ "$row_count" =~ ^[1-9][0-9]*$ ]] || fail 'list did not expose a positive dynamic row count'
workspace_prompt=$(last_prompt <<< "$list_text"); [[ "$workspace_prompt" == cluster\> ]] || fail 'list did not produce workspace prompt'
printf 'workspace prompt: %s\n' "$workspace_prompt" >> "$verification_log"
list_row=$(awk -F '│' '/^[[:space:]]*[0-9]+[[:space:]]*│/{gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2); gsub(/^[[:space:]]+|[[:space:]]+$/, "", $5); print $2 "\t" $5; exit}' <<< "$list_text")
expected_endpoint_host=${list_row%%$'\t'*}; expected_provider_session_id=${list_row#*$'\t'}
[[ -n "$expected_endpoint_host" && -n "$expected_provider_session_id" ]] || fail 'list row did not expose identities'
host_re=$(printf '%s' "$expected_endpoint_host" | escape_ere); provider_re=$(printf '%s' "$expected_provider_session_id" | escape_ere)
before=$(snapshot); send_line 1; session_prompt_re="^cluster\[$host_re/$provider_re\]>$"; session_text=$(wait_delta_regex "$before" "$session_prompt_re"); session_prompt=$(last_prompt <<< "$session_text"); [[ "$session_prompt" =~ $session_prompt_re ]] || fail 'numeric selection prompt identity mismatch'; printf 'bare 1 prompt: %s\n' "$session_prompt" >> "$verification_log"

before=$(snapshot); send_line 'cd ..'; endpoint_text=$(wait_delta_regex "$before" "^cluster\\[$host_re/[^/]+\\]>$"); endpoint_prompt=$(last_prompt <<< "$endpoint_text"); [[ "$endpoint_prompt" == cluster["$expected_endpoint_host"/* ]] || fail 'endpoint hostname mismatch'; printf 'cd .. prompt: %s\n' "$endpoint_prompt" >> "$verification_log"
before=$(snapshot); send_line 'cd 1'; wait_delta_fixed "$before" "$session_prompt" >> "$verification_log"
before=$(snapshot); send_line logs; logs_text=$(wait_delta_regex "$before" '^observed_at: [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$'); grep -Eq '^observed_at: [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$' <<< "$logs_text" || fail 'logs omitted a readable timestamp'; printf 'logs limitation: RenderSnapshot exposes timestamp/truncation/content, not session identity\n%s\n' "$logs_text" >> "$verification_log"
before=$(snapshot); send_line 'help cd'; help_text=$(wait_delta_fixed "$before" 'Syntax: cd [target]'); grep -Fq 'valid replacement' <<< "$help_text" || fail 'help cd omitted replacement semantics'; printf '%s\n' "$help_text" >> "$verification_log"
before=$(snapshot); send_line 'cd ..'; wait_delta_fixed "$before" "$endpoint_prompt" >> "$verification_log"
invalid_row=$((row_count + 1)); before=$(snapshot); send_line "$invalid_row"; error_text=$(wait_delta_regex "$before" "^error: row $invalid_row is out of range; valid rows are 1-$row_count$"); error_line=$(grep -E "^error: row $invalid_row is out of range; valid rows are 1-$row_count$" <<< "$error_text" | tail -n 1); usage_line=$(grep -Fx 'usage: cd [target]' <<< "$error_text" | tail -n 1); next_line=$(grep -Fx 'next: Run help cd for valid syntax.' <<< "$error_text" | tail -n 1); [[ "$error_line" == "error: row $invalid_row is out of range; valid rows are 1-$row_count" && "$usage_line" == 'usage: cd [target]' && "$next_line" == 'next: Run help cd for valid syntax.' ]] || fail 'invalid-row diagnostic did not exactly match three-line contract'; diagnostic_text=$(printf '%s\n%s\n%s' "$error_line" "$usage_line" "$next_line"); [[ "$(printf '%s\n' "$diagnostic_text" | wc -l)" -eq 3 ]] || fail 'invalid-row diagnostic was not exactly three non-empty lines'; printf 'invalid row diagnostic:\n%s\n' "$diagnostic_text" >> "$verification_log"

send_line quit; deadline=$((SECONDS + timeout_seconds)); while (( SECONDS < deadline )); do if [[ -s "$exit_marker" ]]; then exit_code=$(cat "$exit_marker"); [[ "$exit_code" == 0 ]] || fail "CLI exit code was $exit_code"; snapshot >> "$capture_path"; [[ -s "$capture_path" ]] || fail 'final interaction capture is empty'; printf 'PASS: list, bare-number selection, cd .., explicit cd, logs, help and invalid-row handling\nCLI_EXIT=%s\n' "$exit_code" | tee -a "$verification_log"; exit 0; fi; sleep 0.1; done; fail 'CLI did not report exit after quit'
