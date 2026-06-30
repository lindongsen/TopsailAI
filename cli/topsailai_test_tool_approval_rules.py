#!/usr/bin/env python3
"""
Generic CLI test harness for TopsailAI tool approval rules.

This script loads a tool approval rule set and evaluates how the matcher
resolves one or more sample tool calls.  It is intentionally tool-agnostic:
the default regression cases can be extended without touching the evaluation
logic, and arbitrary tool calls can be supplied on the command line.

Usage:
    # Run the built-in regression suite.
    python /TopsailAI/cli/topsailai_test_tool_approval_rules.py

    # Evaluate a single command using the default tool (cmd_tool-exec_cmd).
    python /TopsailAI/cli/topsailai_test_tool_approval_rules.py "rm -f /tmp/.tmp/x.file"

    # Evaluate calls for a specific tool.
    python /TopsailAI/cli/topsailai_test_tool_approval_rules.py "cmd_tool-exec_cmd:rm -f /tmp/.tmp/x.file"
    python /TopsailAI/cli/topsailai_test_tool_approval_rules.py --tool file_tool-write_file "/etc/passwd" "/etc/hosts"

    # Machine-readable JSON output.
    python /TopsailAI/cli/topsailai_test_tool_approval_rules.py --json "rm -rf /" "echo hello"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

# Make the project source tree importable when the script is executed directly.
# The topsailai package lives under <repo-root>/src, while this script is in
# <repo-root>/cli, so we add <repo-root>/src to sys.path.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "src"))
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from topsailai.ai_base.tool_approval import instance as approval_instance
from topsailai.ai_base.tool_approval import matcher as approval_matcher


def _resolve_default_rules_path() -> str:
    """Resolve the default approval rules file path.

    Resolution order (earlier wins):
      1. TOPSAILAI_TOOL_APPROVAL_RULES environment variable if set and non-empty.
      2. ${TOPSAILAI_HOME}/tool_approval.json if TOPSAILAI_HOME is set and non-empty.
      3. ${TOPSAILAI_WORK_FOLDER}/tool_approval.json if TOPSAILAI_WORK_FOLDER is set and non-empty.
      4. ~/.topsailai/tool_approval.json as the final fallback.

    The returned path is resolved at import time so that --rules can still
    override it explicitly on the command line.
    """
    env_rules = os.environ.get("TOPSAILAI_TOOL_APPROVAL_RULES")
    if env_rules:
        return env_rules

    topsailai_home = os.environ.get("TOPSAILAI_HOME")
    if topsailai_home:
        return os.path.join(topsailai_home, "tool_approval.json")

    work_folder = os.environ.get("TOPSAILAI_WORK_FOLDER")
    if work_folder:
        return os.path.join(work_folder, "tool_approval.json")

    return os.path.expanduser("~/.topsailai/tool_approval.json")
DEFAULT_RULES_PATH = _resolve_default_rules_path()

# Tool name used for positional arguments that do not specify one explicitly.
DEFAULT_TOOL_NAME = "cmd_tool-exec_cmd"


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


def _configure_environment(rules_path: str) -> None:
    """Enable approval and point the matcher at the requested rule file."""
    os.environ["TOPSAILAI_TOOL_APPROVAL_ENABLED"] = "1"
    os.environ["TOPSAILAI_TOOL_APPROVAL_RULES"] = rules_path


def _load_rules(rules_path: str) -> list[dict[str, Any]]:
    """Load and return the raw rule list from a JSON file."""
    with open(rules_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


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


def _format_text(result: dict[str, Any], index: int) -> str:
    """Render a single result in human-readable form."""
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

    lines.append("")
    return "\n".join(lines)


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
        default=DEFAULT_RULES_PATH,
        help=f"Path to the approval rules JSON file (default: {DEFAULT_RULES_PATH}).",
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
    args = parser.parse_args(argv)

    # Make sure the matcher reads from the requested file on this run.
    _configure_environment(args.rules)
    approval_matcher._rules_cache = None  # type: ignore[attr-defined]

    # Load rules early so JSON syntax errors surface before evaluation.
    _load_rules(args.rules)

    results: list[dict[str, Any]] = []
    for tool_name, raw_value, extra_args, description in _collect_cases(args):
        tool_args = _build_tool_args(tool_name, raw_value, extra_args)
        result = _evaluate(tool_name, tool_args)
        if description:
            result["description"] = description
        results.append(result)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        for idx, result in enumerate(results, start=1):
            print(_format_text(result, idx), end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
