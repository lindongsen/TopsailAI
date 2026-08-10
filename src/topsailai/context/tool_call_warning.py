"""
Repeated tool-call warning detection.

This module emits a user-role warning message when a specific tool is called
more than a configured number of times within a configured time window. It is
advisory only: configuration errors or evaluation failures must never interrupt
tool execution.

Configuration is provided through the environment variable
``TOPSAILAI_TOOL_CALL_WARNING_RULES`` as a JSON list of rule dicts. Each rule
supports the following keys:

- ``agent_role`` (optional, default ``*``): ``manager``, ``worker``, or ``*``.
  Unknown roles are treated as ``*``.
- ``tool_call`` (required): exact tool name or ``*``.
- ``max_calls`` (required, > 0): maximum allowed call count within the window.
  A warning triggers when the count is strictly greater than this value.
- ``window_seconds`` (optional, default 60): rolling time window in seconds.
  Non-positive values fall back to 60.
- ``warning`` (required): warning template injected into the agent context.
- ``enabled`` (optional, default true): whether the rule is active.
- ``dedup`` (optional, default true): when true, the rule warns only once per
  sustained over-limit period and re-arms after the count falls back to or
  below ``max_calls``.

Supported warning-template placeholders: ``{tool_call}``, ``{count}``,
``{agent_role}``, ``{window_seconds}``, ``{max_calls}``.

Rule matching uses declared order with first-match-wins precedence. A rule
matches when both the role (exact or ``*``) and the tool (exact or ``*``)
match the current agent role and called tool name.
"""

from __future__ import annotations

import functools
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from topsailai.ai_base.constants import (
    AGENT_ROLE_VALUES,
    DEFAULT_AGENT_ROLE,
    MSG_KEY_RAW_TEXT,
    MSG_KEY_STEP_NAME,
    ROLE_USER,
    STEP_NAME_OBSERVATION,
)
from topsailai.utils import env_tool

logger = logging.getLogger(__name__)

# Environment variable that holds the JSON list of warning rules.
ENV_TOOL_CALL_WARNING_RULES = "TOPSAILAI_TOOL_CALL_WARNING_RULES"

# Wildcard value used for role and tool matching.
_WILDCARD = "*"

# Default rolling time window in seconds.
DEFAULT_WINDOW_SECONDS = 60

# Attribute name used to store per-agent dedup trigger state on ToolStat.
_TRIGGER_STATE_ATTR = "_tool_call_warning_triggered"

# Supported warning-template placeholders.
_PLACEHOLDER_KEYS = (
    "tool_call",
    "count",
    "agent_role",
    "window_seconds",
    "max_calls",
)


@dataclass
class ToolCallWarningRule:
    """A single repeated tool-call warning rule."""

    agent_role: str = _WILDCARD
    tool_call: str = _WILDCARD
    max_calls: int = 0
    window_seconds: int = DEFAULT_WINDOW_SECONDS
    warning: str = ""
    enabled: bool = True
    dedup: bool = True


def _as_bool(value: Any, default: bool) -> bool:
    """Coerce a value to a boolean using the project's truthy convention."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return _parse_bool(value, default)


def _parse_bool(value: Any, default: bool) -> bool:
    """Parse a boolean-like value, falling back to the provided default."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on", "enabled"):
            return True
        if normalized in ("0", "false", "no", "off", "disabled", ""):
            return False
        return default
    return bool(value) if value is not None else default
