"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-08-13
  Purpose: Ask user for decision when task is blocked.
"""

import math
import os
import sys
import threading
import time
from datetime import datetime
from typing import Callable

from topsailai.logger import logger
from topsailai.utils import env_tool, thread_local_tool
from topsailai.context.ctx_safe import truncate_text


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_default_timeout() -> float | None:
    """Return default timeout from TOPSAILAI_HUMAN_DECISION_TIMEOUT.

    0 or unset means infinite (only honored with interactive TTY).
    """
    value = os.getenv("TOPSAILAI_HUMAN_DECISION_TIMEOUT", "0")
    try:
        t = float(value)
        return t if t > 0 else None
    except (TypeError, ValueError):
        return None


def _get_allow_free_text_default() -> bool:
    """Return default allow_free_text from TOPSAILAI_HUMAN_DECISION_ALLOW_FREE_TEXT."""
    return env_tool.is_true(os.getenv("TOPSAILAI_HUMAN_DECISION_ALLOW_FREE_TEXT", "1"))


def _get_max_answer_length() -> int:
    """Return max answer length from TOPSAILAI_HUMAN_DECISION_MAX_ANSWER_LENGTH."""
    value = os.getenv("TOPSAILAI_HUMAN_DECISION_MAX_ANSWER_LENGTH", "30000")
    try:
        n = int(value)
        return n if n > 0 else 2000
    except (TypeError, ValueError):
        return 8000


def _get_prompt_template() -> str:
    """Return custom prompt template from TOPSAILAI_HUMAN_DECISION_PROMPT_TEMPLATE."""
    return os.getenv("TOPSAILAI_HUMAN_DECISION_PROMPT_TEMPLATE", "").strip()


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------

def _resolve_input_funcs():
    """Resolve input functions in priority order.

    Returns:
        tuple[Callable|None, Callable|None]: (with_timeout_func, plain_func)
    """
    with_timeout = thread_local_tool.get_agent_runtime_input_with_timeout()
    plain = thread_local_tool.get_agent_runtime_input()
    return with_timeout, plain


def _has_usable_input_source(with_timeout, plain) -> bool:
    """Check whether any usable input source exists."""
    if with_timeout or plain:
        return True
    if not env_tool.is_interactive_mode():
        return False
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def _is_sub_agent_context() -> bool:
    """Detect sub-agent / deep-recursion context via agent depth counter."""
    depth = thread_local_tool.get_thread_var(thread_local_tool.KEY_AGENT_DEEP, 0) or 0
    return depth > 1


def _read_with_timeout(read_fn, timeout, *args):
    """Run ``read_fn`` in a daemon thread and enforce a deadline.

    Returns the reader result, or ``None`` when the deadline expires.
    When ``timeout`` is falsy (None or <= 0), reads synchronously without limit.
    Exceptions raised by ``read_fn`` propagate to the caller.
    """
    if timeout is None or timeout <= 0:
        return read_fn(*args)

    box = {}

    def runner():
        try:
            box["value"] = read_fn(*args)
        except BaseException as exc:  # pragma: no cover - defensive
            box["error"] = exc

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None
    if "error" in box:
        raise box["error"]
    return box.get("value")


# ---------------------------------------------------------------------------
# Prompt rendering
# ---------------------------------------------------------------------------

def _render_options(options: list[str]) -> str:
    """Render numbered option menu text."""
    lines = []
    for i, opt in enumerate(options):
        lines.append(f"  {i}) {opt}")
    return "\n".join(lines)


def _build_prompt(
    question: str,
    options: list[str] | None,
    allow_free_text: bool,
    default: str | None,
) -> str:
    """Build the full prompt string shown to the user."""
    template = _get_prompt_template()
    display_options = list(options or [])
    opts_text = _render_options(display_options) if display_options else ""

    if template:
        rendered = template.format(
            question=question,
            options=opts_text,
            default=default or "",
        )
        return rendered.strip()

    header = f"[Blocked Task] {question}"
    parts = [header]
    if opts_text:
        parts.append("Options:")
        parts.append(opts_text)
    suffix = ""
    if default:
        suffix = f" (default: {default})"
    if display_options:
        choice_hint = f"Enter your choice [0..{len(display_options)-1}]"
        if allow_free_text:
            choice_hint += " or your own opinion"
        parts.append(f"{choice_hint}, or type '/cancel' to abort{suffix}: ")
    else:
        parts.append(f"Your answer (type '/cancel' to abort){suffix}: ")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Answer normalization & validation
# ---------------------------------------------------------------------------

_CANCEL_WORDS = {"/cancel"}


def _normalize_answer(raw: str) -> str:
    """Strip whitespace and normalize newlines."""
    return raw.strip().rstrip("\n")


def _match_option(answer: str, options: list[str]) -> int:
    """Try to match an answer against provided options.

    Returns zero-based index on match, -1 otherwise.
    """
    if not options:
        return -1
    try:
        idx = int(answer)
        if 0 <= idx < len(options):
            return idx
    except (ValueError, TypeError):
        pass
    lower = answer.lower()
    for i, opt in enumerate(options):
        if opt.lower() == lower:
            return i
    return -1


def _validate_and_resolve(
    raw: str,
    options: list[str] | None,
    allow_free_text: bool,
    default: str | None,
) -> tuple[str, int]:
    """Validate raw input against constraints.

    Returns:
        tuple[str, int]: (answer, option_index)
    """
    answer = _normalize_answer(raw)
    if not answer and default:
        return default, -1
    if options:
        idx = _match_option(answer, options)
        if idx >= 0:
            return options[idx], idx
        if not allow_free_text:
            raise ValueError("Invalid option selected.")
    return answer, -1


# ---------------------------------------------------------------------------
# Core ask function
# ---------------------------------------------------------------------------
def _resolve_allow_free_text(value: int | str | None) -> tuple[bool | None, str | None]:
    """Resolve an integer free-text flag (1=true, 0=false) or its failure reason.

    Numeric strings are converted with ``int()``. Python booleans stay accepted
    because ``bool`` is an ``int`` subclass. ``None`` and blank strings fall back
    to the environment default.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return _get_allow_free_text_default(), None
    if isinstance(value, bool):
        return value, None
    if isinstance(value, int):
        return value != 0, None
    if not isinstance(value, str):
        return None, "invalid_allow_free_text"
    try:
        numeric = int(value.strip())
    except (TypeError, ValueError):
        return None, "invalid_allow_free_text"
    return numeric != 0, None


