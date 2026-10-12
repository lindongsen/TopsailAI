"""Strict, immutable metadata-only SummarySnapshot v1 boundary.

Author: DawsonLin
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.points.context.summary_contracts import (
    SUMMARY_POINTS_BY_NAME,
    SUMMARY_SCHEMA_VERSION,
    SummaryPointContract,
)
from topsailai.hooks.validation import validate_payload

_OPERATION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _validate(point: SummaryPointContract, payload: Any, operation_id: str) -> dict:
    """Compose generic detachment with exact v1 identity and classification checks."""
    if type(point) is not SummaryPointContract:
        raise ValidationError("summary point must be a SummaryPointContract")
    canonical = SUMMARY_POINTS_BY_NAME.get(point.name)
    if canonical is None or point != canonical:
        raise ValidationError("summary point must match its centralized v1 contract")
    if type(operation_id) is not str or not _OPERATION_ID.fullmatch(operation_id):
        raise ValidationError("invalid expected summary operation_id")
    detached = validate_payload(point.definition, payload)
    if set(detached) != point.allowed_fields:
        raise ValidationError("summary payload has an invalid field set")
    if detached["schema_version"] != SUMMARY_SCHEMA_VERSION or detached["schema_version"] != point.definition.major_version:
        raise ValidationError("summary schema_version must equal event major_version")
    if detached["operation_id"] != operation_id:
        raise ValidationError("summary operation_id must equal expected operation_id")
    if detached["point_name"] != point.name or detached["point_name"] != point.definition.name:
        raise ValidationError("summary point_name must equal point and event name")
    if detached["outcome"] != point.outcome:
        raise ValidationError("summary outcome must match point phase")
    if point.outcome == "error":
        if detached["error_category"] not in point.error_categories:
            raise ValidationError("invalid summary error_category")
        if detached["failed_stage"] not in point.failed_stages:
            raise ValidationError("invalid summary failed_stage")
    return detached


@dataclass(frozen=True, slots=True)
class SummarySnapshot:
    """Own validated scalar metadata; optional model values are omitted on the wire."""

    schema_version: int
    operation_id: str
    point_name: str
    outcome: str
    error_category: str | None = None
    failed_stage: str | None = None
    partial_apply_possible: bool | None = None

    def __post_init__(self) -> None:
        """Reject invalid direct construction as well as invalid boundary input."""
        if type(self.point_name) is not str:
            raise ValidationError("invalid summary point_name")
        point = SUMMARY_POINTS_BY_NAME.get(self.point_name)
        if point is None:
            raise ValidationError("unknown summary point_name")
        _validate(point, self.to_payload(), self.operation_id)

    def to_payload(self) -> dict:
        """Return a fresh plain JSON object with no mutable aliases or layer field."""
        payload = {
            "schema_version": self.schema_version, "operation_id": self.operation_id,
            "point_name": self.point_name, "outcome": self.outcome,
        }
        for key in ("error_category", "failed_stage", "partial_apply_possible"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload


def validate_summary_payload(
    point: SummaryPointContract, payload: Any, *, operation_id: str,
) -> SummarySnapshot:
    """Validate raw JSON against a host-selected contract and expected operation ID."""
    return SummarySnapshot(**_validate(point, payload, operation_id))


def build_summary_payload(
    point: SummaryPointContract, *, operation_id: str, **classification: Any,
) -> dict:
    """Build only fixed identity fields and approved explicit host classifications."""
    if type(point) is not SummaryPointContract:
        raise ValidationError("summary point must be a SummaryPointContract")
    if set(classification) - {"error_category", "failed_stage", "partial_apply_possible"}:
        raise ValidationError("unknown summary classification fields")
    payload = {
        "schema_version": SUMMARY_SCHEMA_VERSION, "operation_id": operation_id,
        "point_name": point.name, "outcome": point.outcome, **classification,
    }
    return validate_summary_payload(point, payload, operation_id=operation_id).to_payload()
