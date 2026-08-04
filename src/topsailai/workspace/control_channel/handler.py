"""
Handler registry for the control channel module.

Provides the abstract base class for business handlers and the registry
that maps actions to handlers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-03
Purpose: Control channel handler registry
"""

from abc import ABC, abstractmethod
from typing import Optional

from topsailai.workspace.control_channel.protocol import ControlRequest, ControlResponse, ControlContext


class ControlHandler(ABC):
    """Abstract base class for control channel business handlers.

    Subclasses must define the action name and implement handle().
    """

    @property
    @abstractmethod
    def action(self) -> str:
        """Return the action name this handler processes."""

    @abstractmethod
    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        """Process the request and return a response.

        Args:
            request: The incoming control request.
            context: Runtime context for the current agent process.

        Returns:
            A ControlResponse instance.
        """


class ControlHandlerRegistry:
    """Registry mapping action names to ControlHandler instances.

    Similar to HookInstruction, this registry allows business logic to be
    registered and unregistered dynamically.
    """

    def __init__(self):
        self._handlers: dict[str, ControlHandler] = {}

    def register(self, handler: ControlHandler) -> None:
        """Register a handler for its declared action.

        Args:
            handler: A ControlHandler instance.

        Raises:
            ValueError: If handler is None, does not declare an action,
                or if the action is already registered.
        """
        if handler is None:
            raise ValueError("handler cannot be None")
        action = handler.action
        if not action:
            raise ValueError("handler must declare a non-empty action")
        if action in self._handlers:
            raise ValueError(f"action already registered: {action}")
        self._handlers[action] = handler

    def unregister(self, action: str) -> Optional[ControlHandler]:
        """Unregister a handler by action name.

        Args:
            action: The action name to unregister.

        Returns:
            The removed handler, or None if no handler was registered.
        """
        return self._handlers.pop(action, None)

    def get(self, action: str) -> Optional[ControlHandler]:
        """Get the handler registered for an action.

        Args:
            action: The action name to look up.

        Returns:
            The registered handler, or None if not found.
        """
        return self._handlers.get(action)

    def list_actions(self) -> list[str]:
        """Return a sorted list of registered action names."""
        return sorted(self._handlers.keys())

    def is_registered(self, action: str) -> bool:
        """Check whether an action has a registered handler."""
        return action in self._handlers

    def handle(self, request: ControlRequest, context: ControlContext) -> ControlResponse:
        """Dispatch a request to the appropriate handler.

        Args:
            request: The incoming control request.
            context: Runtime context for the current agent process.

        Returns:
            A ControlResponse. If no handler is found or the handler raises,
            an error response is returned.
        """
        handler = self._handlers.get(request.action)
        if handler is None:
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error=f"unknown action: {request.action}",
            )
        try:
            return handler.handle(request, context)
        except Exception as e:
            return ControlResponse(
                request_id=request.request_id,
                status="error",
                error=f"handler error: {e}",
            )
