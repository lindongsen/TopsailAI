import os
from datetime import datetime
import simplejson

from topsailai.logger.log_chat import logger
from topsailai.utils import thread_local_tool

from topsailai.utils import env_tool
from topsailai.utils.ansi_color import Colors, colored


g_flag_print_step = None
TAIL_PREVIEW_LENGTH = 300
PRINT_STEP_SIMPLE_PREVIEW_LENGTH = 160
# First tool-call argument preview stays short to keep simple-mode output on one line.
PRINT_STEP_TOOL_ARG_PREVIEW_LENGTH = 80
# Substrings (case-insensitive) marking argument names whose values must be masked.
PRINT_STEP_SENSITIVE_ARG_KEYS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "accesskey",
    "private_key",
    "credential",
)
PRINT_STEP_MODE_ENV = "TOPSAILAI_PRINT_STEP_MODE"
# Ordered so callers (e.g. instructions) can present a stable numbered list.
PRINT_STEP_MODE_LIST = ("normal", "simple")
PRINT_STEP_MODE_DEFAULT = "normal"
PRINT_STEP_MODES = set(PRINT_STEP_MODE_LIST)
PRINT_STEP_MODE_DESCRIPTIONS = {
    "normal": "legacy full step output",
    "simple": "bounded one-line summaries with first tool-call argument; task/thought/action/final/inquiry fully printed",
}
PRINT_STEP_FULL_PREFIXES = ("task", "thought", "action", "final", "inquiry")
_print_step_invalid_mode_warned = False


def get_print_step_mode() -> str:
    """Return the configured console detail mode for step messages."""
    global _print_step_invalid_mode_warned

    mode = os.getenv(PRINT_STEP_MODE_ENV, "").strip().lower() or PRINT_STEP_MODE_DEFAULT
    if mode in PRINT_STEP_MODES:
        return mode
    if not _print_step_invalid_mode_warned:
        logger.warning(
            "Invalid %s value %r; falling back to '%s'",
            PRINT_STEP_MODE_ENV,
            mode,
            PRINT_STEP_MODE_DEFAULT,
        )
        _print_step_invalid_mode_warned = True
    return PRINT_STEP_MODE_DEFAULT


def _safe_step_text(value) -> str:
    """Convert a step value to text without propagating conversion errors."""
    try:
        return str(value)
    except Exception:
        return repr(type(value))


def _format_simple_preview(value) -> str:
    """Return a bounded preview of the first non-empty line in a value."""
    text = _safe_step_text(value)
    lines = text.splitlines()
    first_line = next((line for line in lines if line.strip()), "")
    preview = " ".join(first_line.split())
    if not preview:
        return ""

    is_truncated = len(preview) > PRINT_STEP_SIMPLE_PREVIEW_LENGTH
    is_truncated = is_truncated or any(
        line.strip() for line in lines[lines.index(first_line) + 1:]
    )
    preview = preview[:PRINT_STEP_SIMPLE_PREVIEW_LENGTH]
    if is_truncated:
        preview += f" [truncated, {len(text)} chars total]"
    return preview


def _tool_call_name(tool_call) -> str:
    """Extract a tool name without serializing tool-call arguments."""
    function = None
    if isinstance(tool_call, dict):
        function = tool_call.get("function")
        name = tool_call.get("name")
    else:
        function = getattr(tool_call, "function", None)
        name = getattr(tool_call, "name", None)

    if isinstance(function, dict):
        name = function.get("name") or name
    elif function is not None:
        name = getattr(function, "name", None) or name
    return _safe_step_text(name) if name else "unknown"


def _as_tool_calls(msg):
    """Return tool-call items when the message has a recognizable shape."""
    if isinstance(msg, dict) and "tool_calls" in msg:
        tool_calls = msg.get("tool_calls")
        return tool_calls if isinstance(tool_calls, list) else None
    if not isinstance(msg, list) or not msg:
        return None

    for item in msg:
        if isinstance(item, dict):
            if not any(key in item for key in ("function", "name", "arguments", "id")):
                return None
        elif not any(hasattr(item, key) for key in ("function", "name", "arguments", "id")):
            return None
    return msg


