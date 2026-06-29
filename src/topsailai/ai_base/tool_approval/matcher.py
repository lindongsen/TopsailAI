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
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        return False

    if op == "not_contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected not in actual
        return False

    if op == "starts_with":
        if isinstance(actual, str) and isinstance(expected, str):
            return actual.startswith(expected)
        return False

    if op == "ends_with":
        if isinstance(actual, str) and isinstance(expected, str):
            return actual.endswith(expected)
        return False

    if op == "regex":
        if isinstance(actual, str) and isinstance(expected, str):
            try:
                return bool(re.search(expected, actual))
            except re.error:
                return False
        return False

    if op == "in":
        if isinstance(expected, list):
            return actual in expected
        if isinstance(expected, str):
            return str(actual) in expected.split(",")
        return False

    if op == "not_in":
        if isinstance(expected, list):
            return actual not in expected
        if isinstance(expected, str):
            return str(actual) not in expected.split(",")
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


def _parse_rules(data: Any) -> list[ApprovalRule]:
    """Parse a JSON-decoded value into a list of ApprovalRule objects."""
    if not isinstance(data, list):
        logger.warning("TOPSAILAI_TOOL_APPROVAL_RULES must be a JSON array")
        _disable_approval_due_to_config_error()
        return []

    rules = []
    for item in data:
        rule = _parse_rule(item)
        if rule is not None:
            rules.append(rule)
        else:
            logger.warning("Skipping invalid approval rule: %s", item)

    # Smaller priority values are evaluated first.
    return sorted(rules, key=lambda r: r.priority)


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

    # If the value points to an existing file, read the file content.
    if os.path.isfile(raw):
        try:
            with open(raw, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            logger.error("Cannot read approval rules file %s: %s", raw, exc)
            _disable_approval_due_to_config_error()
            _RULES_CACHE = []
            return _RULES_CACHE

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Invalid TOPSAILAI_TOOL_APPROVAL_RULES JSON: %s", exc)
        _disable_approval_due_to_config_error()
        _RULES_CACHE = []
        return _RULES_CACHE

    rules = _parse_rules(data)
    _RULES_CACHE = rules
    return rules


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


# Backward-compatible alias.
find_matching_rule = match_approval_rule
