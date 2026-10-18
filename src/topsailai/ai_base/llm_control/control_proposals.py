"""Validate opaque Hook returns without granting plugin authority. Author: DawsonLin."""
from topsailai.ai_base.llm_control.attempt_control import AttemptTarget, ControlProposal
from topsailai.hooks.result_contracts import HookPointResult

CONTROL_POINT = "hook__llm__before__first_byte_wait_tick"


def validated_proposals(result, target, *, registry):
    """Decode successful direct Module values and revalidate retained provenance.

    Exact envelope types avoid executing properties on opaque plugin values.
    Duplicate returns are ignored; no callback, exception or Script result is a
    command. Selection still MUST revalidate under the arbitration lock.
    """
    if type(result) is not HookPointResult or type(target) is not AttemptTarget:
        return ()
    if result.hook_point_name != CONTROL_POINT or result.status not in ("success", "completed_with_errors"):
        return ()
    proposals = []
    seen = set()
    for handler in result.handlers:
        if handler.handler.kind != "module" or handler.status != "success":
            continue
        returned = handler.returned
        if not returned.present or returned.representation != "direct":
            continue
        proposal = returned.value
        if type(proposal) is not ControlProposal or id(proposal) in seen:
            continue
        if registry.validates(target, proposal):
            seen.add(id(proposal))
            proposals.append(proposal)
    return tuple(proposals)
