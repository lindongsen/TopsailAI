#!/bin/bash
#
# Author: DawsonLin
# Email: lin_dongsen@126.com
# Created: 2026-04-13
# Purpose:
#   Summarizer script for agent_daemon to summarize messages for a session.
#   This script is called by the Croner job for daily message summarization.
#
# Environment variables when running:
#   - TOPSAILAI_SESSION_ID: Session identifier
#   - TOPSAILAI_TASK: Message content to summarize
#   - TOPSAILAI_AGENT_DAEMON_HOST: Daemon host (default: localhost)
#   - TOPSAILAI_AGENT_DAEMON_PORT: Daemon port (default: 7373)
#

set -e

# Get environment variables
SESSION_ID="${TOPSAILAI_SESSION_ID}"
TASK="${TOPSAILAI_TASK}"
HOST="${TOPSAILAI_AGENT_DAEMON_HOST:-localhost}"
PORT="${TOPSAILAI_AGENT_DAEMON_PORT:-7373}"
BASE_URL="http://${HOST}:${PORT}"

# Logging function
log_info() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: $*"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

# Validate required environment variables
validate_env() {
    if [ -z "${SESSION_ID}" ]; then
        log_error "Missing required environment variable: TOPSAILAI_SESSION_ID"
        exit 1
    fi

    if [ -z "${TASK}" ]; then
        log_error "Missing required environment variable: TOPSAILAI_TASK"
        exit 1
    fi

    log_info "Session ID: ${SESSION_ID}"
    log_info "Base URL: ${BASE_URL}"
}

# Main summarization logic
# This is a placeholder - in production, this would call an AI service
summarize_messages() {
    log_info "Starting message summarization for session: ${SESSION_ID}"

    # The summarization result would typically be stored or sent somewhere
    # For now, we just log the task content
    log_info "Message content to summarize: ${TASK}"

    # Placeholder: In a real implementation, you would:
    # 1. Call an AI service to summarize the messages
    # 2. Store the summary in the database
    # 3. Or send it to another API endpoint
    TOPSAILAI_INTERACTIVE_MODE=0 topsailai_agent_call_instruction -i "/ctx.summarize" -p "0 0"

    log_info "Summarization completed for session: ${SESSION_ID}"
}

# Main entry point
main() {
    log_info "Summarizer script started"

    validate_env
    summarize_messages

    log_info "Summarizer script completed successfully"
    exit 0
}

# Run main function
main