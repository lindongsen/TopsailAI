"""Strict noninteractive runtime boundary, with literal message preservation.

Author: DawsonLin
"""

import argparse
import json
import math
from pathlib import Path
import re
import sys

from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.runtime_operations import (
    MESSAGE_LIMIT, RuntimeRequest, RuntimeResult, execute_runtime_request,
)


class RuntimeUsageError(ValueError):
    """Reject syntax without exposing submitted values in diagnostics."""


class RuntimeInputError(Exception):
    """Classify stdin device failures separately from invalid arguments."""


class RuntimeParser(argparse.ArgumentParser):
    """Keep parser failures within the same structured output contract."""

    def error(self, message):
        """Avoid argparse diagnostics that could echo message or JSON values."""
        raise RuntimeUsageError("Invalid runtime arguments")


class UniqueValue(argparse.Action):
    """Permit identical repeated options, but reject conflicting values."""

    def __call__(self, parser, namespace, values, option_string=None):
        """Store explicit values once in the shared parser namespace."""
        if hasattr(namespace, self.dest) and getattr(namespace, self.dest) != values:
            raise RuntimeUsageError("Conflicting runtime options")
        setattr(namespace, self.dest, values)


def build_parser():
    """Build offline help and a shared option namespace for either syntax."""
    parser = RuntimeParser(
        prog="topsailai runtime", allow_abbrev=False,
        description="Execute one exact send, btw or control operation",
        epilog=("Use send/btw -m TEXT or --stdin; control ACTION -a JSON; "
                "or -i '/send TEXT', '/ctx.btw TEXT', '/control ACTION JSON', "
                "'/control.ACTION JSON'. A single whitespace delimiter is consumed; "
                "remaining message whitespace is preserved. Timeout excludes stdin "
                "and blocking injection append. Delivery is not final consumption."),
    )
    for flags, dest, kind in [
        (("-s", "--session-id", "--session_id"), "session_id", str),
        (("-p", "--pid"), "pid", int),
        (("--timeout",), "timeout", float),
        (("-i", "--instruction"), "instruction", str),
        (("-m", "--message"), "message", str),
        (("-a", "--args"), "payload_text", str),
    ]:
        parser.add_argument(*flags, dest=dest, type=kind, action=UniqueValue,
                            default=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="emit one public JSON result")
    parser.add_argument("--stdin", action="store_true", help="read bounded non-TTY UTF-8 input")
    parser.add_argument("positionals", nargs="*", metavar="ACTION")
    return parser


def _json_requested(argv):
    """Recognize option tokens without mistaking consumed values for flags."""
    value_flags = {"-s", "--session-id", "--session_id", "-p", "--pid",
                   "--timeout", "-i", "--instruction", "-m", "--message", "-a", "--args"}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            return False
        if token == "--json":
            return True
        index += 2 if token in value_flags else 1
    return False


def _split_token(text):
    """Consume exactly one command delimiter and retain the remaining text."""
    match = re.match(r"([^\s]+)(?:\s([\s\S]*))?\Z", text)
    if not match:
        raise RuntimeUsageError("Invalid runtime instruction")
    return match.group(1), match.group(2)


def _payload(text):
    """Require an encodable JSON object without nonfinite constants."""
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise RuntimeUsageError("Control arguments must be an object")
        json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise RuntimeUsageError("Invalid control arguments") from exc


