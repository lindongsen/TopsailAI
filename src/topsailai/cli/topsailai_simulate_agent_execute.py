#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simulate the agent execution phase for a given LLM response.

This CLI parses an LLM response (from text, file or stdin) into steps and runs
the AGENT EXECUTION PHASE headlessly: it dispatches each ``action`` through the
registered tool set, feeds back observations, and stops when a ``final_answer``
is reached -- without needing a live LLM. It complements
``topsailai_format_response`` which only performs the parsing stage.
"""

import argparse
import json
import os
import sys

import _import_topsailai  # noqa: F401

from topsailai.ai_base.llm_control.message import format_response
from topsailai.utils.format_tool import (
    parse_topsailai_format,
    to_topsailai_format,
)

# change PWD after importing topsailai (mirror topsailai_format_response)
PWD = os.getenv("TOPSAILAI_PWD")
if PWD:
    os.chdir(PWD)

EXIT_OK = 0          # final answer produced
EXIT_ERROR = 1       # runtime / execution error
EXIT_USAGE = 2       # argument misuse
EXIT_MAX_STEPS = 3   # max-steps exceeded without reaching a final answer


class SimulateError(Exception):
    """Base exception for simulation failures."""


class MaxStepsExceeded(SimulateError):
    """Raised when the processed step budget is exhausted before completion."""

    def __init__(self, max_steps: int):
        super().__init__(f"max-steps ({max_steps}) exceeded without reaching a final answer")
        self.max_steps = max_steps


def resolve_path(path: str) -> str:
    """Resolve a relative path against the original TOPSAILAI_PWD.

    Importing the parent project's source tree may change the current working
    directory. To keep file arguments working when invoked through the
    dispatcher script, relative paths are resolved against the directory where
    the user ran the command.
    """
    pwd = os.getenv("TOPSAILAI_PWD")
    if pwd and not os.path.isabs(path):
        return os.path.join(os.path.abspath(pwd), path)
    return path


def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_simulate_agent_execute",
        description=(
            "Run the agent execution phase for an LLM response: parse it into "
            "steps, dispatch actions through the registered tools, feed back "
            "observations, and stop at a final answer."
        ),
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--text",
        type=str,
        help="Raw LLM response text to simulate.",
    )
    group.add_argument(
        "--file",
        type=str,
        help="Path to a file containing the LLM response to simulate.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Paths to files containing responses to simulate. Use '-' to read from stdin.",
    )

    exec_group = parser.add_argument_group("execution controls")
    exec_group.add_argument(
        "--max-steps",
        type=int,
        default=50,
        help="Hard cap on total processed steps across the run (default: 50).",
    )
    exec_group.add_argument(
        "--interactive",
        action="store_true",
        help="Allow interactive prompts for inquiry/single-thought steps; otherwise use automatic non-interactive observation.",
    )
    exec_group.add_argument(
        "--show-tools",
        action="store_true",
        help="Print the list of available tool names before executing.",
    )
    exec_group.add_argument(
        "--exclude-tools",
        type=str,
        default="",
        help="Filter out tools whose full name starts with any ';'-separated prefix.",
    )
    exec_group.add_argument(
        "--only-tools",
        type=str,
        default="",
        help="Restrict the tool map to tools matching any ';'-separated prefix.",
    )

    out_group = parser.add_argument_group("output controls")
    out_group.add_argument(
        "--output-format",
        type=str,
        default="transcript",
        choices=("transcript", "json", "topsailai"),
        help="Output format (default: transcript).",
    )
    out_group.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Indentation level for JSON output (default: 2).",
    )
    out_group.add_argument(
        "--compact",
        action="store_true",
        help="Output compact JSON instead of pretty-printed JSON.",
    )
    out_group.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational chatter and print only the final answer.",
    )
    return parser.parse_args(argv)


def read_file(path: str) -> str:
    """Read text from a file using UTF-8 encoding."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_input(path: str) -> str:
    """Read text from a file or stdin when path is '-'."""
    if path == "-":
        return sys.stdin.read()
    return read_file(path)


def build_tool_map(exclude: str = "", only: str = "") -> dict:
    """Build the tool map honoring exclude/only prefix filters.

    Args:
        exclude: ';'-separated prefixes; tools starting with any are removed.
        only: ';'-separated prefixes; only tools matching any are kept.

    Returns:
        dict: filtered {tool_name: callable} mapping.
    """
    from topsailai.tools.base.common import TOOLS

    tool_map = dict(TOOLS)

    exclude_prefixes = [p.strip() for p in exclude.split(";") if p.strip()]
    for prefix in exclude_prefixes:
        tool_map = {k: v for k, v in tool_map.items() if not k.startswith(prefix)}

    only_prefixes = [p.strip() for p in only.split(";") if p.strip()]
    if only_prefixes:
        matched = {}
        for prefix in only_prefixes:
            for k, v in tool_map.items():
                if k.startswith(prefix):
                    matched[k] = v
        tool_map = matched

    return tool_map


