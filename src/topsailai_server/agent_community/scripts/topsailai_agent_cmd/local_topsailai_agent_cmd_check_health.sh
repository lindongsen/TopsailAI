#!/bin/bash
# Local agent health check wrapper. Always returns healthy.

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
  Local agent health check wrapper. Always returns healthy.

Usage:
  $(basename "$0") [OPTIONS]

Options:
  -h, --help    Show this help message and exit

Examples:
  $(basename "$0")
  ACS_AGENT_API_BASE=http://127.0.0.1:7373 $(basename "$0")

Exit Codes:
  0    Always returns 0 (healthy)
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

# Always return healthy
echo '{"code":0,"data":{"status":"healthy"}}'
exit 0
