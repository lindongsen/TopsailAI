#!/usr/bin/env python3
"""
Generic CLI test harness for TopsailAI tool approval rules.

This script loads a tool approval rule set and evaluates how the matcher
resolves one or more sample tool calls.  It is intentionally tool-agnostic:
the default regression cases can be extended without touching the evaluation
logic, and arbitrary tool calls can be supplied on the command line.

Usage:
    # Run the built-in regression suite using TOPSAILAI_TOOL_APPROVAL_RULES.
    python topsailai_test_tool_approval_rules.py

    # Evaluate a single command using the default tool (cmd_tool-exec_cmd).
    python topsailai_test_tool_approval_rules.py "rm -f /tmp/.tmp/x.file"

    # Evaluate calls for a specific tool.
    python topsailai_test_tool_approval_rules.py "cmd_tool-exec_cmd:rm -f /tmp/.tmp/x.file"
    python topsailai_test_tool_approval_rules.py --tool file_tool-write_file "/etc/passwd" "/etc/hosts"

    # Use a specific rule file or multiple files separated by ';'.
    python topsailai_test_tool_approval_rules.py --rules /path/to/tool_approval.json
    python topsailai_test_tool_approval_rules.py --rules "/path/to/a.json;/path/to/b.json"

    # Machine-readable JSON output.
    python topsailai_test_tool_approval_rules.py --json "rm -rf /" "echo hello"

    # Drive the real approval flow: every call that resolves to ASK pops up the
    # interactive approve/deny prompt exactly like a running agent does.
    python topsailai_test_tool_approval_rules.py --interactive "sudo ls"
    python topsailai_test_tool_approval_rules.py --interactive --rules /path/to/tool_approval.json
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Any

import _import_topsailai  # noqa: F401

from topsailai.ai_base.tool_approval import instance as approval_instance
from topsailai.ai_base.tool_approval.instance import ToolApprovalInstance
from topsailai.ai_base.tool_approval.matcher import (
    clear_approval_rules_cache,
    load_approval_rules,
)
from topsailai.ai_base.tool_approval.registry import (
    register_pending_approval,
    unregister_pending_approval,
)
from topsailai.ai_base.tool_approval.transport import LocalApprovalTransport


# Tool name used for positional arguments that do not specify one explicitly.
DEFAULT_TOOL_NAME = "cmd_tool-exec_cmd"

# Timeout policies accepted by ToolApprovalInstance.apply_timeout_policy().
TIMEOUT_POLICIES = ("deny", "allow", "ask_again")


@dataclass(frozen=True)
class TestCase:
    """A single regression case.

    Attributes:
        tool_name: Name of the tool to evaluate (e.g. cmd_tool-exec_cmd).
        raw_value: The primary argument for the tool.  Interpretation depends
            on the tool (e.g. the shell command for cmd_tool-exec_cmd, or the
            file path for file_tool-write_file).
        extra_args: Additional fixed arguments required to construct a valid
            tool call (e.g. content for file_tool-write_file).
        description: Optional human-readable note shown in text output.
    """

    tool_name: str
    raw_value: str
    extra_args: dict[str, Any] | None = None
    description: str | None = None


# Built-in regression suite.  Add new cases here without changing the engine.
DEFAULT_TEST_CASES: list[TestCase] = [
    # Directory-component bypass rules: /tmp
    TestCase("cmd_tool-exec_cmd", "rm -f /tmp/123.txt"),
    TestCase("cmd_tool-exec_cmd", "rm -f /tmp/abc/def.txt"),
    # Mixed /tmp and non-/tmp paths must NOT match the bypass rule.
    TestCase("cmd_tool-exec_cmd", "rm -f /tmp/123.txt /hello/456.txt"),
    TestCase("cmd_tool-exec_cmd", "rm -f /tmp/123.txt /tmp/456.txt"),
    # The /tmp directory itself is allowed (rm -f cannot remove directories anyway).
    TestCase("cmd_tool-exec_cmd", "rm -f /tmp"),
    # /tmpfile.txt is not under /tmp and must NOT match.
    TestCase("cmd_tool-exec_cmd", "rm -f /tmpfile.txt"),

    # Directory-component bypass rules: .tmp
    TestCase("cmd_tool-exec_cmd", "rm -f /tmp/.tmp/x.file"),
    TestCase("cmd_tool-exec_cmd", "rm -f .tmp/x.file"),
    # Mixed .tmp and non-.tmp paths must NOT match the bypass rule.
    TestCase("cmd_tool-exec_cmd", "rm -f .tmp/123.txt /hello/456.txt"),
    TestCase("cmd_tool-exec_cmd", "rm -f /tmp/.tmp/123.txt /tmp/.tmp/456.txt"),
    TestCase("cmd_tool-exec_cmd", "rm -f /home/user/.tmp/123 /home/user/.tmp/456"),
    # .tmp file-extension cases must NOT match the bypass rule.
    TestCase("cmd_tool-exec_cmd", "rm -f /home/user/1.tmp/x.file"),
    TestCase("cmd_tool-exec_cmd", "rm -f /home/user/x.tmp"),

    # Directory-component bypass rules: .task
    TestCase("cmd_tool-exec_cmd", "rm -f /path/to/.task/xxx"),
    TestCase("cmd_tool-exec_cmd", "rm -f .task/xxx"),
    # Mixed .task and non-.task paths must NOT match the bypass rule.
    TestCase("cmd_tool-exec_cmd", "rm -f .task/123.txt /hello/456.txt"),
    TestCase("cmd_tool-exec_cmd", "rm -f /path/to/.task/123 /path/to/.task/456"),
    # .task file-extension cases must NOT match the bypass rule.
    TestCase("cmd_tool-exec_cmd", "rm -f /path/to/x.task"),
    TestCase("cmd_tool-exec_cmd", "rm -f /path/to/x.task/xxx"),

    # Destructive / dangerous commands should still require approval.
    TestCase("cmd_tool-exec_cmd", "rm -rf /tmp/.tmp/x.file"),
    TestCase("cmd_tool-exec_cmd", "rm -rf /"),
    TestCase("cmd_tool-exec_cmd", "git reset --hard HEAD~1"),
    TestCase("cmd_tool-exec_cmd", "sudo ls"),

    # Benign commands should not match any rule.
    TestCase("cmd_tool-exec_cmd", "echo hello"),

    # Non-command tools should also be evaluable.
    TestCase("file_tool-write_file", "/etc/passwd", extra_args={"content": "test"}),
]


def _configure_environment(rules_value: str | None) -> None:
    """Enable approval and point the matcher at the requested rule source."""
    os.environ["TOPSAILAI_TOOL_APPROVAL_ENABLED"] = "1"
    if rules_value:
        os.environ["TOPSAILAI_TOOL_APPROVAL_RULES"] = rules_value


def _build_tool_args(tool_name: str, raw_value: str, extra_args: dict[str, Any] | None) -> dict[str, Any]:
    """Construct the argument dictionary for a tool call.

    The mapping below knows how to translate the simple ``raw_value`` used by
    the CLI/test cases into the structured arguments expected by each tool's
    approval rule matcher.  For unknown tools, ``raw_value`` is passed as
    ``value`` so the matcher can still inspect it.
    """
    args: dict[str, Any] = {}
    if extra_args:
        args.update(extra_args)

    if tool_name == "cmd_tool-exec_cmd":
        args["cmd"] = raw_value
    elif tool_name == "file_tool-write_file":
        args.setdefault("file_path", raw_value)
    elif tool_name == "file_tool-read_file":
        args.setdefault("file_path", raw_value)
    else:
        args.setdefault("value", raw_value)

    return args


def _evaluate(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one tool call and return a normalized result dictionary."""
    instance = approval_instance.ToolApprovalInstance(
        tool_name=tool_name,
        tool_args=tool_args,
    )
    decision = instance.decide()
    matched_rule = getattr(decision, "rule", None)
    return {
        "tool_name": tool_name,
        "tool_args": tool_args,
        "decision": decision.action,
        "rule_name": getattr(matched_rule, "name", None) if matched_rule else None,
        "timeout": getattr(decision, "timeout", None),
        "policy": getattr(decision, "policy", None),
    }