def _as_int(value: Any, default: int) -> int:
    """Coerce a value to an integer, falling back to the provided default."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_role(value: Any) -> str:
    """Normalize an agent_role value; unknown roles become the wildcard."""
    role = str(value).strip() if value is not None else _WILDCARD
    if role in AGENT_ROLE_VALUES or role == _WILDCARD:
        return role
    logger.warning("unknown agent_role '%s' in tool-call warning rule, treating as '*'", role)
    return _WILDCARD


def _get_rules_env_value() -> Optional[str]:
    """Read the raw tool-call warning rules from the environment.

    Wrapped in a module-level helper so tests can patch this function instead
    of the shared ``env_tool.EnvReaderInstance`` singleton, which is also used
    by unrelated subsystems (e.g. the events config).
    """
    return env_tool.EnvReaderInstance.get(ENV_TOOL_CALL_WARNING_RULES)


def parse_rules(env_value: Optional[str] = None) -> List[ToolCallWarningRule]:
    """Parse warning rules from the environment variable.

    Args:
        env_value: Optional raw JSON string. When None, the value is read from
            ``TOPSAILAI_TOOL_CALL_WARNING_RULES``.

    Returns:
        A list of validated :class:`ToolCallWarningRule`. Invalid JSON or a
        non-list payload disables the feature (empty list). Invalid individual
        rules are skipped with a warning. This function never raises.
    """
    if env_value is None:
        env_value = _get_rules_env_value()

    if not env_value or not str(env_value).strip():
        return []

    try:
        raw = json.loads(str(env_value))
    except (TypeError, ValueError) as exc:
        logger.warning(
            "invalid JSON for %s, tool-call warning disabled: %s",
            ENV_TOOL_CALL_WARNING_RULES,
            exc,
        )
        return []

    if not isinstance(raw, list):
        logger.warning(
            "%s must be a JSON list, tool-call warning disabled",
            ENV_TOOL_CALL_WARNING_RULES,
        )
        return []

    rules: List[ToolCallWarningRule] = []
    for index, item in enumerate(raw):
        rule = _parse_rule(item, index)
        if rule is not None:
            rules.append(rule)
    return rules


def _parse_rule(item: Any, index: int) -> Optional[ToolCallWarningRule]:
    """Parse and validate a single rule dict, or return None to skip it."""
    if not isinstance(item, dict):
        logger.warning("skip non-dict tool-call warning rule at index %d", index)
        return None

    tool_call = str(item.get("tool_call", "")).strip()
    if not tool_call:
        logger.warning("skip tool-call warning rule at index %d: missing tool_call", index)
        return None

    max_calls = _as_int(item.get("max_calls"), 0)
    if max_calls <= 0:
        logger.warning(
            "skip tool-call warning rule at index %d: max_calls must be > 0", index
        )
        return None

    warning = str(item.get("warning", "")).strip()
    if not warning:
        logger.warning("skip tool-call warning rule at index %d: missing warning", index)
        return None

    window_seconds = _as_int(item.get("window_seconds"), DEFAULT_WINDOW_SECONDS)
    if window_seconds <= 0:
        logger.warning(
            "invalid window_seconds %r at index %d, falling back to %d",
            item.get("window_seconds"),
            index,
            DEFAULT_WINDOW_SECONDS,
        )
        window_seconds = DEFAULT_WINDOW_SECONDS

    return ToolCallWarningRule(
        agent_role=_normalize_role(item.get("agent_role")),
        tool_call=tool_call,
        max_calls=max_calls,
        window_seconds=window_seconds,
        warning=warning,
        enabled=_parse_bool(item.get("enabled"), True),
        dedup=_parse_bool(item.get("dedup"), True),
    )


def match_rule(
    rules: List[ToolCallWarningRule],
    agent_role: str,
    tool_name: str,
) -> Optional[ToolCallWarningRule]:
    """Return the first matching rule using declared order (first-match-wins).

    A rule matches when it is enabled and both the role (exact or ``*``) and
    the tool (exact or ``*``) match the current agent role and tool name.

    Args:
        rules: Parsed warning rules.
        agent_role: The current agent role.
        tool_name: The called tool name.

    Returns:
        The first matching rule, or None when no rule matches.
    """
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.agent_role != _WILDCARD and rule.agent_role != agent_role:
            continue
        if rule.tool_call != _WILDCARD and rule.tool_call != tool_name:
            continue
        return rule
    return None


def render_warning(
    template: str,
    tool_call: str = "",
    count: int = 0,
    agent_role: str = "",
    window_seconds: int = 0,
    max_calls: int = 0,
) -> str:
    """Render a warning template by replacing supported placeholders.

    Placeholders are replaced literally, so templates containing braces that
    are not placeholders are preserved unchanged.

    Args:
        template: The warning template.
        tool_call: Called tool name.
        count: Number of calls within the window.
        agent_role: Current agent role.
        window_seconds: Configured time window.
        max_calls: Configured maximum call count.

    Returns:
        The rendered warning string.
    """
    mapping = {
        "tool_call": str(tool_call),
        "count": str(count),
        "agent_role": str(agent_role),
        "window_seconds": str(window_seconds),
        "max_calls": str(max_calls),
    }
    result = template
    for key in _PLACEHOLDER_KEYS:
        result = result.replace("{" + key + "}", mapping[key])
    return result


def count_calls_in_window(
    stat: Any,
    tool_name: str,
    window_seconds: int,
    now: Optional[datetime] = None,
) -> int:
    """Count calls to a tool within a rolling time window.

    Args:
        stat: A ``ToolStat`` instance (or any object exposing ``get_by_tool``).
        tool_name: The tool name to count.
        window_seconds: Length of the rolling window in seconds.
        now: Reference time; defaults to the current time.

    Returns:
        The number of recorded calls to ``tool_name`` within the window.
    """
    if now is None:
        now = datetime.now()
    start = now - timedelta(seconds=window_seconds)
    count = 0
    for call in stat.get_by_tool(tool_name):
        try:
            call_time = datetime.fromisoformat(call["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= call_time <= now:
            count += 1
    return count


def evaluate_tool_call(
    stat: Any,
    rules: List[ToolCallWarningRule],
    agent_role: str,
    tool_name: str,
    now: Optional[datetime] = None,
) -> Optional[Tuple[ToolCallWarningRule, int]]:
    """Evaluate whether a tool call should trigger a warning.

    Args:
        stat: A ``ToolStat`` instance used for counting.
        rules: Parsed warning rules.
        agent_role: The current agent role.
        tool_name: The called tool name.
        now: Reference time; defaults to the current time.

    Returns:
        A ``(rule, count)`` tuple when the call count exceeds the matched
        rule's ``max_calls``, otherwise None.
    """
    if not rules:
        return None
    rule = match_rule(rules, agent_role, tool_name)
    if rule is None:
        return None
    count = count_calls_in_window(stat, tool_name, rule.window_seconds, now)
    if count > rule.max_calls:
        return rule, count
    return None


def _rule_key(rule: ToolCallWarningRule) -> Tuple[str, str, int, int]:
    """Return a stable identity key for a rule used for dedup state."""
    return (rule.agent_role, rule.tool_call, rule.max_calls, rule.window_seconds)


def _get_trigger_state(stat: Any) -> Dict[Tuple[str, str, int, int], bool]:
    """Get or create the per-agent dedup trigger state dict on a ToolStat."""
    state = getattr(stat, _TRIGGER_STATE_ATTR, None)
    if state is None:
        state = {}
        try:
            setattr(stat, _TRIGGER_STATE_ATTR, state)
        except Exception:
            # Some stat-like objects may be read-only; fall back to a local dict.
            state = {}
    return state


def _inject_warning(agent: Any, warning_text: str) -> None:
    """Inject a warning into the Agent2LLM context as a user-role message.

    When an agent object is available, the warning is appended directly via
    ``add_user_message`` as a structured observation content dict. Otherwise
    it falls back to the file-based runtime message source. Failures are
    logged and swallowed (advisory only).
    """
    if agent is not None:
        try:
            content = {
                MSG_KEY_STEP_NAME: STEP_NAME_OBSERVATION,
                MSG_KEY_RAW_TEXT: warning_text,
            }
            agent.add_user_message(content, need_print=False)
            return
        except Exception:
            logger.exception("failed to inject tool-call warning via agent")

    try:
        from topsailai.workspace.agent.runtime_message_sources.file import (
            get_default_inject_message_file_path,
            write_message,
        )

        write_message(
            get_default_inject_message_file_path(),
            warning_text,
            role=ROLE_USER,
            step_name=STEP_NAME_OBSERVATION,
        )
    except Exception:
        logger.exception("failed to inject tool-call warning via file source")
def _maybe_emit_warning(tool_name: str, tool_args: Any) -> None:
    """Evaluate and emit a tool-call warning after a tool has been recorded.

    This is advisory only: any failure is logged and swallowed so tool
    execution is never interrupted.
    """
    try:
        rules = parse_rules()
        if not rules:
            return

        from topsailai.utils.thread_local_tool import get_agent_object
        from topsailai.context.tool_stat import get_agent_tool_stat
        from topsailai.ai_base.agent_types.init import get_agent_role

        agent = get_agent_object()
        agent_role = getattr(agent, "agent_role", None) or get_agent_role()
        stat = get_agent_tool_stat(agent)
        now = datetime.now()

        rule = match_rule(rules, agent_role, tool_name)
        if rule is None:
            return

        count = count_calls_in_window(stat, tool_name, rule.window_seconds, now)
        key = _rule_key(rule)
        trigger_state = _get_trigger_state(stat)

        if count <= rule.max_calls:
            # Re-arm: the count has fallen back to or below the threshold.
            trigger_state[key] = False
            return

        if rule.dedup and trigger_state.get(key):
            # Already warned during this sustained over-limit period.
            return

        trigger_state[key] = True

        warning_text = render_warning(
            rule.warning,
            tool_call=tool_name,
            count=count,
            agent_role=agent_role,
            window_seconds=rule.window_seconds,
            max_calls=rule.max_calls,
        )

        logger.warning(
            "tool-call warning triggered: tool=%s count=%d role=%s rule=%s",
            tool_name,
            count,
            agent_role,
            key,
        )

        try:
            from topsailai.events import record_event

            record_event(
                "tool_call.warning",
                {
                    "tool_call": tool_name,
                    "tool_args": tool_args,
                    "count": count,
                    "agent_role": agent_role,
                    "max_calls": rule.max_calls,
                    "window_seconds": rule.window_seconds,
                    "warning": warning_text,
                },
            )
        except Exception:
            logger.exception("failed to record tool-call warning event")

        _inject_warning(agent, warning_text)
    except Exception:
        logger.exception("tool-call warning evaluation failed (advisory only)")


def detect_tool_call_warning(exec_tool_func):
    """Decorator that evaluates a repeated tool-call warning after execution.

    The wrapped function is expected to record the tool call (e.g. via
    ``tool_stat.record_tool_call``) before returning. Because this decorator
    wraps the function, it runs after the call has been recorded, so the
    triggering invocation is included in the window count.

    The original result is always returned unchanged; the warning is advisory.
    """

    @functools.wraps(exec_tool_func)
    def wrapper(tool_func, args, tool_name: Optional[str] = None):
        result = exec_tool_func(tool_func, args, tool_name=tool_name)
        effective_tool_name = tool_name or getattr(tool_func, "__name__", None)
        if effective_tool_name:
            try:
                _maybe_emit_warning(effective_tool_name, args)
            except Exception:
                logger.exception("tool-call warning evaluation failed (advisory only)")
        return result

    return wrapper