def _resolve_timeout_seconds(value: float | str | None) -> tuple[float | None, str | None]:
    """Resolve a finite numeric timeout or return its validation reason."""
    if value is None:
        return _get_default_timeout(), None
    if isinstance(value, bool):
        return None, "invalid_timeout_seconds"
    if isinstance(value, str) and not value.strip():
        return None, "invalid_timeout_seconds"
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        return None, "invalid_timeout_seconds"
    if not math.isfinite(timeout):
        return None, "invalid_timeout_seconds"
    return (timeout if timeout > 0 else None), None


def _validate_request(
    question: str,
    options: list[str] | None,
    allow_free_text: int | str | None,
    timeout_seconds: float | str | None,
    default: str | None,
) -> tuple[str | None, bool | None, float | None]:
    """Validate arguments and return reason plus normalized runtime values."""
    if not isinstance(question, str) or not question.strip():
        return "invalid_question", None, None
    if options is not None:
        if not isinstance(options, list) or not all(isinstance(option, str) for option in options):
            return "invalid_options", None, None
    if default is not None and not isinstance(default, str):
        return "invalid_default", None, None
    effective_allow_free_text, reason = _resolve_allow_free_text(allow_free_text)
    if reason is not None:
        return reason, None, None
    effective_timeout, reason = _resolve_timeout_seconds(timeout_seconds)
    if reason is not None:
        return reason, None, None
    return None, effective_allow_free_text, effective_timeout


