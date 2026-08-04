"""
Business control handlers package.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-04
Purpose: Auto-discover and register business handlers for the control channel
"""

import importlib
import inspect
import os
from typing import Type

from topsailai.workspace.control_channel.handler import ControlHandler, ControlHandlerRegistry


def _discover_handler_classes(package_dir: str, package_name: str) -> list[Type[ControlHandler]]:
    """Scan package_dir for ControlHandler subclasses.

    Every ``.py`` file except ``__init__.py`` is imported. Classes that are
    concrete subclasses of ``ControlHandler`` are collected and returned.
    """
    handler_classes: list[Type[ControlHandler]] = []
    for filename in sorted(os.listdir(package_dir)):
        if not filename.endswith(".py"):
            continue
        if filename == "__init__.py":
            continue

        module_name = f"{package_name}.{filename[:-3]}"
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
    package_dir = os.path.dirname(os.path.abspath(__file__))
    package_name = __name__

    handler_classes = _discover_handler_classes(package_dir, package_name)

    for handler_class in handler_classes:
        registry.register(handler_class())