def _tool_call_arguments(tool_call):
    """Return raw tool-call arguments from dict or SDK attribute shapes.

    Only plain payload types are accepted so unexpected objects (for example
    mocks) never leak their repr into console output.
    """
    function = None
    if isinstance(tool_call, dict):
        function = tool_call.get("function")
        arguments = tool_call.get("arguments")
    else:
        function = getattr(tool_call, "function", None)
        arguments = getattr(tool_call, "arguments", None)

    if isinstance(function, dict):
        arguments = function.get("arguments", arguments)
    elif function is not None:
        arguments = getattr(function, "arguments", arguments)

    if isinstance(arguments, (dict, list, str)):
        return arguments
    return None


def _is_sensitive_arg_key(key) -> bool:
    """Return True when an argument name looks like it carries credentials."""
    lowered = _safe_step_text(key).lower()
    return any(word in lowered for word in PRINT_STEP_SENSITIVE_ARG_KEYS)


def _format_simple_arg_value(key, value) -> str:
    """Render one first-argument preview as ``key=value`` on a single line.

    Args:
        key: Argument name; empty for an unnamed value.
        value: Parsed argument value.

    Returns:
        Bounded single-line text. Sensitive keys always render ``***``.
    """
    if isinstance(value, (dict, list)):
        try:
            text = simplejson.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            text = _safe_step_text(value)
    elif value is None:
        text = "None"
    elif isinstance(value, str):
        text = value if value != "" else '""'
    else:
        text = _safe_step_text(value)

    if _is_sensitive_arg_key(key):
        return f"{key}=***" if key else "***"

    text = " ".join(text.split())
    if len(text) > PRINT_STEP_TOOL_ARG_PREVIEW_LENGTH:
        text = (
            f"{text[:PRINT_STEP_TOOL_ARG_PREVIEW_LENGTH]}"
            f" [truncated, {len(text)} chars total]"
        )
    return f"{key}={text}" if key else text


def _format_simple_tool_arg(tool_call) -> str:
    """Return a preview of the first tool-call argument, or "" when absent.

    Rules: a JSON object exposes its first key/value pair (generation order);
    any other payload is shown as an unnamed value. Missing, empty or unparsable
    arguments yield "" so callers keep the legacy name-only summary and console
    printing never raises.
    """
    arguments = _tool_call_arguments(tool_call)
    if arguments is None:
        return ""

    if isinstance(arguments, dict):
        if not arguments:
            return ""
        key, value = next(iter(arguments.items()))
        return _format_simple_arg_value(key, value)

    if isinstance(arguments, list):
        return _format_simple_arg_value("", arguments) if arguments else ""

    text = arguments.strip()
    if not text:
        return ""
    try:
        parsed = simplejson.loads(text)
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        if not parsed:
            return ""
        key, value = next(iter(parsed.items()))
        return _format_simple_arg_value(key, value)
    if parsed is None and text not in ("null", "None"):
        # Not a JSON payload: show the raw string as an unnamed value.
        return _format_simple_arg_value("", text)
    return _format_simple_arg_value("", parsed)


def _format_simple_tool_calls(tool_calls: list) -> str:
    """Return a tool-call summary with names and the first argument preview.

    Tool-call IDs are never included. Each distinct ``(name, first argument)``
    pair is rendered on its own indented line; calls without usable arguments
    keep the legacy name-only summary line unchanged.
    """
    names = []
    details = []
    seen = set()
    for tool_call in tool_calls:
        name = _tool_call_name(tool_call)
        if name not in names:
            names.append(name)
        first_arg = _format_simple_tool_arg(tool_call)
        if not first_arg:
            continue
        dedup_key = (name, first_arg)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        details.append(f"  {name}({first_arg})")

    summary = f"[tool_calls] count={len(tool_calls)} names={','.join(names)}"
    if not details:
        return summary
    return "\n".join([summary, *details])


def _parse_step_message(msg):
    """Parse structured JSON or TopsailAI step text, leaving plain strings unchanged."""
    if not isinstance(msg, str):
        return msg
    try:
        parsed = simplejson.loads(msg)
    except Exception:
        parsed = None
    if isinstance(parsed, (dict, list)):
        return parsed

    from topsailai.utils import format_tool
    parsed_steps = format_tool.parse_topsailai_format(msg)
    if not parsed_steps:
        return msg
    return [
        {"step_name": step_name, "raw_text": raw_text}
        for step_name, raw_text in parsed_steps.items()
    ]


