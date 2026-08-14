"""
Thought/Final-Answer abnormal line-ratio detection.

When an LLM response is finally classified as ``thought`` (or ``final`` /
``final_answer``) and more than a configurable proportion of its non-empty
lines contain a configurable substring, the response is considered potentially
malformed. For a ``thought``, a critical user-role observation is appended to
warn the model. For a ``final``/``final_answer``, the step is converted back to
a ``thought`` (the task is NOT terminated) and the same critical observation is
appended, giving the model another chance to produce a well-formed step.

Configuration is provided through environment variables:

- ``TOPSAILAI_THOUGHT_LINE_PATTERN_ENABLED`` (master switch, default off)
- ``TOPSAILAI_THOUGHT_LINE_PATTERN_RULES`` (JSON list of rule dicts)

Each rule supports the following keys:

- ``pattern`` (required): substring that a non-empty line must contain.
- ``line_ratio`` (required, 0 < value <= 1): triggering ratio. A rule fires
  when ``matched / total`` is STRICTLY greater than this value.
- ``min_lines`` (optional, default 5): minimum number of non-empty lines
  required before the rule is evaluated (avoids false positives on short text).
- ``case_sensitive`` (optional, default true): whether substring matching is
  case-sensitive.
- ``enabled`` (optional, default true): whether the rule is active.
- ``dedup`` (optional, default true): when true, the rule emits a warning only
  once per sustained over-threshold period and re-arms after the ratio falls
  back to or below the threshold.
- ``agent_role`` (optional, default ``*``): ``manager``, ``worker``, or ``*``.
  Unknown roles are treated as ``*``.
- ``warning`` (optional): custom warning template. Supported placeholders:
  ``{pattern}``, ``{matched}``, ``{total}``, ``{actual_ratio}``,
  ``{line_ratio}``, ``{agent_role}``, ``{step_type}``.

Multiple rules use OR semantics: any rule that fires contributes to a single
merged critical observation. Only assistant ``thought``/``final`` responses are
scanned; injected observations are never scanned again, preventing recursion.

The whole mechanism is advisory only: configuration errors or evaluation
failures are logged and swallowed, never interrupting agent execution.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from topsailai.ai_base.constants import (
    AGENT_ROLE_VALUES,
    MSG_KEY_RAW_TEXT,
    MSG_KEY_STEP_NAME,
    ROLE_USER,
    STEP_NAME_OBSERVATION,
)
from topsailai.utils import env_tool

logger = logging.getLogger(__name__)

# Environment variable holding the master switch.
ENV_THOUGHT_LINE_PATTERN_ENABLED = "TOPSAILAI_THOUGHT_LINE_PATTERN_ENABLED"
# Environment variable holding the JSON list of detection rules.
ENV_THOUGHT_LINE_PATTERN_RULES = "TOPSAILAI_THOUGHT_LINE_PATTERN_RULES"

# Wildcard value used for role matching.
_WILDCARD = "*"

# Default minimum number of non-empty lines before a rule is evaluated.
DEFAULT_MIN_LINES = 5

# Attribute name used to store per-agent dedup trigger state on ToolStat.
_TRIGGER_STATE_ATTR = "_thought_line_pattern_triggered"

# Placeholder keys supported by custom warning templates.
_PLACEHOLDER_KEYS = (
    "pattern",
    "matched",
    "total",
    "actual_ratio",
    "line_ratio",
    "agent_role",
    "step_type",
)


@dataclass
class ThoughtLinePatternRule:
    """A single thought/final-answer abnormal line-ratio detection rule."""

    pattern: str = ""
    line_ratio: float = 0.0
    min_lines: int = DEFAULT_MIN_LINES
    case_sensitive: bool = True
    enabled: bool = True
    dedup: bool = True
    agent_role: str = _WILDCARD
    warning: str = ""


def _as_int(value: Any, default: int) -> int:
    """Coerce a value to an integer, falling back to the provided default."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    """Coerce a value to a float, falling back to the provided default."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value: Any, default: bool) -> bool:
    """Parse a boolean-like value, falling back to the provided default."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "on", "enabled"):
            return True
        if normalized in ("0", "false", "no", "off", "disabled", ""):
            return False
        return default
    if value is None:
        return default
    return bool(value)


def _normalize_role(value: Any) -> str:
    """Normalize an agent_role value; unknown roles become the wildcard."""
    role = str(value).strip() if value is not None else _WILDCARD
    if role in AGENT_ROLE_VALUES or role == _WILDCARD:
        return role
    logger.warning(
        "unknown agent_role '%s' in thought-line-pattern rule, treating as '*'",
        role,
    )
    return _WILDCARD


def _get_rules_env_value() -> Optional[str]:
    """Read the raw detection rules from the environment.

    Wrapped in a module-level helper so tests can patch this function instead
    of the shared ``env_tool.EnvReaderInstance`` singleton.
    """
    return env_tool.EnvReaderInstance.get(ENV_THOUGHT_LINE_PATTERN_RULES)


def is_enabled() -> bool:
    """Return whether the thought-line-pattern detection is enabled.

    Controlled by ``TOPSAILAI_THOUGHT_LINE_PATTERN_ENABLED``; defaults to off.
    """
    try:
        return env_tool.EnvReaderInstance.check_bool(
            ENV_THOUGHT_LINE_PATTERN_ENABLED, False
        )
    except Exception:
        logger.exception("failed to read %s, assuming disabled", ENV_THOUGHT_LINE_PATTERN_ENABLED)
        return False


def parse_rules(env_value: Optional[str] = None) -> List[ThoughtLinePatternRule]:
    """Parse detection rules from the environment variable.

    Args:
        env_value: Optional raw JSON string. When None, the value is read from
            ``TOPSAILAI_THOUGHT_LINE_PATTERN_RULES``.

    Returns:
        A list of validated :class:`ThoughtLinePatternRule`. Invalid JSON or a
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
            "invalid JSON for %s, thought-line-pattern disabled: %s",
            ENV_THOUGHT_LINE_PATTERN_RULES,
            exc,
        )
        return []

    if not isinstance(raw, list):
        logger.warning(
            "%s must be a JSON list, thought-line-pattern disabled",
            ENV_THOUGHT_LINE_PATTERN_RULES,
        )
        return []

    rules: List[ThoughtLinePatternRule] = []
    for index, item in enumerate(raw):
        rule = _parse_rule(item, index)
        if rule is not None:
            rules.append(rule)
    return rules


