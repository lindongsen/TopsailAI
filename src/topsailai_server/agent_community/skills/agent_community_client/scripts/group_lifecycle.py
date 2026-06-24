#!/usr/bin/env python3
"""
group_lifecycle.py - CLI tool for managing ACS group lifecycle.

Subcommands:
    create-group, list-groups, get-group, update-group, delete-group
    join-member, list-members, update-member, leave-member
    send-message, list-messages, get-message, update-message, delete-message, trigger-message

Environment Variables:
    ACS_SERVER_API_BASE   - API base URL (optional, defaults to "http://localhost:7370")
    ACS_LOG_LEVEL         - logging level (optional, defaults to "INFO")
    ACS_API_KEY           - API key token "ak-{id}.{secret}" (optional)
    ACS_LOGIN_SESSION_KEY - Session key for X-Session-Key auth (optional, priority over API key)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

from api_client import ACSAPIError, ACSClient, setup_logging

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="group_lifecycle.py",
        description="CLI for AI-Agent Community Server (ACS) group lifecycle management",
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("ACS_SERVER_API_BASE", "http://localhost:7370"),
        help="ACS API base URL (default: http://localhost:7370 or ACS_SERVER_API_BASE env var)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("ACS_API_KEY"),
        help="API key token (default: ACS_API_KEY env var)",
    )
    parser.add_argument(
        "--session-key",
        default=os.environ.get("ACS_LOGIN_SESSION_KEY"),
        help="Session key for X-Session-Key auth (default: ACS_LOGIN_SESSION_KEY env var; priority over --api-key)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ------------------------------------------------------------------
    # Group commands
    # ------------------------------------------------------------------
    create_group = subparsers.add_parser("create-group", help="Create a new group")
    create_group.add_argument("--name", required=True, help="Group name")
    create_group.add_argument("--context", default="", help="Group context/description")
    create_group.add_argument("--key", default="", help="Group secret key (empty for public)")

    list_groups = subparsers.add_parser("list-groups", help="List all groups")
    _add_list_filters(list_groups)

    get_group = subparsers.add_parser("get-group", help="Get a group by ID")
    get_group.add_argument("group_id", help="Group ID")

    update_group = subparsers.add_parser("update-group", help="Update a group")
    update_group.add_argument("group_id", help="Group ID")
    update_group.add_argument("--name", help="New group name")
    update_group.add_argument("--context", help="New group context")
    update_group.add_argument("--key", help="New group key")

    delete_group = subparsers.add_parser("delete-group", help="Delete a group")
    delete_group.add_argument("group_id", help="Group ID")

    # ------------------------------------------------------------------
    # Member commands
    # ------------------------------------------------------------------
    join_member = subparsers.add_parser("join-member", help="Add a member to a group or self-join")
    join_member.add_argument("group_id", help="Group ID")
    join_member.add_argument("--id", dest="member_id", help="Member ID (omit for self-join)")
    join_member.add_argument("--name", dest="member_name", help="Member name")
    join_member.add_argument(
        "--type",
        dest="member_type",
        choices=["user", "worker-agent", "manager-agent"],
        help="Member type (omit for self-join)",
    )
    join_member.add_argument("--description", default="", help="Member description")
    join_member.add_argument("--interface", help="Member interface as JSON string")
    join_member.add_argument("--self-join", action="store_true", help="Self-join the group")
    join_member.add_argument("--group-key", help="Secret key for self-joining a private group")

    list_members = subparsers.add_parser("list-members", help="List members of a group")
    list_members.add_argument("group_id", help="Group ID")
    _add_list_filters(list_members)

    update_member = subparsers.add_parser("update-member", help="Update a group member")
    update_member.add_argument("group_id", help="Group ID")
    update_member.add_argument("member_id", help="Member ID")
    update_member.add_argument("--name", help="New member name")
    update_member.add_argument("--description", help="New member description")
    update_member.add_argument("--status", choices=["online", "offline", "idle", "processing"], help="New member status")
    update_member.add_argument("--interface", help="New member interface as JSON string")

    leave_member = subparsers.add_parser("leave-member", help="Remove a member from a group")
    leave_member.add_argument("group_id", help="Group ID")
    leave_member.add_argument("member_id", help="Member ID")

    # ------------------------------------------------------------------
    # Message commands
    # ------------------------------------------------------------------
    send_message = subparsers.add_parser("send-message", help="Send a message to a group")
    send_message.add_argument("group_id", help="Group ID")
    send_message.add_argument("--text", required=True, help="Message text")
    send_message.add_argument(
        "--sender-id",
        help="Sender member ID (derived from authentication when omitted)",
    )
    send_message.add_argument(
        "--sender-type",
        choices=["user", "worker-agent", "manager-agent"],
        help="Sender type (derived from authentication when omitted)",
    )
    send_message.add_argument("--attachments", help="Message attachments as JSON string")
    send_message.add_argument("--processed-msg-id", help="Processed message ID")

    list_messages = subparsers.add_parser("list-messages", help="List messages in a group")
    list_messages.add_argument("group_id", help="Group ID")
    list_messages.add_argument("--processed-msg-id", help="Filter by processed message ID")
    _add_list_filters(list_messages)

    get_message = subparsers.add_parser("get-message", help="Get a single message")
    get_message.add_argument("group_id", help="Group ID")
    get_message.add_argument("message_id", help="Message ID")

    update_message = subparsers.add_parser("update-message", help="Update a message")
    update_message.add_argument("group_id", help="Group ID")
    update_message.add_argument("message_id", help="Message ID")
    update_message.add_argument("--text", required=True, help="New message text")

    delete_message = subparsers.add_parser("delete-message", help="Soft-delete a message")
    delete_message.add_argument("group_id", help="Group ID")
    delete_message.add_argument("message_id", help="Message ID")

    trigger_message = subparsers.add_parser("trigger-message", help="Manually trigger agent for a message")
    trigger_message.add_argument("group_id", help="Group ID")
    trigger_message.add_argument("message_id", help="Message ID")
    trigger_message.add_argument("--agent-id", help="Specific agent ID to trigger")

    return parser


def _add_list_filters(subparser: argparse.ArgumentParser) -> None:
    """Add common list filter arguments to a subparser."""
    subparser.add_argument("--offset", type=int, default=0, help="Records to skip")
    subparser.add_argument("--limit", type=int, default=1000, help="Max records to return")
    subparser.add_argument("--sort-key", default="create_at_ms", help="Field to sort by")
    subparser.add_argument("--order-by", default="desc", choices=["asc", "desc"], help="Sort direction")
    subparser.add_argument("--create-at-ms", help='Time range filter "start-end" (epoch ms)')
    subparser.add_argument("--update-at-ms", help='Time range filter "start-end" (epoch ms)')


def print_json(data: Any) -> None:
    """Pretty-print data as JSON."""
    print(json.dumps(data, indent=2, ensure_ascii=False))


def handle_error(exc: ACSAPIError) -> int:
    """Print an API error and return exit code."""
    logger.error("%s", exc)
    if exc.trace_id:
        logger.error("Trace ID: %s", exc.trace_id)
    return 1


def _build_client(args: argparse.Namespace) -> ACSClient:
    """Build an ACSClient from parsed CLI arguments."""
    return ACSClient(
        base_url=args.api_base,
        api_key=args.api_key,
        session_key=args.session_key,
    )


def cmd_create_group(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle create-group command."""
    try:
        result = client.create_group(
            group_name=args.name,
            group_context=args.context,
            group_key=args.key,
        )
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_list_groups(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle list-groups command."""
    try:
        result = client.list_groups(
            offset=args.offset,
            limit=args.limit,
            sort_key=args.sort_key,
            order_by=args.order_by,
            create_at_ms=args.create_at_ms,
            update_at_ms=args.update_at_ms,
        )
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_update_group(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle update-group command."""
    kwargs: dict[str, Any] = {}
    if args.name is not None:
        kwargs["group_name"] = args.name
    if args.context is not None:
        kwargs["group_context"] = args.context
    if args.key is not None:
        kwargs["group_key"] = args.key
    if not kwargs:
        logger.error("No fields to update. Provide --name, --context, or --key.")
        return 1
    try:
        result = client.update_group(args.group_id, **kwargs)
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_delete_group(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle delete-group command."""
    try:
        client.delete_group(args.group_id)
        print(json.dumps({"message": "group deleted"}, indent=2, ensure_ascii=False))
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_join_member(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle join-member command."""
    member_interface = None
    if args.interface:
        try:
            member_interface = json.loads(args.interface)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in --interface: %s", exc)
            return 1

    if args.self_join:
        kwargs: dict[str, Any] = {"group_id": args.group_id}
        if args.member_name:
            kwargs["member_name"] = args.member_name
        if args.description:
            kwargs["member_description"] = args.description
        if args.group_key is not None:
            kwargs["group_key"] = args.group_key
        try:
            result = client.join_member(**kwargs)
            print_json(result)
            return 0
        except ACSAPIError as exc:
            return handle_error(exc)

    if not args.member_id or not args.member_type:
        logger.error("--id and --type are required unless --self-join is used.")
        return 1

    try:
        result = client.join_member(
            group_id=args.group_id,
            member_id=args.member_id,
            member_name=args.member_name,
            member_type=args.member_type,
            member_description=args.description,
            member_interface=member_interface,
        )
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_list_members(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle list-members command."""
    try:
        result = client.list_members(
            group_id=args.group_id,
            offset=args.offset,
            limit=args.limit,
            sort_key=args.sort_key,
            order_by=args.order_by,
        )
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_get_group(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle get-group command."""
    try:
        result = client.get_group(args.group_id)
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_update_member(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle update-member command."""
    kwargs: dict[str, Any] = {}
    if args.name is not None:
        kwargs["member_name"] = args.name
    if args.description is not None:
        kwargs["member_description"] = args.description
    if args.status is not None:
        kwargs["member_status"] = args.status
    if args.interface is not None:
        try:
            kwargs["member_interface"] = json.loads(args.interface)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in --interface: %s", exc)
            return 1
    if not kwargs:
        logger.error("No fields to update. Provide --name, --description, --status, or --interface.")
        return 1
    try:
        result = client.update_member(args.group_id, args.member_id, **kwargs)
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_leave_member(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle leave-member command."""
    try:
        result = client.leave_member(args.group_id, args.member_id)
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_send_message(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle send-message command."""
    message_attachments = None
    if args.attachments:
        try:
            message_attachments = json.loads(args.attachments)
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in --attachments: %s", exc)
            return 1

    kwargs: dict[str, Any] = {
        "group_id": args.group_id,
        "message_text": args.text,
        "message_attachments": message_attachments,
        "processed_msg_id": args.processed_msg_id,
    }
    if args.sender_id is not None:
        kwargs["sender_id"] = args.sender_id
    if args.sender_type is not None:
        kwargs["sender_type"] = args.sender_type

    try:
        result = client.send_message(**kwargs)
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_list_messages(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle list-messages command."""
    try:
        result = client.list_messages(
            group_id=args.group_id,
            offset=args.offset,
            limit=args.limit,
            sort_key=args.sort_key,
            order_by=args.order_by,
            processed_msg_id=args.processed_msg_id,
            create_at_ms=args.create_at_ms,
            update_at_ms=args.update_at_ms,
        )
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_get_message(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle get-message command."""
    try:
        result = client.get_message(args.group_id, args.message_id)
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_update_message(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle update-message command."""
    try:
        result = client.update_message(
            args.group_id,
            args.message_id,
            message_text=args.text,
        )
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_delete_message(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle delete-message command."""
    try:
        result = client.delete_message(args.group_id, args.message_id)
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def cmd_trigger_message(client: ACSClient, args: argparse.Namespace) -> int:
    """Handle trigger-message command."""
    try:
        result = client.trigger_message(
            group_id=args.group_id,
            message_id=args.message_id,
            agent_id=args.agent_id,
        )
        print_json(result)
        return 0
    except ACSAPIError as exc:
        return handle_error(exc)


def main() -> int:
    """Main entry point."""
    setup_logging()
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    client = _build_client(args)

    handlers: dict[str, Any] = {
        "create-group": cmd_create_group,
        "list-groups": cmd_list_groups,
        "get-group": cmd_get_group,
        "update-group": cmd_update_group,
        "delete-group": cmd_delete_group,
        "join-member": cmd_join_member,
        "list-members": cmd_list_members,
        "update-member": cmd_update_member,
        "leave-member": cmd_leave_member,
        "send-message": cmd_send_message,
        "list-messages": cmd_list_messages,
        "get-message": cmd_get_message,
        "update-message": cmd_update_message,
        "delete-message": cmd_delete_message,
        "trigger-message": cmd_trigger_message,
    }

    handler = handlers.get(args.command)
    if handler is None:
        logger.error("Unknown command: %s", args.command)
        return 1

    return handler(client, args)


if __name__ == "__main__":
    sys.exit(main())
