#!/bin/bash
# Local agent chat wrapper.

set -euo pipefail

# Get the absolute path of the script and its directory
EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")

# Switch to the script's directory
cd "${EXE_FOLDER}" || exit 1

# Show help information
show_help() {
    cat <<EOF
Description:
  Local agent chat wrapper.
  Uses topsailai_agent_chat or topsailai_llm_chat to send a message to the local agent.

Usage:
  $(basename "$0") [OPTIONS]

Options:
  -h, --help    Show this help message and exit

Environment Variables:
  ACS_GROUP_ID          Group ID mapped to SESSION_ID
  ACS_AGENT_PROMPT      Agent prompt mapped to SYSTEM_PROMPT
  ACS_AGENT_MESSAGE     Message content mapped to TOPSAILAI_USER_MESSAGE
  ACS_AGENT_MODE        Agent mode: "chat" or "agent" (default: agent)
  ACS_AGENT_TYPE        Agent type: "manager-agent" or other

Examples:
  ACS_GROUP_ID=test ACS_AGENT_PROMPT="say hello" ACS_AGENT_MESSAGE="hi" $(basename "$0")
  ACS_AGENT_MODE=chat ACS_AGENT_TYPE=manager-agent ACS_GROUP_ID=test ACS_AGENT_MESSAGE="hi" $(basename "$0")

Exit Codes:
  0    Chat completed successfully
  1    Chat failed or required parameter missing
EOF
}

# Parse command-line arguments
if [[ "$#" -gt 0 ]]; then
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            show_help >&2
            exit 1
            ;;
    esac
fi

# Map ACS_* environment variables to topsailai_agent_chat variables
export SESSION_ID="${ACS_GROUP_ID:-}"
export SYSTEM_PROMPT="${ACS_AGENT_PROMPT:-}"
export TOPSAILAI_USER_MESSAGE="${ACS_AGENT_MESSAGE:-}"

# Validate required parameters
if [[ -z "$SESSION_ID" ]]; then
    echo "Error: SESSION_ID is required but not set (check ACS_GROUP_ID)" >&2
    exit 1
fi

if [[ -z "$TOPSAILAI_USER_MESSAGE" ]]; then
    echo "Error: TOPSAILAI_USER_MESSAGE is required but not set (check ACS_AGENT_MESSAGE)" >&2
    exit 1
fi

# Determine which chat command to use based on ACS_AGENT_MODE and ACS_AGENT_TYPE
AGENT_MODE="${ACS_AGENT_MODE:-agent}"
AGENT_TYPE="${ACS_AGENT_TYPE:-}"

if [[ "$AGENT_MODE" == "chat" && "$AGENT_TYPE" == "manager-agent" ]]; then
    # Case 1: chat mode with manager-agent → use topsailai_llm_chat
    export TOPSAILAI_USER_MESSAGE
    topsailai_llm_chat
else
    # Disable interactive mode for scripted execution
    export TOPSAILAI_INTERACTIVE_MODE="0"

    if [[ "$AGENT_MODE" == "chat" && "$AGENT_TYPE" != "manager-agent" ]]; then
        # Case 2: chat mode with non-manager-agent → append warning message
        TOPSAILAI_USER_MESSAGE="${TOPSAILAI_USER_MESSAGE}
! DONOT INVOKE ANY TOOLS/SKILLS, Think directly and give the final answer !"
        export TOPSAILAI_USER_MESSAGE
    fi

    # Case 3: default → use topsailai_agent_chat
    topsailai_agent_chat
fi