def extract_pending_final(text: str):
    """Extract a candidate final answer that the framework mistake-fixer strips.

    The live ReAct loop intentionally merges/drops a trailing ``final_answer``
    when an ``action`` precedes it, because the tool result must be observed
    before finalizing. A fixed-response simulator cannot reach that state, so we
    capture the original final text from the raw input as a fallback result.

    Args:
        text: Raw LLM response text (before any mistake fixing).

    Returns:
        str or None: The extracted final answer text, else None.
    """
    if not text:
        return None
    stripped = text.strip()
    try:
        parsed = parse_topsailai_format(stripped)
    except Exception:
        parsed = {}
    if parsed:
        for key in reversed(list(parsed.keys())):
            if key.startswith("final"):
                value = parsed[key]
                return value if isinstance(value, str) and value.strip() else None
    # Fall back to JSON list-of-steps shape.
    try:
        data = json.loads(stripped)
    except Exception:
        return None
    steps = data if isinstance(data, list) else [data]
    for step in reversed(steps):
        if isinstance(step, dict) and str(step.get("step_name", "")).startswith("final"):
            value = step.get("raw_text")
            if isinstance(value, str) and value.strip():
                return value
    return None
def _step_record(index: int, step: dict, ret) -> dict:
    """Build a structured record for one processed step."""
    record = {
        "index": index,
        "step_name": step.get("step_name"),
        "raw_text": step.get("raw_text"),
        "tool_call": step.get("tool_call"),
        "tool_args": step.get("tool_args"),
    }
    if getattr(ret, "user_msg", None) is not None:
        record["user_msg"] = ret.user_msg
    if getattr(ret, "tool_msg", None) is not None:
        record["observation"] = ret.tool_msg
    if getattr(ret, "result", None) is not None:
        record["result"] = ret.result
    return record


def simulate(text: str, *, max_steps: int = 100, flag_interactive: bool = False,
             tool_map: dict = None, show_tools: bool = False) -> tuple:
    """Run the headless agent-execution loop over a parsed LLM response.

    Steps within the provided response are processed sequentially. Each
    ``action`` dispatches its tool and records the resulting observation inline;
    processing continues until a ``final_answer`` terminates the task or the
    step budget is exhausted.

    Args:
        text: Raw LLM response text.
        max_steps: Maximum number of steps to process.
        flag_interactive: Allow interactive prompting for inquiry/thought steps.
        tool_map: Tool map used for dispatch; defaults to all registered tools.
        show_tools: Print the available tool names first.

    Returns:
        tuple[list, object]: (records, result). ``result`` holds the final
        answer text when a final answer was reached, else None.

    Raises:
        MaxStepsExceeded: When the step budget is exhausted without a final answer.
    """
    if tool_map is None:
        tool_map = build_tool_map()

    if show_tools:
        print(f"[available_tools] [{len(tool_map)}] {sorted(tool_map.keys())}")

    # Capture a candidate final answer before mistake-fixing strips it.
    pending_final = extract_pending_final(text)

    # Force deterministic interactivity regardless of ambient env override.
    prev_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
    os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = "1" if flag_interactive else "0"
    try:
        from topsailai.ai_base.agent_types.react import AgentStepCall

        step_call = AgentStepCall(flag_interactive=flag_interactive)
        response = format_response(text)
        records = []
        processed = 0
        result = None

        for i, step in enumerate(response):
            if processed >= max_steps:
                raise MaxStepsExceeded(max_steps)
            try:
                ret = step_call(step, tools=tool_map, response=response, index=i)
            except Exception as e:  # surface decorator/framework errors gracefully
                record = _step_record(i, step, type("R", (), {"code": None})())
                record["error"] = str(e)
                records.append(record)
                processed += 1
                continue

            record = _step_record(i, step, ret)
            records.append(record)
            processed += 1

            code = getattr(ret, "code", None)
            if code == ret.CODE_TASK_FINAL:
                result = ret.result
                break

# The framework merges/drops a trailing final_answer after an action,
        # so fall back to the captured original text when no live final was reached.
        if result is None and pending_final is not None:
            result = pending_final
        return records, result
    finally:
        if prev_env is None:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        else:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = prev_env