def _parse_rule(item: Any, index: int) -> Optional[ThoughtLinePatternRule]:
    """Parse and validate a single rule dict, or return None to skip it."""
    if not isinstance(item, dict):
        logger.warning(
            "skip non-dict thought-line-pattern rule at index %d", index
        )
        return None

    pattern = str(item.get("pattern", "")).strip()
    if not pattern:
        logger.warning(
            "skip thought-line-pattern rule at index %d: missing pattern", index
        )
        return None

    line_ratio = _as_float(item.get("line_ratio"), 0.0)
    if not (0.0 < line_ratio <= 1.0):
        logger.warning(
            "skip thought-line-pattern rule at index %d: line_ratio must be in (0, 1]",
            index,
        )
        return None

    min_lines = _as_int(item.get("min_lines"), DEFAULT_MIN_LINES)
    if min_lines < 0:
        min_lines = DEFAULT_MIN_LINES

    return ThoughtLinePatternRule(
        pattern=pattern,
        line_ratio=line_ratio,
        min_lines=min_lines,
        case_sensitive=_parse_bool(item.get("case_sensitive"), True),
        enabled=_parse_bool(item.get("enabled"), True),
        dedup=_parse_bool(item.get("dedup"), True),
        agent_role=_normalize_role(item.get("agent_role")),
        warning=str(item.get("warning", "")).strip(),
    )


def _split_non_empty_lines(text: str) -> List[str]:
    """Split text into stripped non-empty lines.

    Empty lines and whitespace-only lines are excluded from both the numerator
    and denominator of the ratio calculation.
    """
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _compute_match(
    text: str, rule: ThoughtLinePatternRule
) -> Optional[Tuple[ThoughtLinePatternRule, int, int]]:
    """Compute whether a rule fires for the given text.

    Returns ``(rule, matched, total)`` when the ratio of non-empty lines
    containing ``pattern`` is strictly greater than ``line_ratio`` and the
    total non-empty line count meets ``min_lines``. Otherwise returns None.
    """
    non_empty = _split_non_empty_lines(text)
    total = len(non_empty)
    if total < rule.min_lines:
        return None

    needle = rule.pattern if rule.case_sensitive else rule.pattern.lower()
    matched = 0
    for line in non_empty:
        haystack = line if rule.case_sensitive else line.lower()
        if needle in haystack:
            matched += 1

    if total > 0 and matched / total > rule.line_ratio:
        return rule, matched, total
    return None


def _rule_key(rule: ThoughtLinePatternRule) -> Tuple[str, float, int, bool, str]:
    """Return a stable identity key for a rule used for dedup state."""
    return (
        rule.pattern,
        rule.line_ratio,
        rule.min_lines,
        rule.case_sensitive,
        rule.agent_role,
    )


def _get_trigger_state(stat: Any) -> Dict[Tuple[str, float, int, bool, str], bool]:
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


def render_warning(template: str, mapping: Dict[str, Any]) -> str:
    """Render a warning template by replacing supported placeholders.

    Placeholders are replaced literally, so braces that are not known
    placeholders are preserved unchanged.
    """
    result = template
    for key in _PLACEHOLDER_KEYS:
        result = result.replace("{" + key + "}", str(mapping.get(key, "")))
    return result


