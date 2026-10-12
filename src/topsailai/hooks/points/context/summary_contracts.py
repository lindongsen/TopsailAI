"""Centralized SummarySnapshot v1 point contracts.

Author: DawsonLin
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration

SUMMARY_SCHEMA_VERSION = 1
SUMMARY_PAYLOAD_LIMIT_BYTES = 8192
COMMON_FIELDS = frozenset({"schema_version", "operation_id", "point_name", "outcome"})
GENERATION_CATEGORIES = frozenset({"timeout", "transport", "provider", "invalid_response", "unknown"})
APPLICATION_CATEGORIES = frozenset({"persistence", "state_update", "unknown"})
GENERATION_STAGES = frozenset({"generation_request", "generation_validate", "generation_unknown"})
APPLICATION_STAGES = MappingProxyType({
    "user2agent": frozenset({"session_write", "history_delete", "session_reload", "memory_update", "application_unknown"}),
    "agent2llm": frozenset({"runtime_rebuild", "tool_pairing", "token_stat_update", "application_unknown"}),
})


@dataclass(frozen=True, slots=True)
class SummaryPointContract:
    """Own one immutable declaration and its lifecycle-specific restrictions."""

    declaration: HookPointDeclaration
    phase_one_eligible: bool

    @property
    def name(self) -> str:
        """Return the authoritative point/event name."""
        return self.declaration.name

    @property
    def definition(self) -> EventDefinition:
        """Return the detached event schema."""
        return self.declaration.definition

    @property
    def layer(self) -> str:
        """Derive layer from the authoritative action suffix."""
        return self.name.rsplit("_", 1)[1]

    @property
    def outcome(self) -> str:
        """Use the declaration phase as the payload outcome."""
        return self.declaration.phase

    @property
    def allowed_fields(self) -> frozenset[str]:
        """Return the exact lifecycle field set."""
        fields = COMMON_FIELDS
        if self.outcome == "error":
            fields = fields | {"error_category", "failed_stage"}
        if self.is_apply_error:
            fields = fields | {"partial_apply_possible"}
        return fields

    @property
    def is_apply_error(self) -> bool:
        """Identify application-error checkpoints only."""
        return self.outcome == "error" and "__summary_apply_" in self.name

    @property
    def error_categories(self) -> frozenset[str]:
        """Return bounded host classifications for this point."""
        if self.outcome != "error":
            return frozenset()
        return APPLICATION_CATEGORIES if self.is_apply_error else GENERATION_CATEGORIES

    @property
    def failed_stages(self) -> frozenset[str]:
        """Return stages available at the point's named layer."""
        if self.outcome != "error":
            return frozenset()
        return APPLICATION_STAGES[self.layer] if self.is_apply_error else GENERATION_STAGES


def _declare(phase: str, action: str, layer: str) -> SummaryPointContract:
    """Build a detached declaration without catalog activation or I/O."""
    name = f"hook__context__{phase}__summary_{action}_{layer}"
    outcome = {"before": "before", "after": "success", "error": "error"}[phase]
    fields = set(COMMON_FIELDS)
    if phase == "error":
        fields.update({"error_category", "failed_stage"})
    if phase == "error" and action == "apply":
        fields.add("partial_apply_possible")
    properties = {
        key: {"type": "integer" if key == "schema_version" else
              "boolean" if key == "partial_apply_possible" else "string"}
        for key in sorted(fields)
    }
    definition = EventDefinition(
        name, SUMMARY_SCHEMA_VERSION,
        {"type": "object", "required": sorted(fields), "properties": properties},
        SUMMARY_PAYLOAD_LIMIT_BYTES,
    )
    declaration = HookPointDeclaration(
        name=name, definition=definition, phase=outcome, mode="sync",
        owner="context.summary", failure_policy="report",
    )
    return SummaryPointContract(declaration, not (phase == "after" and action == "generate"))


BEFORE_GENERATE_USER2AGENT = _declare("before", "generate", "user2agent")
BEFORE_GENERATE_AGENT2LLM = _declare("before", "generate", "agent2llm")
AFTER_GENERATE_USER2AGENT = _declare("after", "generate", "user2agent")
AFTER_GENERATE_AGENT2LLM = _declare("after", "generate", "agent2llm")
AFTER_APPLY_USER2AGENT = _declare("after", "apply", "user2agent")
AFTER_APPLY_AGENT2LLM = _declare("after", "apply", "agent2llm")
ERROR_GENERATE_USER2AGENT = _declare("error", "generate", "user2agent")
ERROR_GENERATE_AGENT2LLM = _declare("error", "generate", "agent2llm")
ERROR_APPLY_USER2AGENT = _declare("error", "apply", "user2agent")
ERROR_APPLY_AGENT2LLM = _declare("error", "apply", "agent2llm")
SUMMARY_POINTS = (
    BEFORE_GENERATE_USER2AGENT, BEFORE_GENERATE_AGENT2LLM,
    AFTER_GENERATE_USER2AGENT, AFTER_GENERATE_AGENT2LLM,
    AFTER_APPLY_USER2AGENT, AFTER_APPLY_AGENT2LLM,
    ERROR_GENERATE_USER2AGENT, ERROR_GENERATE_AGENT2LLM,
    ERROR_APPLY_USER2AGENT, ERROR_APPLY_AGENT2LLM,
)
SUMMARY_POINTS_BY_NAME = MappingProxyType({point.name: point for point in SUMMARY_POINTS})
SUMMARY_SCHEMA = BEFORE_GENERATE_USER2AGENT.definition.payload_schema
