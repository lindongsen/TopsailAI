"""Hooks for successful story memory create and update operations."""

import logging
from collections.abc import Callable

from topsailai.utils import hook_tool

logger = logging.getLogger(__name__)

CREATE = "create"
UPDATE = "update"
SUPPORTED_OPERATIONS = (CREATE, UPDATE)
EXTERNAL_HOOK_ENV_KEY = "TOPSAILAI_HOOK_SCRIPTS_MEMORY_WRITE"


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


def fire_memory_hooks(operation: str, event: dict) -> dict:
    """Run in-process hooks first, then configured external scripts."""
    in_process = REGISTRY.call(operation, event)
    external = {}
    try:
        external = hook_tool.call_hook_scripts(EXTERNAL_HOOK_ENV_KEY, event)
    except Exception:
        logger.exception("external memory hooks failed: operation=%s", operation)
    return {"in_process": in_process, "external": external}
