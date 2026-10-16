"""Test-only bridge for retained prepared Executor tests, not a production API.

Author: DawsonLin
"""

from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from topsailai.hooks.configured_executor import HookOperation
from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.points.context.summary_adapter import SummaryCheckpointResult, _CHECKPOINTS


@dataclass(frozen=True, slots=True, eq=False)
class LegacySummaryHookOperation:
    """Use adapter-shared checkpoint custody for one actual summary."""

    layer: str
    operation: HookOperation
    _executor: Any = field(repr=False)
    _handled: set[tuple[str, str]] = field(default_factory=set, repr=False)
    _lock: Any = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        """Validate explicit authority and the U2 identity boundary before use."""
        if type(self.layer) is not str or self.layer not in _CHECKPOINTS:
            raise ValidationError("invalid summary layer")
        if type(self.operation) is not HookOperation:
            raise ValidationError("summary operation must be an exact HookOperation")
        if not callable(getattr(self._executor, "dispatch", None)):
            raise ValidationError("summary executor must provide dispatch")
        _CHECKPOINTS[self.layer]["before_summary_generate"].build_payload(
            operation_id=self.operation.operation_id)

    def emit(self, checkpoint: str, **classification: Any) -> SummaryCheckpointResult:
        """Validate then atomically consume a same-layer checkpoint before dispatch."""
        if type(checkpoint) is not str or checkpoint not in _CHECKPOINTS[self.layer]:
            raise ValidationError("unknown or inactive summary checkpoint")
        selected = _CHECKPOINTS[self.layer][checkpoint]
        key = (self.operation.operation_id, selected.NAME)
        with self._lock:
            if key in self._handled:
                return SummaryCheckpointResult(*key, already_handled=True)
            try:
                payload = selected.build_payload(
                    operation_id=self.operation.operation_id, **classification)
            except TypeError as error:
                raise ValidationError("invalid summary classification fields") from error
            self._handled.add(key)
        report = self._executor.dispatch(selected.POINT, payload=payload, operation=self.operation)
        return SummaryCheckpointResult(*key, already_handled=False, report=report)


class LegacySummaryHookAdapter:
    """Create explicit summary operations using an injected synchronous executor."""

    def __init__(self, executor: Any) -> None:
        """Bind authority without creating a runtime, registrar, or global lookup."""
        if not callable(getattr(executor, "dispatch", None)):
            raise ValidationError("summary executor must provide dispatch")
        self._executor = executor
        self._handled: set[tuple[str, str]] = set()
        self._lock = Lock()

    def begin(self, layer: str, *, operation: HookOperation | None = None) -> LegacySummaryHookOperation:
        """Create one operation wrapper using this adapter's shared checkpoint custody."""
        return LegacySummaryHookOperation(
            layer, HookOperation() if operation is None else operation, self._executor,
            _handled=self._handled, _lock=self._lock)
