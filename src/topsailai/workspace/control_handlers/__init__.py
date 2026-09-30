"""
Business control handlers package.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-04
Purpose: Auto-discover and register business handlers for the control channel
"""

import importlib
import inspect
import pkgutil
from typing import Type

from topsailai.workspace.control_channel.handler import ControlHandler, ControlHandlerRegistry


def _discover_handler_classes(package_path: list[str], package_name: str) -> list[Type[ControlHandler]]:
    """Discover concrete ControlHandler subclasses in package modules."""
    handler_classes: list[Type[ControlHandler]] = []
    modules = sorted(pkgutil.iter_modules(package_path), key=lambda module: module.name)
    for module_info in modules:
        if module_info.ispkg:
            continue

        module_name = f"{package_name}.{module_info.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            # A broken module should not prevent other handlers from loading.
            continue

        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if obj is ControlHandler:
                continue
            if issubclass(obj, ControlHandler) and not inspect.isabstract(obj):
                handler_classes.append(obj)

    return handler_classes


def register_control_handlers(registry: ControlHandlerRegistry) -> None:
    """Register all discovered business control handlers on the given registry."""
    handler_classes = _discover_handler_classes(__path__, __name__)

    for handler_class in handler_classes:
        registry.register(handler_class())
