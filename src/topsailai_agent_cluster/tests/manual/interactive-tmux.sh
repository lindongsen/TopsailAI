#!/bin/sh
set -eu
: "${AGENT_CLUSTER_CLI:?set AGENT_CLUSTER_CLI to the built CLI path}"
: "${AGENT_CLUSTER_SERVER_URL:?set AGENT_CLUSTER_SERVER_URL}"
: "${AGENT_CLUSTER_TOKEN:?set AGENT_CLUSTER_TOKEN}"
: "${AGENT_CLUSTER_TMUX_SESSION:?set a unique tmux session name}"
tmux new-session -d -s "$AGENT_CLUSTER_TMUX_SESSION" \
  "$AGENT_CLUSTER_CLI --server-url $AGENT_CLUSTER_SERVER_URL --token $AGENT_CLUSTER_TOKEN interactive"
trap 'tmux kill-session -t "$AGENT_CLUSTER_TMUX_SESSION" 2>/dev/null || true' EXIT INT TERM
sleep 1
tmux capture-pane -p -t "$AGENT_CLUSTER_TMUX_SESSION"
tmux wait-for -S "$AGENT_CLUSTER_TMUX_SESSION" 2>/dev/null || true