def format_print_step_simple(msg) -> str:
    """Format a step message as bounded, low-noise console output."""
    if msg is None or msg == "" or msg == []:
        return ""

    parsed_msg = _parse_step_message(msg)
    tool_calls = _as_tool_calls(parsed_msg)
    if tool_calls is not None:
        return _format_simple_tool_calls(tool_calls) if tool_calls else ""

    items = parsed_msg if isinstance(parsed_msg, list) else [parsed_msg]
    output = []
    for item in items:
        if isinstance(item, dict) and "step_name" in item:
            step_name = _safe_step_text(item.get("step_name"))
            raw_text = _safe_step_text(item.get("raw_text", ""))
            if step_name.startswith(PRINT_STEP_FULL_PREFIXES):
                if raw_text.strip():
                    output.append(f"[{step_name}] {raw_text}")
                continue
            preview = _format_simple_preview(raw_text)
            if preview:
                output.append(f"[{step_name}] {preview}")
            continue
        preview = _format_simple_preview(item)
        if preview:
            output.append(preview)
    return "\n".join(output)

def get_truncation_len() -> int|None:
    """Get the truncation length for debug printing from environment.

    Returns:
        int|None: Truncation length as integer if DEBUG_PRINT_TRUNCATE_LENGTH is set,
                 otherwise None.
    """
    truncation_len = os.getenv("DEBUG_PRINT_TRUNCATE_LENGTH")
    try:
        if truncation_len:
            return int(truncation_len)
    except Exception:
        pass
    return None


def _is_color_enabled(color_enabled=None) -> bool:
    """Resolve whether ANSI color should be emitted.

    Priority chain: explicit parameter > TOPSAILAI_PRINT_COLOR_ENABLED > NO_COLOR > TTY.

    Args:
        color_enabled: Explicit override. ``None`` means auto-detect from env/TTY.

    Returns:
        True if colors should be applied, False otherwise.
    """
    if color_enabled is not None:
        return bool(color_enabled)
    env_val = os.getenv("TOPSAILAI_PRINT_COLOR_ENABLED")
    if env_val is not None:
        return env_val.strip().lower() in ("1", "true", "yes", "on")
    if os.getenv("NO_COLOR"):
        return False
    try:
        import sys
        return sys.stdout.isatty()
    except Exception:
        return False

_STYLE_MAP = {
    "info":     (Colors.CYAN, False, False),
    "debug":    (Colors.GRAY, False, True),
    "warning":  (Colors.YELLOW, False, False),
    "error":    (Colors.RED, False, False),
    "critical": (Colors.RED, True, False),   # bold
}

def _style(msg, kind: str, color_enabled=None) -> str:
    """Colorize *msg* according to semantic *kind*, unless disabled.

    Caller MUST ensure plain-text truncation is done BEFORE invoking
    this function; ANSI codes are wrapped afterward so escape sequences
    and RESET cannot be lost by truncation.

    Args:
        msg: Message content to style.
        kind: One of the keys in ``_STYLE_MAP``.
        color_enabled: See :func:`_is_color_enabled`.

    Returns:
        The styled string (or original when coloring is disabled).
    """
    text = str(msg)
    if not _is_color_enabled(color_enabled):
        return text
    color, bold, dim = _STYLE_MAP[kind]
    return colored(text, color=color, bold=bold, dim=dim)

def _format_truncated_msg(msg, truncation_len:int|None=None) -> str:
    if truncation_len is None:
        truncation_len = get_truncation_len()
    raw_msg = msg
    msg = str(msg)
    if msg and len(msg) > truncation_len:
        return msg[:truncation_len] + f"\n\n[Display truncated: {len(msg)} chars total; showing last {TAIL_PREVIEW_LENGTH} below]\n\n{msg[-TAIL_PREVIEW_LENGTH:]}"
    return raw_msg

