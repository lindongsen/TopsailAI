"""Hooks for successful story memory create and update operations."""

import json
import logging
import os
from collections.abc import Callable

from topsailai.utils import cmd_tool, hook_tool

logger = logging.getLogger(__name__)

CREATE = "create"
UPDATE = "update"
SUPPORTED_OPERATIONS = (CREATE, UPDATE)
EXTERNAL_HOOK_ENV_KEY = "TOPSAILAI_HOOK_SCRIPTS_MEMORY_WRITE"
MEMORY_SYNC_HOOKS_ENV_KEY = "TOPSAILAI_MEMORY_SYNC_HOOKS"
DEFAULT_SYNC_HOOK_TIMEOUT = 300
EVENT_SCHEMA_VERSION = 1
EVENT_FIELDS = (
    "memory_id",
    "title",
    "content",
    "memory_file",
    "workspace",
    "timestamp",
    "version",
)


class MemoryHookRegistry:
    """Register and call memory hooks in deterministic registration order."""

    def __init__(self):
        self._hooks: dict[str, list[Callable[[dict], object]]] = {
            operation: [] for operation in SUPPORTED_OPERATIONS
        }

    def register(self, operation: str, hook: Callable[[dict], object]) -> None:
        """Register a callable for a supported memory operation."""
        if operation not in self._hooks:
            raise ValueError(f"unsupported memory hook operation: {operation}")
        if not callable(hook):
            raise ValueError("memory hook must be callable")
        self._hooks[operation].append(hook)

    def unregister(self, operation: str, hook: Callable[[dict], object]) -> bool:
        """Unregister one callable and report whether it was present."""
        if operation not in self._hooks:
            return False
        try:
            self._hooks[operation].remove(hook)
            return True
        except ValueError:
            return False

    def call(self, operation: str, event: dict) -> list[object | None]:
        """Call all hooks for an operation, swallowing individual failures."""
        results = []
        for hook in tuple(self._hooks.get(operation, ())):
            try:
                results.append(hook(event))
            except Exception:
                logger.exception(
                    "memory hook failed: operation=%s hook=%r", operation, hook
                )
                results.append(None)
        return results


REGISTRY = MemoryHookRegistry()


def register_create_hook(hook: Callable[[dict], object]) -> None:
    """Register a hook for successful memory creation."""
    REGISTRY.register(CREATE, hook)


def register_update_hook(hook: Callable[[dict], object]) -> None:
    """Register a hook for successful memory updates."""
    REGISTRY.register(UPDATE, hook)


def unregister_create_hook(hook: Callable[[dict], object]) -> bool:
    """Unregister a memory creation hook."""
    return REGISTRY.unregister(CREATE, hook)


def unregister_update_hook(hook: Callable[[dict], object]) -> bool:
    """Unregister a memory update hook."""
    return REGISTRY.unregister(UPDATE, hook)


def _load_sync_hook_config() -> dict:
    """Load the optional event-keyed sync hook configuration."""
    raw = os.getenv(MEMORY_SYNC_HOOKS_ENV_KEY, "").strip()
    if not raw:
        return {}
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("invalid %s JSON: %s", MEMORY_SYNC_HOOKS_ENV_KEY, exc)
        return {}
    if not isinstance(config, dict):
        logger.warning("%s must contain a JSON object", MEMORY_SYNC_HOOKS_ENV_KEY)
        return {}
    for key in config:
        if key not in SUPPORTED_OPERATIONS:
            logger.warning("ignoring unsupported memory sync event: %s", key)
    return config


def _build_sync_event(operation: str, event: dict) -> dict:
    """Convert the internal memory event into the stable stdin contract."""
    payload = {"schema_version": EVENT_SCHEMA_VERSION, "event": operation}
    payload.update({field: event[field] for field in EVENT_FIELDS})
    return payload


def _dispatch_sync_binding(operation: str, binding: object, stdin_text: str):
    """Execute one configured sync binding without raising to the write path."""
    if not isinstance(binding, dict):
        logger.warning("ignoring invalid memory sync binding: operation=%s", operation)
        return None
    if binding.get("enabled", True) is False:
        return None

    script = binding.get("script")
    if not isinstance(script, str) or not script.strip():
        logger.warning("memory sync binding has no script: operation=%s", operation)
        return None
    timeout = binding.get("timeout", DEFAULT_SYNC_HOOK_TIMEOUT)
    env_keys = binding.get("env_keys")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        logger.warning("memory sync binding has invalid timeout: operation=%s", operation)
        return None
    if env_keys is not None and (
        not isinstance(env_keys, list)
        or not all(isinstance(key, str) for key in env_keys)
    ):
        logger.warning("memory sync binding has invalid env_keys: operation=%s", operation)
        return None

    try:
        result = cmd_tool.exec_cmd(
            [script], timeout=timeout, env_keys=env_keys, stdin_text=stdin_text
        )
        if result[0] != 0:
            logger.warning(
                "memory sync hook exited non-zero: operation=%s script=%s code=%s",
                operation,
                script,
                result[0],
            )
        return result
    except Exception:
        logger.exception(
            "memory sync hook failed: operation=%s script=%s", operation, script
        )
        return None


def dispatch_memory_sync_hooks(operation: str, event: dict) -> list[object | None]:
    """Dispatch configured create or update scripts with a JSON stdin payload."""
    if operation not in SUPPORTED_OPERATIONS:
        return []
    bindings = _load_sync_hook_config().get(operation, [])
    if not isinstance(bindings, list):
        logger.warning("memory sync event bindings must be a list: %s", operation)
        return []
    if not bindings:
        return []

    try:
        stdin_text = json.dumps(_build_sync_event(operation, event), ensure_ascii=False)
    except (KeyError, TypeError, ValueError):
        logger.exception("invalid memory sync event payload: operation=%s", operation)
        return []
    return [
        _dispatch_sync_binding(operation, binding, stdin_text)
        for binding in bindings
    ]


def fire_memory_hooks(operation: str, event: dict) -> dict:
    """Run in-process, legacy external, and event-keyed sync hooks."""
    in_process = REGISTRY.call(operation, event)
    external = {}
    try:
        external = hook_tool.call_hook_scripts(EXTERNAL_HOOK_ENV_KEY, event)
    except Exception:
        logger.exception("external memory hooks failed: operation=%s", operation)
    sync = dispatch_memory_sync_hooks(operation, event)
    return {"in_process": in_process, "external": external, "sync": sync}