def _build_warning(
    hits: List[Tuple[ThoughtLinePatternRule, int, int]],
    agent_role: str,
    step_type: str,
) -> str:
    """Build a single merged critical observation text for all firing rules."""
    upper_type = step_type.upper()
    parts = [
        f"CRITICAL-SYSTEM-ALERT: THE PREVIOUS {upper_type} MAY BE MALFORMED",
        "",
        f"Suspicious line patterns were detected in the previous {step_type} response:",
    ]
    for rule, matched, total in hits:
        if rule.warning:
            rendered = render_warning(
                rule.warning,
                {
                    "pattern": rule.pattern,
                    "matched": matched,
                    "total": total,
                    "actual_ratio": round(matched / total, 6),
                    "line_ratio": rule.line_ratio,
                    "agent_role": agent_role,
                    "step_type": step_type,
                },
            )
            indented = rendered.replace("\n", "\n  ")
            parts.append(f"- {indented}")
        else:
            parts.append(
                f'- pattern="{rule.pattern}", matched={matched}/{total}, '
                f'ratio={(matched / total) * 100:.1f}%, '
                f'threshold={rule.line_ratio * 100:.1f}%'
            )
    parts.extend(
        [
            "",
            "The previous response may be malformed, repetitive, or unrecognizable "
            "by the agent response parser.",
            "",
            "Stop and question your previous response:",
            f"- Is it a valid {step_type}?",
            "- Did you accidentally emit an unsupported model-specific format?",
            "- Does the response follow the required TopsailAI step schema?",
            "- Should you produce a concrete action or a concise final_answer instead?",
            "",
            "Do not repeat the malformed content. Re-evaluate the task and return a "
            "valid next step.",
        ]
    )
    return "\n".join(parts)

def _inject_critical(agent: Any, warning_text: str) -> None:
    """Inject a critical observation into the Agent2LLM context.

    When an agent object is available, the warning is appended directly via
    ``add_user_message`` as a structured observation content dict. Otherwise it
    falls back to the file-based runtime message source. Failures are logged and
    swallowed (advisory only).
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
            logger.exception("failed to inject thought-line-pattern warning via agent")

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
        logger.exception(
            "failed to inject thought-line-pattern warning via file source"
        )


def evaluate_and_maybe_inject(
    raw_text: str,
    step_type: str = "thought",
    on_warning=None,
) -> bool:
    """Evaluate a thought/final response and inject a critical observation.

    Args:
        raw_text: The raw text of the assistant thought/final step.
        step_type: Either ``"thought"`` or ``"final_answer"``, used for the
            warning text and logging.
        on_warning: Optional callable invoked with the exact merged warning
            text just before it is injected into the context. This lets the
            caller surface the same message through another channel (for
            example printing it via :mod:`utils.print_tool`) without
            duplicating the warning content. It is only called when an actual
            injection happens (not suppressed by dedup).

    Returns:
        True when at least one rule matches, including a sustained match whose
        warning is suppressed by dedup. Callers use this to decide whether a
        ``final``/``final_answer`` step should be converted back to a
        ``thought``. Returns False when no rule matches or detection is
        disabled. Warning injection and callbacks occur only for non-suppressed
        matches.

    Advisory only: any failure is logged and swallowed.
    """
    if not is_enabled():
        return False
    try:
        rules = parse_rules()
        if not rules:
            return False

        from topsailai.utils.thread_local_tool import get_agent_object
        from topsailai.context.tool_stat import get_agent_tool_stat
        from topsailai.ai_base.agent_types.init import get_agent_role

        agent = get_agent_object()
        agent_role = getattr(agent, "agent_role", None) or get_agent_role()
        stat = get_agent_tool_stat(agent)
        trigger_state = _get_trigger_state(stat)

        matched_any = False
        hits: List[Tuple[ThoughtLinePatternRule, int, int]] = []
        for rule in rules:
            if not rule.enabled:
                continue
            if rule.agent_role != _WILDCARD and rule.agent_role != agent_role:
                continue
            key = _rule_key(rule)
            match = _compute_match(raw_text, rule)
            if match is None:
                # Below threshold: re-arm the rule for future detections.
                trigger_state[key] = False
                continue
            matched_any = True
            if rule.dedup and trigger_state.get(key):
                # Keep the detection result but suppress repeated warnings.
                continue
            trigger_state[key] = True
            hits.append(match)

        if not hits:
            return matched_any

        warning_text = _build_warning(hits, agent_role, step_type)
        logger.warning(
            "thought-line-pattern warning triggered: step=%s hits=%d role=%s",
            step_type,
            len(hits),
            agent_role,
        )

        try:
            from topsailai.events import record_event

            record_event(
                "thought.line_pattern.warning",
                {
                    "step_type": step_type,
                    "agent_role": agent_role,
                    "hit_count": len(hits),
                    "patterns": [r.pattern for r, _, _ in hits],
                    "warning": warning_text,
                },
            )
        except Exception:
            logger.exception("failed to record thought-line-pattern warning event")

        if on_warning is not None:
            try:
                on_warning(warning_text)
            except Exception:
                logger.exception(
                    "thought-line-pattern on_warning callback failed (advisory only)"
                )

        _inject_critical(agent, warning_text)
        return True
    except Exception:
        logger.exception(
            "thought-line-pattern evaluation failed (advisory only)"
        )
        return False
