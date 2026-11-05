"""Conditional startup-observation retention policy. Author: DawsonLin."""

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Callable, Mapping

from topsailai.utils import json_tool, message_tool


@dataclass(frozen=True)
class RecoveryConfig:
    """Immutable per-runtime policy; explicit construction overrides environment."""

    enabled: bool = True
    ratio: float = 0.7

    def __post_init__(self):
        """Reject invalid explicit configuration before any context mutation."""
        if type(self.enabled) is not bool:
            raise ValueError("recovery enabled must be boolean")
        if type(self.ratio) not in (int, float) or not math.isfinite(self.ratio) or not 0 < self.ratio < 1:
            raise ValueError("recovery ratio must be finite and strictly between 0 and 1")


def load_recovery_config(values: Mapping, log) -> RecoveryConfig:
    """Parse external configuration once at the runtime construction boundary."""
    enabled = str(values.get("TOPSAILAI_CONTEXT_SUMMARY_OBSERVATION_RECOVERY_ENABLED", "1")).lower().strip()
    if enabled not in ("1", "true", "yes", "on", "enabled"):
        return RecoveryConfig(False)
    raw = values.get("TOPSAILAI_CONTEXT_SUMMARY_RECOVERY_RATIO", "0.7")
    try:
        return RecoveryConfig(True, float(raw))
    except (TypeError, ValueError, OverflowError):
        log.warning("Invalid summary recovery ratio %r; using 0.7", raw)
        return RecoveryConfig(True)


def message_key(message) -> str:
    """Canonicalize once for set membership across raw and decoded messages."""
    return json.dumps(message_tool._normalize_message_value(message), sort_keys=True, default=str, ensure_ascii=False)


def startup_observations(messages: list) -> tuple:
    """Identify only the contiguous opening observation block after systems."""
    result = []
    started = False
    for message in messages:
        value = json_tool.safe_json_load(message)
        if not isinstance(value, dict):
            break
        if not started and value.get("role") == "system":
            continue
        content = json_tool.safe_json_load(value.get("content"))
        if value.get("role") != "user" or not isinstance(content, dict) or content.get("step_name") != "observation":
            break
        started = True
        result.append(message)
    return tuple(result)


def protected_messages(messages: list) -> list:
    """Protect systems, explicit tasks, and the latest genuine user input."""
    result = []
    opening = startup_observations(messages)
    opening_end = len(opening)
    for message in messages:
        value = json_tool.safe_json_load(message)
        if not isinstance(value, dict) or value.get("role") != "system":
            break
        opening_end += 1
    latest = None
    for index, message in enumerate(messages):
        value = json_tool.safe_json_load(message)
        if not isinstance(value, dict):
            continue
        content = json_tool.safe_json_load(value.get("content"))
        task = isinstance(content, dict) and content.get("step_name") == "task"
        if (value.get("role") == "system" or task
                or (value.get("role") == "user" and index >= opening_end)):
            result.append(message)
        if value.get("role") == "user":
            latest = message
    if latest is not None:
        result.append(latest)
    return result


def unique(messages: list) -> tuple:
    """Deduplicate retained values in stable order with linear membership work."""
    seen = set()
    result = []
    for message in messages:
        key = message_key(message)
        if key not in seen:
            seen.add(key)
            result.append(message)
    return tuple(result)


def fingerprint(session_id: str, session: list, runtime: list) -> str:
    """Bound same-state bookkeeping to one content digest per runtime."""
    digest = hashlib.sha256()
    for value in (session_id, session, runtime):
        digest.update(message_key(value).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class RecoveryPlan:
    """One operation's exact selected survivors and measured budget evidence."""

    removed_keys: frozenset
    session_keep: tuple
    runtime_keep: tuple
    budget: int
    normal_tokens: int
    candidate_tokens: int
    reserve: int
    expected_state: str = ""


def select_recovery(
    config: RecoveryConfig, session: list, runtime: list,
    normal: list, threshold: int, safe_limit: int | None, reserve: int,
    count: Callable, layer: str, runtime_normal: list | None = None,
) -> RecoveryPlan | None:
    """Choose replacement only when ordinary retention misses a usable target."""
    if not config.enabled or not isinstance(threshold, int) or threshold <= 0:
        return None
    limits = [value for value in (threshold, safe_limit) if isinstance(value, int) and value > 0]
    if not limits:
        return None
    budget = int(min(limits) * config.ratio)
    normal_tokens = count(normal)
    if normal_tokens is None or normal_tokens + reserve <= budget:
        return None
    eligible = startup_observations(session or runtime)
    if not eligible:
        return None
    protected = protected_messages(session) + [message for message in runtime
        if isinstance(json_tool.safe_json_load(message), dict)
        and json_tool.safe_json_load(message).get("role") == "system"]
    protected_keys = {message_key(message) for message in protected}
    # Keys identify normalized content, not message positions. A later identical
    # runtime-only message may also be filtered out, even if normal summary
    # retention would keep it; a matching protected key instead prevents removal.
    # The user accepts this content-based behavior for now; no positional fix.
    removed = frozenset(message_key(message) for message in eligible) - protected_keys
    if not removed:
        return None
    session_keep = tuple(message for message in session if message_key(message) not in removed)
    if runtime_normal is None:
        runtime_normal = normal if layer == "agent2llm" else runtime
    runtime_keep = unique([message for message in runtime_normal if message_key(message) not in removed] + protected)
    selected = runtime_keep if layer == "agent2llm" else unique(
        [message for message in normal if message_key(message) not in removed] + protected_messages(session)
    )
    if layer == "user2agent":
        session_keep = selected
    # Preserve surviving session values in runtime order, never reorder tool groups.
    runtime_keys = {message_key(message) for message in runtime_keep + tuple(session_keep)}
    for index, message in enumerate(runtime):
        value = json_tool.safe_json_load(message)
        if not isinstance(value, dict) or not value.get("tool_calls"):
            continue
        end = index + 1
        while end < len(runtime):
            following = json_tool.safe_json_load(runtime[end])
            if not isinstance(following, dict) or following.get("role") != "tool":
                break
            end += 1
        group_keys = {message_key(item) for item in runtime[index:end]}
        if group_keys & runtime_keys:
            runtime_keys.update(group_keys)
    runtime_keep = tuple(message for message in runtime if message_key(message) in runtime_keys)
    candidate_tokens = count(list(runtime_keep if layer == "agent2llm" else session_keep))
    if candidate_tokens is None or candidate_tokens + reserve > budget:
        return None
    # Every removed value must actually be available to the summarizer.
    if not removed.issubset({message_key(message) for message in runtime}):
        return None
    return RecoveryPlan(removed, tuple(session_keep), runtime_keep, budget, normal_tokens, candidate_tokens, reserve)