def _parse_arg(arg: str, default_tool_name: str) -> tuple[str, str]:
    """Split a CLI argument into (tool_name, raw_value).

    Supports an optional ``tool_name:value`` prefix.  When omitted, the default
    tool name is used.
    """
    if ":" in arg:
        tool_name, value = arg.split(":", 1)
        return tool_name, value
    return default_tool_name, arg


def _format_header(result: dict[str, Any], index: int) -> str:
    """Render the static part of one case, shown before any approval prompt."""
    lines = [f"--- Case {index} ---"]
    lines.append(f"Tool    : {result['tool_name']}")

    tool_args = result["tool_args"]
    if result["tool_name"] == "cmd_tool-exec_cmd" and "cmd" in tool_args:
        lines.append(f"Command : {tool_args['cmd']}")
    else:
        lines.append(f"Args    : {tool_args}")

    rule_name = result["rule_name"] or "no match"
    lines.append(f"Rule    : {rule_name}")
    lines.append(f"Decision: {result['decision'].upper()}")

    if result["timeout"] is not None:
        lines.append(f"Timeout : {result['timeout']}")
    if result["policy"] is not None:
        lines.append(f"Policy  : {result['policy']}")

    if result["decision"] == approval_instance.ApprovalDecision.NO_APPROVAL:
        lines.append("Note    : allowed without approval")

    return "\n".join(lines)


