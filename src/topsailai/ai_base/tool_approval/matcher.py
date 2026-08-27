"""
Tool approval rule matching.

Rules describe which tool calls require approval and how to handle them.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from topsailai.utils import env_tool


logger = logging.getLogger(__name__)

_ENV_ENABLED = "TOPSAILAI_TOOL_APPROVAL_ENABLED"
_ENV_RULES = "TOPSAILAI_TOOL_APPROVAL_RULES"
_ENV_DEFAULT_TIMEOUT = "TOPSAILAI_TOOL_APPROVAL_DEFAULT_TIMEOUT"
_ENV_DEFAULT_POLICY = "TOPSAILAI_TOOL_APPROVAL_DEFAULT_POLICY"


@dataclass
class ApprovalRule:
    """A single approval rule."""

    match: str
    mode: str  # require, bypass/skip
    params: list[dict[str, Any]] = field(default_factory=list)
    logic: str = "and"
    timeout: float | None = None
    policy: str | None = None
    priority: int = 0
    name: str | None = None

    def __post_init__(self) -> None:
        mode = self.mode.lower()
        if mode in ("bypass", "skip"):
            self.mode = "bypass"
        else:
            self.mode = mode

        logic = self.logic.lower()
        if logic not in ("and", "or"):
            logger.warning("Unknown approval rule logic '%s', defaulting to 'and'", logic)
            self.logic = "and"

        if self.policy is not None and self.policy not in ("deny", "allow", "ask_again"):
            logger.warning("Unknown approval rule policy '%s', ignoring", self.policy)
            self.policy = None


@dataclass
class ConditionMatch:
    """
    Result of evaluating one parameter condition of a matched rule.

    Used to show the approver which concrete condition made a tool call require
    approval, together with the actual argument value that was inspected.
    """

    param: str | None
    op: str
    expected: Any
    actual: Any
    matched: bool
    error: str | None = None


@dataclass
class RuleMatch:
    """
    A matched rule together with the evaluated parameter conditions.

    Returned by :func:`match_approval_rule_detail` so callers can render both
    the rule identity and the decisive conditions.
    """

    rule: ApprovalRule
    tool_name_matched: bool
    conditions: list[ConditionMatch] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        """Return True when the rule applies to the tool call."""
        if not self.tool_name_matched:
            return False
        if not self.conditions:
            return True
        # Mirror the rule's condition logic so the reported decision matches
        # the boolean semantics of _evaluate_params().
        if getattr(self.rule, "logic", "and") == "or":
            return any(condition.matched for condition in self.conditions)
        return all(condition.matched for condition in self.conditions)


_RULES_CACHE: list[ApprovalRule] | None = None
_CONFIG_ERROR_LOGGED = False


def is_tool_approval_enabled() -> bool:
    """Return True when tool approval is enabled in the environment."""
    return env_tool.is_true(env_tool.EnvReaderInstance.get(_ENV_ENABLED, default="0"))


def _match_pattern(pattern: str, value: str) -> bool:
    """
    Match a value against a pattern containing only '*' wildcards.

    '*' matches any character sequence including the empty sequence.
    Matching is case-sensitive. '?' and bracket expressions are treated as
    literal characters, not as wildcards.
    """
    # Convert the pattern to a regex that only treats '*' as a wildcard.
    # All other regex metacharacters (including '?' and '[') are escaped.
    # We split on literal '*' so that re.escape is applied to each fixed
    # fragment independently, then join with '.*'.
    regex = "^" + ".*".join(re.escape(part) for part in pattern.split("*")) + "$"
    return bool(re.fullmatch(regex, value))


def _evaluate_condition(actual: Any, op: str, expected: Any) -> bool:
    """Evaluate a single parameter condition."""
    op = op.lower()

    if op == "exists":
        return actual is not None

    if op == "eq":
        return actual == expected

    if op == "ne":
        return actual != expected

    if op == "contains":
        if not isinstance(expected, str):
            return False
        return expected in str(actual)

    if op == "not_contains":
        if not isinstance(expected, str):
            return False
        return expected not in str(actual)

    if op == "starts_with":
        if not isinstance(expected, str):
            return False
        return str(actual).startswith(expected)

    if op == "ends_with":
        if not isinstance(expected, str):
            return False
        return str(actual).endswith(expected)

    if op == "regex":
        if not isinstance(expected, str):
            return False
        try:
            return bool(re.search(expected, str(actual)))
        except re.error:
            return False

    if op == "in":
        actual_str = str(actual)
        if isinstance(expected, list):
            return actual_str in (str(item) for item in expected)
        if isinstance(expected, str):
            return actual_str in expected.split(",")
        return False

    if op == "not_in":
        actual_str = str(actual)
        if isinstance(expected, list):
            return actual_str not in (str(item) for item in expected)
        if isinstance(expected, str):
            return actual_str not in expected.split(",")
        return False

    if op in ("gt", "gte", "lt", "lte"):
        try:
            actual_num = float(actual)
            expected_num = float(expected)
        except (TypeError, ValueError):
            return False
        if op == "gt":
            return actual_num > expected_num
        if op == "gte":
            return actual_num >= expected_num
        if op == "lt":
            return actual_num < expected_num
        if op == "lte":
            return actual_num <= expected_num

    return False


def _evaluate_params(tool_args: dict[str, Any], params: list[dict[str, Any]], logic: str) -> bool:
    """Evaluate all parameter conditions for a rule using the given logic."""
    if not params:
        return True

    logic = logic.lower()
    if logic not in ("and", "or"):
        logic = "and"

    for condition in params:
        param = condition.get("param")
        op = condition.get("op", "exists")
        expected = condition.get("value")

        if param is None:
            continue

        actual = tool_args.get(param)
        result = _evaluate_condition(actual, op, expected)

        if logic == "and" and not result:
            return False
        if logic == "or" and result:
            return True

    return logic == "and"


def _evaluate_params_detail(
    tool_args: dict[str, Any],
    params: list[dict[str, Any]],
    logic: str,
) -> tuple[bool, list[ConditionMatch]]:
    """
    Evaluate parameter conditions and report every evaluated condition.

    Unlike :func:`_evaluate_params`, this variant never short-circuits so the
    caller can show which concrete condition decided the match. The boolean
    result is identical to :func:`_evaluate_params`.

    Returns:
        A tuple ``(matched, conditions)`` where *conditions* contains one
        :class:`ConditionMatch` per evaluated condition (conditions without a
        ``param`` key are skipped and therefore not reported).
    """
    if not params:
        return True, []

    logic = logic.lower()
    if logic not in ("and", "or"):
        logic = "and"

    results: list[bool] = []
    conditions: list[ConditionMatch] = []

    for condition in params:
        if not isinstance(condition, dict):
            logger.warning("Skipping invalid approval rule condition: %r", condition)
            results.append(False)
            conditions.append(ConditionMatch(
                param=None,
                op="invalid",
                expected=None,
                actual=None,
                matched=False,
                error=f"not an object: {condition!r}",
            ))
            continue

        param = condition.get("param")
        op = condition.get("op", "exists")
        expected = condition.get("value")

        if param is None:
            continue

        actual = tool_args.get(param)
        result = _evaluate_condition(actual, op, expected)
        results.append(result)
        conditions.append(ConditionMatch(
            param=param,
            op=op,
            expected=expected,
            actual=actual,
            matched=result,
        ))

    matched = all(results) if logic == "and" else any(results)
    return matched, conditions


def _rule_matches(rule: ApprovalRule, tool_name: str, tool_args: dict[str, Any]) -> bool:
    """Return True if the rule matches the tool call."""
    if not _match_pattern(rule.match, tool_name):
        return False

    return _evaluate_params(tool_args, rule.params, rule.logic)


def _parse_rule(item: Any) -> ApprovalRule | None:
    """Parse a single rule dictionary into an ApprovalRule object."""
    if not isinstance(item, dict):
        return None

    match = item.get("match")
    mode = item.get("mode")
    if not isinstance(match, str) or not match:
        return None
    if not isinstance(mode, str) or not mode:
        return None

    name = item.get("name")
    if not isinstance(name, str):
        name = None

    params = item.get("params", [])
    if not isinstance(params, list):
        params = []

    logic = item.get("logic", "and")
    if not isinstance(logic, str):
        logic = "and"

    timeout = item.get("timeout")
    if timeout is not None:
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            timeout = None

    policy = item.get("policy")
    if policy is not None and not isinstance(policy, str):
        policy = None

    priority = item.get("priority", 0)
    try:
        priority = int(priority)
    except (TypeError, ValueError):
        priority = 0

    return ApprovalRule(
        match=match,
        mode=mode,
        params=params,
        logic=logic,
        timeout=timeout,
        policy=policy,
        priority=priority,
        name=name,
    )


def _parse_rules(data: Any, source: str = "<inline>") -> list[ApprovalRule]:
    """Parse a JSON-decoded value into a list of ApprovalRule objects."""
    if not isinstance(data, list):
        logger.critical("Approval rules from %s must be a JSON array", source)
        _disable_approval_due_to_config_error()
        return []

    rules = []
    for item in data:
        rule = _parse_rule(item)
        if rule is not None:
            rules.append(rule)
        else:
            logger.warning("Skipping invalid approval rule from %s: %s", source, item)
    # Keep original order here; final sorting happens in load_approval_rules().
    return rules


def _disable_approval_due_to_config_error() -> None:
    """Disable approval after a configuration error so tools can still run."""
    global _CONFIG_ERROR_LOGGED
    if not _CONFIG_ERROR_LOGGED:
        logger.error("Disabling tool approval due to configuration error")
        _CONFIG_ERROR_LOGGED = True
    os.environ[_ENV_ENABLED] = "0"


def _get_default_rules_path() -> str:
    """Return the default approval rules file path based on TOPSAILAI_WORK_FOLDER."""
    work_folder = os.environ.get("TOPSAILAI_WORK_FOLDER") or ""
    return os.path.join(work_folder, "tool_approval.json")


def _looks_like_file_path(value: str) -> bool:
    """Return True if the value looks like a file path rather than inline JSON."""
    if os.path.isfile(value):
        return True
    # Treat strings containing path separators or ending with .json as paths.
    if "/" in value or "\\" in value or value.lower().endswith(".json"):
        return True
    return False


def _load_file_rules(path: str) -> list[ApprovalRule]:
    """Load rules from a JSON file path."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        logger.critical("Cannot read approval rules file %s: %s", path, exc)
        _disable_approval_due_to_config_error()
        return []
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.critical("Invalid JSON in approval rules file %s: %s", path, exc)
        _disable_approval_due_to_config_error()
        return []
    return _parse_rules(data, source=path)