def truncate_msg(msg:str|list|dict, key_name="step_name", value_name="raw_text") -> str:
    """Truncate message content if it exceeds configured length.

    Args:
        msg (str|list|dict): Message to truncate. If string length exceeds limit,
                              it may be parsed as JSON for structured truncation.
        key_name (str): Key name for structured messages (default: "step_name").
        value_name (str): Value name for structured messages (default: "raw_text").

    Returns:
        str: Truncated message as string (possibly JSON).
    """
    from topsailai.ai_base.constants import (
        STEP_NAME_FINAL, STEP_NAME_FINAL_ANSWER, STEP_NAME_THOUGHT,
        STEP_NAME_TASK,
        STEP_NAME_INQUIRY,
    )
    from topsailai.utils import json_tool
    from .format_tool import to_list

    truncation_len = get_truncation_len()
    if truncation_len and truncation_len > 0:
        if isinstance(msg, str) and len(msg) > (truncation_len + 100):
            msg_d = json_tool.safe_json_load(msg)
            if msg_d:
                msg = msg_d

        # Ignore Now
        #if isinstance(msg, str):
        #    if len(msg) > truncation_len:
        #        return _format_truncated_msg(msg)

        if isinstance(msg, (dict, list)):
            for _msg_d in to_list(msg):
                if not isinstance(_msg_d, dict):
                    continue
                _key_text = _msg_d.get(key_name)
                if _key_text in [
                    STEP_NAME_THOUGHT,
                    STEP_NAME_FINAL,
                    STEP_NAME_FINAL_ANSWER,
                    STEP_NAME_TASK,
                    STEP_NAME_INQUIRY,
                ]:
                    continue
                _raw_text = _msg_d.get(value_name)
                if _raw_text:
                    _msg_d[value_name] = _format_truncated_msg(_raw_text)

            msg = json_tool.json_dump(msg, indent=2)

    return msg

def enable_flag_print_step():
    """Enable step-by-step printing for debugging purposes.

    When enabled, print_step() calls will output messages with timestamps.
    This is useful for tracking the execution flow during development.
    """
    global g_flag_print_step
    g_flag_print_step = True

def disable_flag_print_step():
    """Disable step-by-step printing.

    When disabled, print_step() calls will not output any messages.
    """
    global g_flag_print_step
    g_flag_print_step = False

def print_with_time(msg, need_format=False, color_kind=None, color_enabled=None):
    """Print a message with a timestamp and optional agent/model name prefix.

    Args:
        msg: Message string to print
        need_format: Whether to format structured messages for display.
        color_kind: Optional semantic style key (``info``/``debug``/``warning``/
            ``error``/``critical``). When set, the fully-built output line is
            wrapped with ANSI colors *after* any truncation/formatting so that
            escape sequences are never counted toward truncation length and the
            RESET code cannot be lost by truncation.
        color_enabled: Explicit override for color enablement. See
            :func:`_is_color_enabled` for the resolution priority.

    The output format includes:
    - Current timestamp in YYYY-MM-DD HH:MM:SS format
    - Optional agent name if set in thread-local storage
    - Optional model name from the active agent's LLM model
    - The message content
    """
    from . import env_tool
    if not env_tool.is_interactive_mode():
        return

    from . import thread_local_tool, format_tool

    try:
        msg = truncate_msg(msg)
        if need_format:
            msg = format_tool.to_topsailai_format(
                msg, key_name="step_name", value_name="raw_text",
                for_print=True,
            ).strip()
    except Exception as e:
        # debug
        logger.exception("fail to format message: [>>>%s<<<], e=[%s]", msg, e)
        pass

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = (f"[{now}] {msg}")
    agent_name = thread_local_tool.get_thread_var(thread_local_tool.KEY_AGENT_NAME)
    model_name = ""
    agent_obj = thread_local_tool.get_thread_var(thread_local_tool.KEY_AGENT_OBJECT)
    if agent_obj is not None and hasattr(agent_obj, "llm_model"):
        model_name = getattr(agent_obj.llm_model, "model_name", "") or ""

    prefix_parts = []
    if agent_name:
        prefix_parts.append(f"[{agent_name}]")
    if model_name:
        prefix_parts.append(f"[{model_name}]")
    if prefix_parts:
        content = " ".join(prefix_parts) + " " + content

    if color_kind is not None:
        content = _style(content, color_kind, color_enabled)

    print(content)

