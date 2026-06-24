#!/usr/bin/env python3
"""
call_agent.py - Execute the call_agent workflow for ACS.

Workflow:
1. Send a message to a group mentioning an agent
2. Trigger the agent manually via the trigger API
3. Poll for the agent's response message

Environment Variables:
    ACS_AGENT_ID            - member_id (required)
    ACS_AGENT_NAME          - member_name (optional, informational)
    ACS_AGENT_TYPE          - member_type (optional, defaults to "worker-agent")
    ACS_AGENT_TIMEOUT       - timeout in seconds (optional, defaults to 600)
    ACS_AGENT_SUB_TASK      - message_text when -m/--message is not provided (optional)
    ACS_GROUP_ID            - group_id (required)
    ACS_MESSAGE_ID          - processed_msg_id for the new message (required)
    ACS_SERVER_API_BASE     - API base URL (optional, defaults to "http://localhost:7370")
    ACS_LOGIN_SESSION_KEY   - Session key for X-Session-Key auth (optional)
    ACS_API_KEY             - API key token for Bearer auth (optional)
    ACS_LOG_LEVEL           - logging level (optional, defaults to "INFO")
    ACS_POLL_INTERVAL       - polling interval in seconds (optional, defaults to 2)

CLI Arguments:
    -m, --message           - Message text with exactly one @mention (optional if
                              ACS_AGENT_SUB_TASK is set)
    --session-key           - Override X-Session-Key header
    --api-key               - Override Authorization: Bearer token
    --json                  - Output the full response message as JSON

Authentication:
    ACS protected endpoints require authentication. Provide either --session-key
    (or ACS_LOGIN_SESSION_KEY) or --api-key (or ACS_API_KEY). If both are
    provided, the session key takes priority.
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

# Matches ACS member_id / member_name format: alphanumeric, hyphens, underscores.
MENTION_RE = re.compile(r"@([A-Za-z0-9_-]+)")


def get_env_var(name: str, default: str | None = None, required: bool = False) -> str | None:
    """Read an environment variable."""
    value = os.environ.get(name, default)
    if required and not value:
        logger.error("Required environment variable %s is not set.", name)
        sys.exit(1)
    return value


def extract_mention(message_text: str) -> str | None:
    """
    Extract the first @mention from message_text.

    Returns:
        The mentioned identifier (without the leading @), or None if no mention.
    """
    mentions = MENTION_RE.findall(message_text)
    if not mentions:
        return None
    return mentions[0]


def validate_mentions(message_text: str) -> str:
    """
    Validate that message_text contains exactly one @mention.

    Returns:
        The mentioned identifier (without the leading @).

    Raises:
        SystemExit: If the message does not contain exactly one @mention.
    """
    mentions = MENTION_RE.findall(message_text)
    if len(mentions) != 1:
        logger.error(
            "Message must contain exactly one @mention, found %d: %s",
            len(mentions),
            mentions,
        )
        sys.exit(1)
    return mentions[0]


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
        default=None,
        help='Message text with exactly one @mention, e.g., "@agent-1 hello". '
             'If omitted, the value is read from the ACS_AGENT_SUB_TASK environment variable.',
    )
    parser.add_argument(
        "--session-key",
        default=os.environ.get("ACS_LOGIN_SESSION_KEY"),
        help="Session key for X-Session-Key auth (default: ACS_LOGIN_SESSION_KEY env var)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ACS_API_KEY"),
        help="API key token for Authorization: Bearer auth (default: ACS_API_KEY env var)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the full response message as JSON instead of plain text",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Resolve message_text: CLI argument takes priority, then env var
    # ------------------------------------------------------------------
    message_text = args.message
    if message_text is None:
        message_text = os.environ.get("ACS_AGENT_SUB_TASK")
    if not message_text:
        logger.error(
            "Message text is required. Provide -m/--message or set the ACS_AGENT_SUB_TASK "
            "environment variable."
        )
        return 1

    mentioned_agent = validate_mentions(message_text)

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

    if not args.session_key and not args.api_key:
        logger.error(
            "Authentication required. Provide --session-key (or ACS_LOGIN_SESSION_KEY) "
            "or --api-key (or ACS_API_KEY)."
        )
        return 1

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
    client = ACSClient(
        base_url=api_base,
        api_key=args.api_key,
        session_key=args.session_key,
    )

    # ------------------------------------------------------------------
    # Validate that the mentioned agent exists in the group and is an agent
    # ------------------------------------------------------------------
    try:
        members_result = client.list_members(group_id=group_id, limit=1000)
        members = members_result.get("items", [])
        mentioned_member = None
        for member in members:
            if member.get("member_id") == mentioned_agent:
                mentioned_member = member
                break

        if mentioned_member is None:
            logger.error(
                "Mentioned agent '%s' is not a member of group '%s' (caller: '%s' (%s)).",
                mentioned_agent,
                group_id,
                agent_name,
                agent_id,
            )
            return 1

        member_type = mentioned_member.get("member_type", "")
        if not member_type.endswith("-agent"):
            logger.error(
                "Mentioned member '%s' (%s) is not an agent (member_type=%s).",
                mentioned_agent,
                mentioned_member.get("member_name", "<unknown>"),
                member_type,
            )
            return 1
    except ACSAPIError as exc:
        logger.error("Failed to list group members: %s", exc)
        return 1

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

    logger.info(
        "Sent message %s as '%s' (%s) mentioning %s",
        new_msg_id1,
        agent_name,
        agent_id,
        mentioned_agent,
    )

    # ------------------------------------------------------------------
    # Step 2: Trigger the agent manually
    # ------------------------------------------------------------------
    try:
        trigger_result = client.trigger_message(
            group_id=group_id,
            message_id=new_msg_id1,
            agent_id=mentioned_agent,
        )
    except ACSAPIError as exc:
        logger.error("Failed to trigger agent: %s", exc)
        return 1

    status = trigger_result.get("status")
    if status != "pending":
        logger.error(
            "Trigger did not enter pending state (status=%s). Aborting.",
            status,
        )
        return 1

    logger.info("Triggered agent %s for message %s", mentioned_agent, new_msg_id1)

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