def ask_decision(
    question: str,
    options: list[str] | None = None,
    allow_free_text: int | str | None = None,
    timeout_seconds: float | str | None = None,
    default: str | None = None,
) -> dict:
    """Ask the user for a decision when the current task is blocked.

    Args:
        question: Required. The blocking question presented to the user.
        options: Optional predefined choices. When provided, the user may pick
            one option index or matching text.
        allow_free_text: Integer flag, ``1`` enables custom free-text answers and
            ``0`` restricts input to the supplied options. Numeric strings are
            converted with ``int()``; Python booleans remain accepted for
            compatibility. Empty, whitespace, or ``None`` uses the configured
            environment default.
        timeout_seconds: Max seconds to wait. Finite numeric strings are parsed
            automatically. ``None`` uses TOPSAILAI_HUMAN_DECISION_TIMEOUT;
            values less than or equal to 0 resolve to an infinite wait.
        default: Fallback answer used on timeout/no-input/cancellation.

    Returns:
        A structured status-bearing dict. Invalid arguments return
        ``invalid_request`` with a machine-readable ``reason`` and normal
        degradation never raises.
    """
    start = time.time()
    asked_at = datetime.fromtimestamp(start).isoformat(timespec="seconds")

    def build_result(status, answer=None, option_index=-1, reason=None):
        elapsed = int(time.time() - start)
        result = {
            "status": status,
            "answer": answer,
            "option_index": option_index,
            "elapsed": elapsed,
            "asked_at": asked_at,
        }
        if reason is not None:
            result["reason"] = reason
        return result

    invalid_reason, eff_allow_free_text, timeout_seconds = _validate_request(
        question, options, allow_free_text, timeout_seconds, default
    )
    if invalid_reason is not None:
        return build_result("invalid_request", default, -1, invalid_reason)
    # Sub-agent guard: do not prompt nested agents.
    if _is_sub_agent_context():
        logger.info("[human_tool] Skipping ask_decision in sub-agent context.")
        return build_result("unavailable", default, -1)

    # Non-interactive / no-stdin degradation.
    with_timeout, plain = _resolve_input_funcs()
    if not _has_usable_input_source(with_timeout, plain):
        logger.info("[human_tool] No usable input source; returning unavailable.")
        return build_result("unavailable", default, -1)

    prompt = _build_prompt(question, options, eff_allow_free_text, default)

    # Try reading input through available channels.
    raw_answer = None
    status = "answered"
    try:
        if with_timeout:
            raw_answer = with_timeout(prompt, timeout_seconds)
        elif plain:
            raw_answer = _read_with_timeout(plain, timeout_seconds, prompt)
        else:
            raw_answer = _read_with_timeout(input, timeout_seconds, prompt)
    except KeyboardInterrupt:
        status = "cancelled"
    except EOFError:
        status = "cancelled"
    except TimeoutError:
        status = "timeout"

    if status != "answered":
        return build_result(status, default, -1)

    if raw_answer is None:
        return build_result("timeout", default, -1)

    ans_raw = _normalize_answer(str(raw_answer))
    if ans_raw.lower() in _CANCEL_WORDS:
        return build_result("cancelled", default, -1)

    # Option validation loop (strict reprompt when free text disabled).
    max_retries = 5
    attempts = 0
    while True:
        try:
            final_answer, opt_idx = _validate_and_resolve(
                ans_raw, options, eff_allow_free_text, default
            )
            break
        except ValueError:
            if not options:
                break
            if attempts >= max_retries:
                # Retry budget exhausted; degrade to accepting current input.
                final_answer, opt_idx = ans_raw, -1
                break
            attempts += 1
            hint = (
                f"Please enter a valid option [0..{len(options)-1}] "
                f"(or '/cancel'): "
            )
            try:
                if with_timeout:
                    retry = with_timeout(hint, timeout_seconds)
                elif plain:
                    retry = _read_with_timeout(plain, timeout_seconds, hint)
                else:
                    retry = _read_with_timeout(input, timeout_seconds, hint)
            except (KeyboardInterrupt, EOFError):
                return build_result("cancelled", default, -1)
            except TimeoutError:
                return build_result("timeout", default, -1)
            if retry is None:
                # Deadline expired during reprompt; degrade to current input.
                final_answer, opt_idx = ans_raw, -1
                break
            ans_raw = _normalize_answer(str(retry))
            if ans_raw.lower() in _CANCEL_WORDS:
                return build_result("cancelled", default, -1)

    # Truncate long answers.
    max_len = _get_max_answer_length()
    if final_answer and len(final_answer) > max_len:
        final_answer = truncate_text(final_answer, max_len)

    return build_result("answered", final_answer, opt_idx)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

PROMPT = """
## human_tool (ask_decision)

Use this tool when the current task becomes **blocked** and you need a
structured human decision to continue. Typical situations:

- Ambiguous requirements that must be clarified before proceeding.
- Missing authorization for a risky operation.
- Multiple mutually-exclusive branches where only one can proceed.
- Confirmation required before committing a destructive action.

### Usage Guidelines

- Provide a clear, concise `question` describing exactly what blocks progress.
- Use `options` to present discrete choices whenever possible. The user can
  select by index number or matching text.
- Pass `allow_free_text` as an integer: `1` accepts custom input; `0` restricts
  input to options. Numeric strings such as `"1"` are converted with `int()`.
  Empty or omitted values use the environment default.
- Enter `/cancel` to cancel and use the configured `default` fallback.
- Pass `default` as a safe fallback when the user does not respond or cancels.
- `timeout_seconds` accepts a number; numeric strings are parsed automatically.
  Values less than or equal to zero wait indefinitely, while omitted values use
  the global configuration.

### Return Value

The tool ALWAYS returns a structured dictionary for normal operation and
request validation:

```json
{
  "status": "answered|timeout|cancelled|unavailable|invalid_request",
  "answer": "string or null",
  "option_index": -1,
  "elapsed": 1,
  "asked_at": "2026-08-14T16:52:00"
}
```

`elapsed` is the integer duration in seconds. `asked_at` is the local,
timezone-naive ISO-8601 start timestamp with second precision.

Interpretation:

- `answered`: User provided a valid response (`answer` holds it).
- `timeout`: No response within the allowed window; `answer` holds `default`.
- `cancelled`: User aborted (Ctrl+C/EOF/`/cancel`); `answer` holds `default`.
- `unavailable`: No usable input channel or a nested sub-agent cannot prompt;
  `answer` holds `default`. Changing input channels or retrying the same call
  from that context will not resolve it.
- `invalid_request`: One or more arguments have invalid types or values;
  `answer` holds `default` and `reason` identifies the invalid argument.

After receiving the result, incorporate the human's decision into your next
reasoning step. If `status` is `timeout`, `cancelled`, or `unavailable`,
proceed using `default` (if set) or explain why you cannot continue. For
`invalid_request`, correct the arguments before retrying.
"""

TOOLS = dict(
    ask_decision=ask_decision,
)

TOOLS_INFO = {
    "ask_decision": {
        "type": "function",
        "function": {
            "name": "ask_decision",
            "description": ask_decision.__doc__,
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    },
                    "allow_free_text": {"type": ["integer", "null"]},
                    "timeout_seconds": {"type": ["number", "null"]},
                    "default": {"type": ["string", "null"]},
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    },
}

FLAG_TOOL_ENABLED = True