def normalize(args):
    """Validate syntax and selectors before any stdin read or target access."""
    session_id, pid = getattr(args, "session_id", None), getattr(args, "pid", None)
    timeout = getattr(args, "timeout", 5.0)
    if (session_id is None and pid is None) or (pid is not None and pid <= 0):
        raise RuntimeUsageError("Supply a session or positive PID")
    if session_id is not None and (not session_id or session_id in (".", "..") or re.search(r"[\s/\\\x00]", session_id)):
        raise RuntimeUsageError("Invalid session identifier")
    if not math.isfinite(timeout) or timeout <= 0:
        raise RuntimeUsageError("Timeout must be positive and finite")
    instruction = getattr(args, "instruction", None)
    message = getattr(args, "message", None)
    payload_text = getattr(args, "payload_text", None)
    control_action = None
    if instruction is not None:
        if args.positionals or message is not None or payload_text is not None:
            raise RuntimeUsageError("Conflicting instruction sources")
        token, body = _split_token(instruction)
        if token in ("/send", "/ctx.btw"):
            action, message = ("send" if token == "/send" else "btw"), body
        elif token == "/control":
            if body is None:
                raise RuntimeUsageError("Missing control action")
            control_action, payload_text = _split_token(body)
            action = "control"
        elif token.startswith("/control.") and len(token) > len("/control."):
            action, control_action, payload_text = "control", token[len("/control."):], body
        else:
            raise RuntimeUsageError("Unsupported runtime instruction")
    else:
        if not args.positionals or args.positionals[0] not in ("send", "btw", "control"):
            raise RuntimeUsageError("Missing runtime action")
        action = args.positionals[0]
        expected = 2 if action == "control" else 1
        if len(args.positionals) != expected:
            raise RuntimeUsageError("Invalid runtime action arguments")
        if action == "control":
            control_action = args.positionals[1]
    if action == "control":
        if args.stdin or message is not None:
            raise RuntimeUsageError("Control does not accept message input")
        return RuntimeRequest(action, control_action=control_action,
                              payload=_payload(payload_text if payload_text is not None else "{}"),
                              timeout=timeout)
    if payload_text is not None or (message is not None) == args.stdin:
        raise RuntimeUsageError("Select exactly one message source")
    return RuntimeRequest(action, message=message, timeout=timeout)


def _read_stdin(stream):
    """Read at most limit plus one bytes and decode strictly, never prompt."""
    try:
        is_tty = stream.isatty()
    except OSError as exc:
        raise RuntimeInputError("Unable to read stdin") from exc
    if is_tty:
        raise RuntimeUsageError("Interactive stdin is not supported")
    binary = getattr(stream, "buffer", stream)
    chunks, size = [], 0
    while size <= MESSAGE_LIMIT:
        try:
            chunk = binary.read(MESSAGE_LIMIT + 1 - size)
        except OSError as exc:
            raise RuntimeInputError("Unable to read stdin") from exc
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise RuntimeUsageError("stdin must provide UTF-8 bytes")
        chunks.append(chunk)
        size += len(chunk)
    if size > MESSAGE_LIMIT:
        raise RuntimeUsageError("Message exceeds input limit")
    try:
        text = b"".join(chunks).decode("utf-8")
    except UnicodeError as exc:
        raise RuntimeUsageError("Invalid UTF-8 stdin") from exc
    if not text.strip():
        raise RuntimeUsageError("Empty stdin message")
    return text


def public_result(result):
    """Select stable fields explicitly; never serialize an exception or body."""
    return {name: getattr(result, name) for name in (
        "ok", "exit_code", "action", "session_id", "pid", "delivery_state",
        "error_code", "message", "bytes_written", "request_id", "response",
        "delivery_unknown",
    )}


def run_runtime_cli(argv, *, stdin=None, executor=None, home_resolver=None):
    """Normalize once, execute once and emit one result; help stays offline."""
    json_mode = _json_requested(argv)
    try:
        args = build_parser().parse_intermixed_args(argv)
        json_mode = args.json
        request = normalize(args)
        if args.stdin:
            request.message = _read_stdin(sys.stdin if stdin is None else stdin)
        home = (home_resolver or get_topsailai_home)()
        result = (executor or execute_runtime_request)(
            request, Path(home) / "workspace" / "task",
            session_id=getattr(args, "session_id", None), pid=getattr(args, "pid", None))
    except RuntimeInputError as exc:
        result = RuntimeResult(
            False, 5, request.action, getattr(args, "session_id", None),
            getattr(args, "pid", None), error_code="input_read_failed",
            message="Unable to read stdin", cause=exc.__cause__)
    except RuntimeUsageError:
        result = RuntimeResult(False, 2, "", error_code="usage_error",
                               message="Invalid runtime arguments")
    if json_mode:
        print(json.dumps(public_result(result), ensure_ascii=True))
    elif result.ok:
        print(f"Runtime {result.action}: {result.delivery_state}")
    else:
        print(f"Runtime failed: {result.error_code} (exit {result.exit_code})", file=sys.stderr)
    return result.exit_code