def print_step(msg, need_format=True, need_log=False):
    """Print a step message if step printing is enabled.

    IMPORTANT: This function is reserved for printing agent2llm message
    interactions in ai_base/prompt_base.py only. For all other logging or
    printing needs, use print_info() instead.

    This function only prints messages when:
    - DEBUG environment variable is set to "1"
    - OR g_flag_print_step is explicitly enabled

    Args:
        msg: Step message to print
    """
    if need_log:
        logger.info(msg)

    # thread required, refer to tools/agent_tool.py:
    # Background story-generation thread disables debug printing
    if thread_local_tool.get_thread_var(
        thread_local_tool.KEY_FLAG_DEBUG
    ) == 0:
        return
    if g_flag_print_step is False:
        return
    if not env_tool.is_need_print():
        return

    if get_print_step_mode() == "normal":
        print_with_time(msg, need_format=need_format)
        return

    simple_msg = format_print_step_simple(msg)
    if simple_msg:
        print_with_time(simple_msg, need_format=False)
    return

def print_info(msg, color_enabled=None):
    """ Print a message to both logger and console.

    Args:
        msg: Message content to log and print.
        color_enabled: Explicit override for color enablement (see
            :func:`_is_color_enabled`). Defaults to auto-detection.
    """
    logger.info(msg)
    print_with_time(msg, need_format=False, color_kind="info",
                    color_enabled=color_enabled)

def print_debug(msg, color_enabled=None):
    """Print a debug message with step printing enabled.

    Args:
        msg: Debug message to print.
        color_enabled: Explicit override for color enablement (see
            :func:`_is_color_enabled`). Defaults to auto-detection.
    """
    logger.debug(msg)
    # thread required, refer to tools/agent_tool.py:
    # Background story-generation thread disables debug printing
    if thread_local_tool.get_thread_var(
        thread_local_tool.KEY_FLAG_DEBUG
    ) == 0:
        return
    if g_flag_print_step or env_tool.is_need_print():
        print_with_time(f"[DEBUG] {msg}", need_format=False,
                        color_kind="debug", color_enabled=color_enabled)

def print_error(msg, exception=False, color_enabled=None):
    """Print an error message to both logger and console.

    This function logs the error using the application's logger
    and also prints it to the console with a timestamp.

    Args:
        msg: Error message to log and print
        exception: Whether to treat *msg* as an exception for logging.
        color_enabled: Explicit override for color enablement (see
            :func:`_is_color_enabled`). Defaults to auto-detection.
    """
    if isinstance(msg, Exception) or exception:
        logger.exception(msg)
    else:
        logger.error(msg)
    print_with_time(f"Error: {msg}", need_format=False,
                    color_kind="error", color_enabled=color_enabled)
    return

def print_warning(msg, color_enabled=None):
    """Print a warning message to both logger and console.

    This function logs the warning using the application's logger
    and also prints it to the console with a timestamp.

    Args:
        msg: Warning message to log and print
        color_enabled: Explicit override for color enablement (see
            :func:`_is_color_enabled`). Defaults to auto-detection.
    """
    logger.warning(msg)
    print_with_time(f"Warning: {msg}", need_format=False,
                    color_kind="warning", color_enabled=color_enabled)
    return

def print_critical(msg, color_enabled=None):
    """Print a critical message to both logger and console.

    This function logs the critical message using the application's logger
    and also prints it to the console with a timestamp.

    Args:
        msg: Critical message to log and print
        color_enabled: Explicit override for color enablement (see
            :func:`_is_color_enabled`). Defaults to auto-detection.
    """
    logger.critical(msg)
    print_with_time(f"Critical: {msg}", need_format=False,
                    color_kind="critical", color_enabled=color_enabled)
    return

def format_dict_to_md(d:dict) -> str:
    """Format a dictionary as a markdown document for readability.

    This function converts a dictionary into a markdown string where each key
    becomes a level‑2 heading and its value is placed inside a code block.
    String values are printed as‑is; other types are serialized as JSON.

    Args:
        d (dict): The dictionary to format.

    Returns:
        str: A markdown string representing the dictionary.

    Example:
        >>> format_dict_to_md({"name": "Alice", "age": 30})
        '\n## name\n```\nAlice\n```\n\n## age\n```\n30\n```\n'
    """
    s = ""
    for k, v in d.items():
        s += f"\n## {k}\n"
        s += "```\n"
        if isinstance(v, str):
            s += v.strip()
        else:
            s += simplejson.dumps(v, indent=2, ensure_ascii=False)
        s += "\n```\n"

    return s

def add_indent_to_lines(s:str, indent=4) -> str:
    if not s:
        return ""
    new_s = ""
    for line in s.splitlines():
        new_s += " "*indent + line + "\n"
    return new_s
