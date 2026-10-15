#!/bin/sh
# Start one interactive TopsailAI CLI inside an owned tmux session.
#
# This script only launches the program and exposes readiness. It never sends
# input, asserts output, or performs cleanup; those belong to the interaction
# script and the Python harness.
#
# Usage: start_two_layer_cli.sh <cli-name> <endpoint> <run-dir> <interpreter-bin>
#   cli-name: agent_chats | plan_tasks
set -eu

cli_name=$1
endpoint=$2
run_dir=$3

root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
venv=${4:?fourth argument must identify the test interpreter directory}

mkdir -p "$run_dir/home" "$run_dir/tmp"
printf '%s\n' 'Minimal BDD test prompt.' > "$run_dir/minimal.prompt"

export PATH="$venv:$PATH"
export HOME="$run_dir/home"
export XDG_CONFIG_HOME="$run_dir/home/config"
export XDG_CACHE_HOME="$run_dir/home/cache"
export TMPDIR="$run_dir/tmp"

export OPENAI_API_KEY=mock
export OPENAI_MODEL=bdd-agent
export OPENAI_API_BASE="$endpoint"
export OPENAI_BASE_URL="$endpoint"

export LLM_RESPONSE_STREAM=1
export TOPSAILAI_USE_TOOL_CALLS=0
export TOPSAILAI_AUTO_SESSION_NAME_ENABLED=0
export TOPSAILAI_SESSION_ID="$(basename "$run_dir")"
export SESSION_ID="$(basename "$run_dir")"
export TOPSAILAI_INPUT_PIPE_ENABLED=1
export TOPSAILAI_INPUT_PIPE_TIMEOUT=60
export PURE_SYSTEM_PROMPT=1
export TOPSAILAI_CONTEXT_LOAD_USER_MD_ENABLED=0
export SYSTEM_PROMPT="$run_dir/minimal.prompt"
export SYSTEM_PROMPT_EXTRA_FILES=""
export TOPSAILAI_HOME="$run_dir/home/.topsailai"
export TOPSAILAI_DISABLED_TOOLS='human_tool;story_memory_tool;skill_tool'
export UV_NO_DEV=1
export CONTEXT_HISTORY_MANAGERS="sql.ChatHistorySQLAlchemy conn=sqlite:///$run_dir/history.db;"
export TOPSAILAI_CHAT_INTERACTIVE_MODE=0
export TOPSAILAI_PRINT_COLOR_ENABLED=0
export NO_COLOR=1
export TOPSAILAI_PRINT_STEP_MODE=normal
export TOPSAILAI_CONTEXT_USER_MESSAGE=""
export TOPSAILAI_PLUGIN_TOOLS=""
export TOPSAILAI_PLUGIN_INSTRUCTIONS=""
export TOPSAILAI_PLUGIN_SKILLS=""
export TOPSAILAI_CONFIGURED_HOOKS_ENABLED=0
export TOPSAILAI_EVENTS_FILE_PATH="$run_dir/session.events"
export PYTHONPYCACHEPREFIX="$run_dir/pycache"
export TOPSAILAI_PROJECT_WORKSPACE="$run_dir"
export TOPSAILAI_PROJECT_WORKSPACE_LOCK_ENABLED=0
export TOPSAILAI_AGENT_NAME=BDDManager
export DEBUG=0
unset CHAT_MULTI_LINE
cd "$run_dir"

case "$cli_name" in
  agent_chats)
    exec "$root/bin/agent_chats"
    ;;
  plan_tasks)
    exec "$root/bin/topsailai_agent_plan_tasks"
    ;;
  *)
    echo "unknown cli: $cli_name" >&2
    exit 2
    ;;
esac
