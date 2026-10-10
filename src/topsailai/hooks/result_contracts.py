"""Shallow immutable result envelopes; opaque payloads remain caller-owned.

Decision provenance is descriptive, never a Catalog authorization capability.
Diagnostics must be redacted by producers before entering this contract.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal

from topsailai.hooks.contracts import ValidationError


def _text(value: object, label: str, *, nonempty: bool = True, limit: int | None = None) -> None:
    """Validate exact strings without formatting untrusted values."""
    if type(value) is not str or (nonempty and not value) or (limit is not None and len(value) > limit):
        raise ValidationError(label + " must be a bounded valid string")


def _choice(value: object, choices: tuple[str, ...], label: str) -> None:
    """Check finite vocabularies only after exact type validation."""
    if type(value) is not str or value not in choices:
        raise ValidationError("invalid " + label)


def _record(value: object, expected: type, label: str, *, optional: bool = False) -> None:
    """Reject nested lookalikes before dependent access."""
    if optional and value is None:
        return
    if type(value) is not expected:
        raise ValidationError("invalid " + label)


def _correlation(result: object) -> None:
    """Validate execution correlation shared by both envelopes."""
    _text(result.execution_id, "execution_id")
    _text(result.hook_point_name, "hook_point_name")
    if type(result.plan_version) is not int or result.plan_version < 0:
        raise ValidationError("invalid plan_version")


def _members(owner: object, values: object, label: str) -> tuple[HandlerResult, ...]:
    """Detach bounded exact containers and validate correlated members."""
    if type(values) not in (list, tuple) or len(values) > 256:
        raise ValidationError("invalid " + label)
    members = tuple(values)
    ids, names = set(), set()
    for member in members:
        _record(member, HandlerResult, label + " member")
        if (member.execution_id, member.hook_point_name, member.plan_version) != (owner.execution_id, owner.hook_point_name, owner.plan_version):
            raise ValidationError("result correlation mismatch")
        key = (member.handler.kind, member.handler.name)
        if member.handler.id in ids or key in names:
            raise ValidationError("duplicate result identity")
        ids.add(member.handler.id)
        names.add(key)
    return members


@dataclass(frozen=True, slots=True)
class HandlerIdentity:
    """Identify a captured handler independently of its import or physical path."""
    id: str
    name: str
    kind: Literal["module", "default_script_hook", "script"]

    def __post_init__(self) -> None:
        """Preserve exact registered names, including an explicit empty name."""
        _text(self.id, "handler id")
        _text(self.name, "handler name", nonempty=False)
        _choice(self.kind, ("module", "default_script_hook", "script"), "handler kind")


@dataclass(frozen=True, slots=True)
class ReturnedValue:
    """Record presence separately from value without observing opaque payloads."""
    present: bool = False
    representation: Literal["direct", "transported", "reference", "unavailable"] = "unavailable"
    value: Any = field(default=None, repr=False, compare=False, hash=False)
    reference: str | None = None

    def __post_init__(self) -> None:
        """Reject unsupported references and inconsistent representation metadata."""
        if type(self.present) is not bool:
            raise ValidationError("invalid return presence")
        _choice(self.representation, ("direct", "transported", "reference", "unavailable"), "return representation")
        if self.representation == "reference":
            raise ValidationError("managed references are unsupported")
        if self.reference is not None:
            raise ValidationError("unexpected return reference")
        if not self.present and self.representation != "unavailable":
            raise ValidationError("absent return must be unavailable")
        if self.representation == "unavailable" and self.value is not None:
            raise ValidationError("unavailable return cannot hold a value")


@dataclass(frozen=True, slots=True)
class ResultDiagnostic:
    """Hold bounded producer-redacted strings, not exception objects."""
    category: str
    message: str

    def __post_init__(self) -> None:
        """Enforce safe structural bounds without extracting or formatting errors."""
        _text(self.category, "diagnostic category", limit=128)
        _text(self.message, "diagnostic message", nonempty=False, limit=1024)


@dataclass(frozen=True, slots=True)
class ResultTiming:
    """Keep optional wall timestamps separate from measured monotonic duration."""
    started_at: int | float | None = None
    finished_at: int | float | None = None
    elapsed_ms: int = 0

    def __post_init__(self) -> None:
        """Validate finite timestamps without deriving elapsed duration."""
        for value in (self.started_at, self.finished_at):
            if value is not None and (type(value) not in (int, float) or (type(value) is float and not math.isfinite(value))):
                raise ValidationError("invalid result timestamp")
        if self.started_at is not None and self.finished_at is not None and self.finished_at < self.started_at:
            raise ValidationError("result timestamps are reversed")
        if type(self.elapsed_ms) is not int or self.elapsed_ms < 0:
            raise ValidationError("invalid elapsed_ms")


@dataclass(frozen=True, slots=True)
class ResultCleanup:
    """Describe cleanup independently of execution success or failure."""
    state: Literal["safe", "pending", "failed"] = "safe"
    diagnostic: ResultDiagnostic | None = None

    def __post_init__(self) -> None:
        """Validate cleanup state and optional bounded diagnostics."""
        _choice(self.state, ("safe", "pending", "failed"), "cleanup state")
        _record(self.diagnostic, ResultDiagnostic, "cleanup diagnostic", optional=True)


@dataclass(frozen=True, slots=True)
class ResultDecision:
    """Report provenance only; the Catalog must independently authorize blocking."""
    action: Literal["continue", "block"] = "continue"
    authority: Literal["catalog"] | None = None

    def __post_init__(self) -> None:
        """Validate descriptive provenance without consulting or impersonating policy."""
        _choice(self.action, ("continue", "block"), "decision action")
        if self.authority is not None:
            _choice(self.authority, ("catalog",), "decision authority")
        if self.action == "block" and self.authority is None:
            raise ValidationError("block requires catalog provenance")


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """Report one handler and optional ordered Script children without deriving policy."""
    execution_id: str
    hook_point_name: str
    plan_version: int
    handler: HandlerIdentity
    status: Literal["success", "error", "timeout", "cancelled", "not_run", "completed_with_errors"] = "success"
    not_run_reason: str | None = None
    returned: ReturnedValue = field(default_factory=ReturnedValue)
    error: ResultDiagnostic | None = None
    timing: ResultTiming = field(default_factory=ResultTiming)
    cleanup: ResultCleanup = field(default_factory=ResultCleanup)
    decision: ResultDecision = field(default_factory=ResultDecision)
    children: tuple[HandlerResult, ...] = ()

    def __post_init__(self) -> None:
        """Validate shape and detach children without inspecting returned payloads."""
        _correlation(self)
        _record(self.handler, HandlerIdentity, "handler identity")
        _choice(self.status, ("success", "error", "timeout", "cancelled", "not_run", "completed_with_errors"), "handler status")
        _record(self.returned, ReturnedValue, "returned")
        _record(self.error, ResultDiagnostic, "error diagnostic", optional=True)
        _record(self.timing, ResultTiming, "timing")
        _record(self.cleanup, ResultCleanup, "cleanup")
        _record(self.decision, ResultDecision, "decision")
        if self.status == "not_run":
            _text(self.not_run_reason, "not_run reason", limit=1024)
        elif self.not_run_reason is not None:
            raise ValidationError("unexpected not_run reason")
        if self.status in ("error", "timeout", "cancelled", "not_run") and self.returned.present:
            raise ValidationError("failed or unrun handler cannot return normally")
        if self.status == "error" and self.error is None:
            raise ValidationError("error status requires diagnostic")
        if self.status == "completed_with_errors" and self.handler.kind != "default_script_hook":
            raise ValidationError("only default Script Hook may complete with errors")
        children = _members(self, self.children, "children")
        if children and self.handler.kind != "default_script_hook":
            raise ValidationError("only default Script Hook has children")
        if any(child.handler.kind != "script" for child in children):
            raise ValidationError("default children must be Scripts")
        object.__setattr__(self, "children", children)


@dataclass(frozen=True, slots=True)
class HookPointResult:
    """Hold a caller-reported aggregate and the captured order, without status inference."""
    execution_id: str
    hook_point_name: str
    plan_version: int
    status: Literal["success", "completed_with_errors", "blocked", "timeout", "cancelled", "unavailable"] = "success"
    handlers: tuple[HandlerResult, ...] = ()
    timing: ResultTiming = field(default_factory=ResultTiming)
    cleanup: ResultCleanup = field(default_factory=ResultCleanup)
    decision: ResultDecision = field(default_factory=ResultDecision)

    def __post_init__(self) -> None:
        """Validate terminal plan shape while keeping execution and policy elsewhere."""
        _correlation(self)
        _choice(self.status, ("success", "completed_with_errors", "blocked", "timeout", "cancelled", "unavailable"), "Hook Point status")
        _record(self.timing, ResultTiming, "timing")
        _record(self.cleanup, ResultCleanup, "cleanup")
        _record(self.decision, ResultDecision, "decision")
        if (self.status == "blocked") != (self.decision.action == "block"):
            raise ValidationError("blocked status and decision disagree")
        handlers = _members(self, self.handlers, "handlers")
        if not handlers:
            if self.status != "unavailable":
                raise ValidationError("available plan requires default Script Hook")
        elif handlers[-1].handler.kind != "default_script_hook" or any(item.handler.kind != "module" for item in handlers[:-1]):
            raise ValidationError("Modules must precede one terminal default Script Hook")
        object.__setattr__(self, "handlers", handlers)