def _load_inline_rules(raw: str) -> list[ApprovalRule]:
    """Load rules from an inline JSON string."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.critical("Invalid TOPSAILAI_TOOL_APPROVAL_RULES JSON: %s", exc)
        _disable_approval_due_to_config_error()
        return []
    return _parse_rules(data, source="<inline>")


def _load_raw_rules_value(raw: str) -> list[ApprovalRule]:
    """
    Load rules from a single value.

    The value may be either a path to an existing JSON file or a raw JSON
    array literal. Returns a list of parsed rules, or an empty list if the
    value cannot be loaded. Configuration errors are logged at critical level
    and disable approval for the current process.
    """
    if _looks_like_file_path(raw):
        if not os.path.isfile(raw):
            logger.critical("Cannot read approval rules file %s", raw)
            _disable_approval_due_to_config_error()
            return []
        return _load_file_rules(raw)

    return _load_inline_rules(raw)


def load_approval_rules() -> list[ApprovalRule]:
    """Load and cache approval rules from the environment."""
    global _RULES_CACHE

    if _RULES_CACHE is not None:
        return _RULES_CACHE

    raw = env_tool.EnvReaderInstance.get(_ENV_RULES, default="")
    if not raw or not raw.strip():
        raw = _get_default_rules_path()
        if not os.path.isfile(raw):
            _RULES_CACHE = []
            return _RULES_CACHE
        rules = _load_raw_rules_value(raw)
        _RULES_CACHE = rules
        return _RULES_CACHE

    stripped = raw.strip()
    # Backward compatibility: if the whole value is valid JSON, treat it as an
    # inline rule array and do NOT split by ';'. This preserves the previous
    # behavior for JSON literals that may contain semicolons inside strings.
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None

    if data is not None:
        _RULES_CACHE = sorted(_parse_rules(data, source="<inline>"), key=lambda r: r.priority)
        return _RULES_CACHE

    # Multiple rule sources separated by ';'. Each part may be a file
    # path or an inline JSON array literal. Rules from all sources are
    # aggregated and then sorted by priority so the smallest priority wins.
    parts = [part.strip() for part in stripped.split(";") if part.strip()]
    rules: list[ApprovalRule] = []
    for part in parts:
        rules.extend(_load_raw_rules_value(part))

    _RULES_CACHE = sorted(rules, key=lambda r: r.priority)
    return _RULES_CACHE


def clear_approval_rules_cache() -> None:
    """Clear the cached approval rules so they are reloaded on next access."""
    global _RULES_CACHE, _CONFIG_ERROR_LOGGED
    _RULES_CACHE = None
    _CONFIG_ERROR_LOGGED = False


# Alias used by the implementation.
load_rules = load_approval_rules


# Alias used by older code.
clear_rules_cache = clear_approval_rules_cache


def get_approval_rules() -> list[ApprovalRule]:
    """Return the currently loaded approval rules."""
    return load_approval_rules()


def match_approval_rule(tool_name: str | None, tool_args: dict[str, Any] | None) -> ApprovalRule | None:
    """Return the smallest-priority rule that matches the tool call."""
    tool_name = tool_name or ""
    tool_args = tool_args or {}
    rules = sorted(get_approval_rules(), key=lambda r: r.priority)

    for rule in rules:
        if _rule_matches(rule, tool_name, tool_args):
            return rule
    return None


def match_approval_rule_detail(
    tool_name: str | None,
    tool_args: dict[str, Any] | None,
) -> RuleMatch | None:
    """
    Return the smallest-priority matching rule together with condition details.

    The selection semantics are identical to :func:`match_approval_rule`: rules
    are ordered by ascending priority and the first rule whose tool-name pattern
    and parameter conditions match wins. The returned :class:`RuleMatch` also
    carries one :class:`ConditionMatch` per evaluated condition so consumers can
    inspect which concrete value triggered approval.
    """
    tool_name = tool_name or ""
    tool_args = tool_args or {}
    rules = sorted(get_approval_rules(), key=lambda r: r.priority)

    for rule in rules:
        tool_name_matched = _match_pattern(rule.match, tool_name)
        if not tool_name_matched:
            continue
        matched, conditions = _evaluate_params_detail(tool_args, rule.params, rule.logic)
        if matched:
            return RuleMatch(rule=rule, tool_name_matched=True, conditions=conditions)
    return None


# Backward-compatible alias.
find_matching_rule = match_approval_rule