def flatten_for_topsailai(records: list) -> list:
    """Flatten records into a step list including synthesized observations."""
    flattened = []
    for rec in records:
        entry = {}
        if rec.get("step_name"):
            entry["step_name"] = rec["step_name"]
        if rec.get("raw_text") is not None:
            entry["raw_text"] = rec["raw_text"]
        elif rec.get("tool_call"):
            entry["raw_text"] = json.dumps(
                {"tool_call": rec["tool_call"], "tool_args": rec.get("tool_args")},
                ensure_ascii=False,
            )
        if entry:
            flattened.append(entry)
        if rec.get("observation") is not None:
            flattened.append({"step_name": "observation", "raw_text": str(rec["observation"])})
    return flattened


def render_transcript(records: list, quiet: bool = False) -> str:
    """Render a human-readable per-step transcript."""
    lines = []
    for rec in records:
        idx = rec.get("index", "")
        name = rec.get("step_name", "")
        header = f"[{idx}] {name}" if idx != "" else name
        lines.append(header)
        if rec.get("raw_text") is not None:
            lines.append(str(rec["raw_text"]))
        if rec.get("tool_call"):
            args = rec.get("tool_args") or {}
            lines.append(f"-> tool: {rec['tool_call']} {json.dumps(args, ensure_ascii=False)}")
        if rec.get("observation") is not None:
            lines.append(f"-> observation: {str(rec['observation'])}")
        if rec.get("user_msg") is not None:
            lines.append(f"-> user_msg: {str(rec['user_msg'])}")
        if rec.get("error") is not None:
            lines.append(f"-> error: {str(rec['error'])}")
        if rec.get("result") is not None:
            lines.append(f"-> result: {str(rec['result'])}")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


def render_output(records: list, result, fmt: str, indent: int, compact: bool,
                  quiet: bool) -> str:
    """Serialize simulation results to the requested output format."""
    if quiet:
        return str(result) if result is not None else ""
    if fmt == "transcript":
        body = render_transcript(records, quiet)
        if result is not None:
            body = f"{body}\n\nFinal answer:\n{result}"
        return body
    if fmt == "topsailai":
        return to_topsailai_format(
            flatten_for_topsailai(records),
            key_name="step_name",
            value_name="raw_text",
            for_print=True,
        )
    payload = {"records": records, "result": result}
    if compact:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(payload, ensure_ascii=False, indent=indent)


def main(argv=None) -> int:
    """Entry point for the agent-execution simulator CLI."""
    args = parse_args(argv)

    if args.text is not None:
        if args.files:
            print("Error: --text cannot be used with positional file arguments.", file=sys.stderr)
            return EXIT_USAGE
        text = args.text
    elif args.file is not None:
        if args.files:
            print("Error: --file cannot be used with positional file arguments.", file=sys.stderr)
            return EXIT_USAGE
        file_path = resolve_path(args.file)
        if not os.path.isfile(file_path):
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            return EXIT_ERROR
        try:
            text = read_file(file_path)
        except OSError as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            return EXIT_ERROR
    elif args.files:
        if len(args.files) > 1:
            print("Error: exactly one input is supported (--text, --file, or a single file path).", file=sys.stderr)
            return EXIT_USAGE
        path = args.files[0]
        if path == "-":
            text = sys.stdin.read()
        else:
            resolved = resolve_path(path)
            if not os.path.isfile(resolved):
                print(f"Error: file not found: {path}", file=sys.stderr)
                return EXIT_ERROR
            try:
                text = read_file(resolved)
            except OSError as e:
                print(f"Error reading file: {e}", file=sys.stderr)
                return EXIT_ERROR
    else:
        print("Error: provide --text, --file, or a file path ('-' for stdin).", file=sys.stderr)
        return EXIT_USAGE

    try:
        tool_map = build_tool_map(args.exclude_tools, args.only_tools)
        records, result = simulate(
            text,
            max_steps=args.max_steps,
            flag_interactive=args.interactive,
            tool_map=tool_map,
            show_tools=args.show_tools,
        )
    except MaxStepsExceeded as e:
        print(f"Error: {e}", file=sys.stderr)
        return EXIT_MAX_STEPS
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return EXIT_ERROR

    if result is None:
        print("Error: no final answer produced during simulation.", file=sys.stderr)
        return EXIT_ERROR

    print(render_output(records, result, args.output_format, args.indent, args.compact, args.quiet))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())