def _format_text(result: dict[str, Any], index: int) -> str:
    """Render a single result in human-readable form."""
    return f"{_format_header(result, index)}\n"


def _format_interactive_outcome(result: dict[str, Any]) -> str:
    """Render the human decision produced by the interactive approval flow."""
    status = result.get("approval_status")
    if status is None:
        return ""

    lines = [f"Outcome : {status.upper()}"]
    if result.get("decision_by"):
        lines.append(f"By      : {result['decision_by']}")
    if status == ToolApprovalInstance.STATUS_APPROVED:
        lines.append("Note    : tool call would be executed")
    elif status in (ToolApprovalInstance.STATUS_DENIED, ToolApprovalInstance.STATUS_TIMEOUT):
        lines.append("Note    : tool call would be blocked")
    lines.append("")
    return "\n".join(lines)


def _evaluate_interactive(
    tool_name: str,
    tool_args: dict[str, Any],
    transport: LocalApprovalTransport,
    *,
    timeout: float | None = None,
    policy: str | None = None,
) -> dict[str, Any]:
    """Evaluate one tool call through the real approval flow.

    When the matcher resolves the call to ``ask``, the request is pushed through
    the shared approval transport, which renders the same interactive
    approve/deny prompt that a running agent shows and blocks until a human
    answers (or the timeout policy kicks in).  The resulting status is reported
    next to the static decision.

    Args:
        tool_name: Name of the tool being simulated.
        tool_args: Arguments of the simulated tool call.
        transport: Transport used to deliver the approval request.
        timeout: Optional seconds override for the interactive wait.
        policy: Optional timeout policy override (``deny``, ``allow``, ``ask_again``).

    Returns:
        The normalized result dictionary, extended with ``approval_status`` and
        ``decision_by`` when an interactive decision was requested.
    """
    instance = ToolApprovalInstance(
        tool_name=tool_name,
        tool_args=tool_args,
        transport=transport,
    )
    decision = instance.decide()
    matched_rule = getattr(decision, "rule", None)
    effective_timeout = timeout if timeout is not None else getattr(decision, "timeout", None)
    effective_policy = policy or getattr(decision, "policy", None)
    result = {
        "tool_name": tool_name,
        "tool_args": tool_args,
        "decision": decision.action,
        "rule_name": getattr(matched_rule, "name", None) if matched_rule else None,
        "timeout": effective_timeout,
        "policy": effective_policy,
        "approval_status": None,
        "decision_by": None,
    }

    if decision.action != approval_instance.ApprovalDecision.ASK:
        return result

    # Mirror the production decorator: register the instance so an external
    # decision maker can resolve it by ID, then block on the human decision.
    instance.rule_name = result["rule_name"] or "<unnamed>"
    register_pending_approval(instance)
    try:
        transport.send_request(instance)
        status = instance.wait_for_decision(
            timeout=effective_timeout,
            policy=effective_policy,
        )
    finally:
        unregister_pending_approval(instance.id)

    result["approval_status"] = status
    result["decision_by"] = instance.decision_by
    return result


def _collect_cases(args: argparse.Namespace) -> list[tuple[str, str, dict[str, Any] | None, str | None]]:
    """Return the list of cases to evaluate for this invocation."""
    if args.calls:
        return [
            (tool_name, raw_value, None, None)
            for tool_name, raw_value in (_parse_arg(call, args.tool) for call in args.calls)
        ]
    return [
        (case.tool_name, case.raw_value, case.extra_args, case.description)
        for case in DEFAULT_TEST_CASES
    ]


