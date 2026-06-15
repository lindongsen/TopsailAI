#!/bin/bash
# Local agent session status check wrapper.

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
  Local agent session status check wrapper.
  Uses topsailai_session_status to retrieve the current session status.

Usage:
  $(basename "$0") [OPTIONS]

Options:
  -h, --help    Show this help message and exit

Environment Variables:
  ACS_GROUP_ID          Group ID used as TOPSAILAI_SESSION_ID

Examples:
  ACS_GROUP_ID=test $(basename "$0")

Exit Codes:
  0    Status retrieved successfully
  1    Failed to retrieve status
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

# Map ACS_GROUP_ID to TOPSAILAI_SESSION_ID
export TOPSAILAI_SESSION_ID="${ACS_GROUP_ID:-}"

# Execute topsailai_session_status to get session status
topsailai_session_status
