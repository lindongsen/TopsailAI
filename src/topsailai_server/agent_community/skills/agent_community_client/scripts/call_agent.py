#!/usr/bin/env python3
"""
call_agent.py - Execute the call_agent workflow for ACS.

Workflow:
1. Send a message to a group mentioning an agent
2. Trigger the agent manually via the trigger API
3. Poll for the agent's response message

Environment Variables:
    ACS_AGENT_ID        - member_id (required)
    ACS_AGENT_NAME      - member_name (optional, defaults to ACS_AGENT_ID)
    ACS_AGENT_TYPE      - member_type (optional, defaults to "worker-agent")
    ACS_AGENT_TIMEOUT   - timeout in seconds (optional, defaults to 600)
    ACS_GROUP_ID        - group_id (required)
    ACS_MESSAGE_ID      - processed_msg_id for the new message (required)
    ACS_SERVER_API_BASE - API base URL (optional, defaults to "http://localhost:7370")
    ACS_LOG_LEVEL       - logging level (optional, defaults to "INFO")
    ACS_POLL_INTERVAL   - polling interval in seconds (optional, defaults to 2)

CLI Arguments:
    -m, --message       - Message text with exactly one @mention (required)
    --json              - Output the full response message as JSON
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys

from api_client import ACSAPIError, ACSClient, setup_logging

logger = logging.getLogger(__name__)


def get_env_var(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Read an environment variable."""
    value = os.environ.get(name, default)
    if required and not value:
        logger.error("Required environment variable %s is not set.", name)
        sys.exit(1)
    return value


def validate_mentions(message_text: str) -> None:
    """
    Validate that message_text contains exactly one @mention.

    Raises:
        SystemExit: If the message does not contain exactly one @mention.
    """
    mentions = re.findall(r"@\S+", message_text)
    if len(mentions) != 1:
        logger.error(
            "Message must contain exactly one @mention, found %d: %s",
            len(mentions),
            mentions,
        )
        sys.exit(1)


def main() -> int:
    """Execute the call_agent workflow."""
    setup_logging()

    # ------------------------------------------------------------------
    # Parse CLI arguments
    # ------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description="Call an agent in an ACS group and wait for its response.",
    )
    parser.add_argument(
        "-m",
        "--message",
        required=True,
        help='Message text with exactly one @mention, e.g., "@agent-1 hello"',
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the full response message as JSON instead of plain text",
    )
    args = parser.parse_args()

    message_text = args.message
    validate_mentions(message_text)

    # ------------------------------------------------------------------
    # Read environment variables
    # ------------------------------------------------------------------
    agent_id = get_env_var("ACS_AGENT_ID", required=True)
    agent_name = get_env_var("ACS_AGENT_NAME", default=agent_id)
    agent_type = get_env_var("ACS_AGENT_TYPE", default="worker-agent")
    timeout_str = get_env_var("ACS_AGENT_TIMEOUT", default="600")
    group_id = get_env_var("ACS_GROUP_ID", required=True)
    message_id = get_env_var("ACS_MESSAGE_ID", required=True)
    api_base = get_env_var("ACS_SERVER_API_BASE", default="http://localhost:7370")
    poll_interval_str = get_env_var("ACS_POLL_INTERVAL", default="2")

    try:
        timeout = int(timeout_str)
    except ValueError:
        logger.error("ACS_AGENT_TIMEOUT must be an integer, got: %s", timeout_str)
        return 1

    try:
        poll_interval = int(poll_interval_str)
    except ValueError:
        logger.error("ACS_POLL_INTERVAL must be an integer, got: %s", poll_interval_str)
        return 1

    # ------------------------------------------------------------------
    # Initialize client
    # ------------------------------------------------------------------
    client = ACSClient(base_url=api_base)

    # ------------------------------------------------------------------
    # Step 1: Send a message mentioning the agent
    # ------------------------------------------------------------------
    try:
        new_message = client.send_message(
            group_id=group_id,
            message_text=message_text,
            sender_id=agent_id,
            sender_type=agent_type,
            processed_msg_id=message_id,
        )
    except ACSAPIError as exc:
        logger.error("Failed to send message: %s", exc)
        return 1

    new_msg_id1 = new_message.get("message_id")
    if not new_msg_id1:
        logger.error("Created message does not contain a message_id.")
        return 1

    logger.info("Sent message %s mentioning %s", new_msg_id1, agent_id)

    # ------------------------------------------------------------------
    # Step 2: Trigger the agent manually
    # ------------------------------------------------------------------
    try:
        trigger_result = client.trigger_message(
            group_id=group_id,
            message_id=new_msg_id1,
            agent_id=agent_id,
        )
    except ACSAPIError as exc:
        logger.error("Failed to trigger agent: %s", exc)
        return 1

    status = trigger_result.get("status")
    if status != "pending":
        logger.warning("Unexpected trigger status: %s", status)
    else:
        logger.info("Triggered agent %s for message %s", agent_id, new_msg_id1)

    # ------------------------------------------------------------------
    # Step 3: Poll for the agent's response
    # ------------------------------------------------------------------
    try:
        response_message = client.wait_for_response(
            group_id=group_id,
            processed_msg_id=new_msg_id1,
            timeout=timeout,
            poll_interval=poll_interval,
        )
    except ACSAPIError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting.")
        return 130

    # ------------------------------------------------------------------
    # Output the response
    # ------------------------------------------------------------------
    if args.json:
        print(json.dumps(response_message, indent=2, ensure_ascii=False))
    else:
        response_text = response_message.get("message_text", "")
        response_msg_id = response_message.get("message_id", "")
        response_sender_id = response_message.get("sender_id", "")
        print(response_text)
        logger.info("Response message_id=%s sender_id=%s", response_msg_id, response_sender_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