def _runtime_input_available() -> bool:
    """Return True when an agent-runtime input function is registered."""
    from topsailai.utils.thread_local_tool import get_agent_runtime_input_with_timeout

    return get_agent_runtime_input_with_timeout() is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate tool approval rules for sample tool calls."
    )
    parser.add_argument(
        "calls",
        nargs="*",
        help="Tool calls to evaluate. Optional tool_name: prefix.",
    )
    parser.add_argument(
        "--rules",
        default=None,
        help=(
            "Path to the approval rules JSON file, multiple paths separated by ';', "
            "or an inline JSON array. If omitted, reads from "
            "TOPSAILAI_TOOL_APPROVAL_RULES."
        ),
    )
    parser.add_argument(
        "--tool",
        default=DEFAULT_TOOL_NAME,
        help=f"Default tool name for positional arguments (default: {DEFAULT_TOOL_NAME}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of human-readable text.",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help=(
            "Drive the real approval flow: every call that resolves to 'ask' pops up "
            "the interactive approve/deny prompt exactly like a running agent does."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Override the approval wait timeout for interactive mode.",
    )
    parser.add_argument(
        "--policy",
        choices=sorted(TIMEOUT_POLICIES),
        default=None,
        help="Override the timeout policy for interactive mode.",
    )
    args = parser.parse_args(argv)

    # Make sure the matcher reads from the requested source on this run.
    _configure_environment(args.rules)
    clear_approval_rules_cache()

    # Load rules through the shared loader so single file, multiple files,
    # inline JSON, and default-path fallback all work consistently.
    rules = load_approval_rules()

    source = args.rules or os.environ.get("TOPSAILAI_TOOL_APPROVAL_RULES") or "<default>"
    if args.json:
        # Keep stdout clean for machine-readable JSON; emit summary to stderr.
        print(f"Loaded {len(rules)} approval rule(s) from {source}", file=sys.stderr)
    else:
        print(f"Loaded {len(rules)} approval rule(s) from {source}")
        for rule in rules:
            print(f"  - {rule.name or rule.match}: mode={rule.mode}, priority={rule.priority}")

    transport: LocalApprovalTransport | None = None
    if args.interactive:
        # Use a fresh singleton so leftover queued requests from a previous run
        # in the same process cannot leak into this session.
        LocalApprovalTransport.reset_instance()
        transport = LocalApprovalTransport.get_instance()
        if not sys.stdin.isatty() and not _runtime_input_available():
            print(
                "[WARN] stdin is not a TTY and no agent runtime input function is registered; "
                "the approval prompt cannot be answered, the timeout policy will decide.",
                file=sys.stderr,
            )

    # In interactive JSON mode the prompts must not pollute stdout, so all
    # human-readable text is routed to stderr and only the final JSON is printed.
    human_stream = sys.stderr if (args.json and transport is not None) else sys.stdout

    results: list[dict[str, Any]] = []
    with ExitStack() as stack:
        if args.json and transport is not None:
            # The transport renders the approval prompt and echoes the typed
            # answer through ``sys.stdout``; redirect it so stdout keeps
            # carrying nothing but the final JSON document.
            stack.enter_context(contextlib.redirect_stdout(sys.stderr))
        for idx, (tool_name, raw_value, extra_args, description) in enumerate(_collect_cases(args), start=1):
            tool_args = _build_tool_args(tool_name, raw_value, extra_args)
            result = _evaluate(tool_name, tool_args)
            if transport is not None:
                # Print the static case block first so the operator knows which tool
                # call the approval prompt refers to, then run the real approval flow.
                header_result = dict(result)
                if args.timeout is not None:
                    header_result["timeout"] = args.timeout
                if args.policy is not None:
                    header_result["policy"] = args.policy
                print(_format_header(header_result, idx), file=human_stream)
                human_stream.flush()
                result = _evaluate_interactive(
                    tool_name,
                    tool_args,
                    transport,
                    timeout=args.timeout,
                    policy=args.policy,
                )
            if description:
                result["description"] = description
            results.append(result)
            if transport is not None:
                print(_format_interactive_outcome(result), file=human_stream, end="")
                human_stream.flush()

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif transport is None:
        for idx, result in enumerate(results, start=1):
            print(_format_text(result, idx), end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
