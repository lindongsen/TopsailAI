"""Runtime-owned recovery planning and application. Author: DawsonLin."""

from dataclasses import replace

from topsailai.context import ctx_manager
from topsailai.logger import logger
from topsailai.utils import env_tool
from topsailai.utils.print_tool import print_warning
from topsailai.workspace.context.summary_recovery import (
    fingerprint, message_key, select_recovery,
)


def prepare_recovery(owner, layer, messages, head, tail, keep_session=False):
    """Build an operation-local plan without mutating either message store."""
    config = owner.summary_recovery_config
    if not config.enabled or owner.ai_agent is None:
        return None
    runtime = list(owner.ai_agent.messages) if owner.ai_agent else list(messages)
    if layer == "user2agent" and fingerprint("", messages, []) != fingerprint("", owner.messages, []):
        return None
    if layer == "user2agent":
        normal, _ = owner._build_user2agent_summary_partitions(messages, head, tail)
        reserve = owner._get_user2agent_summary_token_reserve()
        default = 0
    else:
        normal, _ = owner._build_agent2llm_summary_partitions(messages, head, tail, keep_session)
        index = owner.ai_agent.get_work_memory_first_position() or 0
        normal = runtime[:index] + normal
        reserve = owner._get_agent2llm_summary_token_reserve()
        default = 128000
    threshold = env_tool.EnvReaderInstance.get(
        f"TOPSAILAI_{layer.upper()}_TOKEN_SUMMARIZE_THRESHOLD", default=default, formatter=int,
    ) or 0
    model = getattr(owner.ai_agent, "llm_model", None)
    limits = owner._compute_context_limits(getattr(model, "model_name", ""), getattr(model, "max_tokens", 0))
    safe_limit = limits[1] if limits else None
    # A replacement updates both layers, so neither positive trigger may be exceeded.
    other_layer = "agent2llm" if layer == "user2agent" else "user2agent"
    other_threshold = env_tool.EnvReaderInstance.get(
        f"TOPSAILAI_{other_layer.upper()}_TOKEN_SUMMARIZE_THRESHOLD",
        default=128000 if other_layer == "agent2llm" else 0, formatter=int,
    ) or 0
    if other_threshold > 0:
        safe_limit = min(safe_limit, other_threshold) if safe_limit else other_threshold
    index = owner.ai_agent.get_work_memory_first_position() or 0
    runtime_normal, _ = owner._build_agent2llm_summary_partitions(
        runtime[index:], head, tail, keep_session,
    )
    runtime_normal = runtime[:index] + runtime_normal
    plan = select_recovery(
        config, list(owner.messages), runtime, normal, threshold, safe_limit,
        reserve, owner._get_current_tokens, layer, runtime_normal,
    )
    if plan is None:
        return None
    # Full runtime input must include session content before cross-layer removal.
    input_keys = {message_key(message) for message in runtime}
    if any(message_key(message) not in input_keys for message in owner.messages):
        logger.warning("Summary recovery deferred: runtime does not contain complete session; session_id=%s", owner.session_id)
        return None
    allowed, reason, _, _ = owner._check_dynamic_summary_feasibility(
        runtime, plan.candidate_tokens, reserve,
    )
    if not allowed:
        logger.warning("Summary recovery deferred: %s; session_id=%s", reason, owner.session_id)
        return None
    runtime_tokens = owner._get_current_tokens(list(plan.runtime_keep))
    if runtime_tokens is None or runtime_tokens + reserve > plan.budget:
        logger.warning("Summary recovery deferred: runtime survivors exceed target; session_id=%s", owner.session_id)
        return None
    # Report only a plan that survived every admission check, so this record is
    # evidence that the mechanism actually triggered for this operation.
    message = (
        f"Summary recovery triggered: layer={layer} budget={plan.budget} "
        f"normal_tokens={plan.normal_tokens} candidate_tokens={plan.candidate_tokens} "
        f"reserve={reserve} removed_messages={len(plan.removed_keys)} "
        f"session_id={owner.session_id}"
    )
    # print_warning reaches stdout and the chat log, so one call is enough.
    print_warning(message)
    return replace(plan, expected_state=fingerprint(owner.session_id, owner.messages, runtime))


def apply_recovery(owner, plan, summary):
    """Apply a generated full-context summary, then verify actual space recovery."""
    current_runtime = list(owner.ai_agent.messages) if owner.ai_agent else []
    if fingerprint(owner.session_id, owner.messages, current_runtime) != plan.expected_state:
        raise RuntimeError("Summary recovery context changed during generation; originals retained")
    session_before = list(owner.messages)
    session_keep = list(plan.session_keep)
    runtime_keep = list(plan.runtime_keep)
    session_after = session_keep + [summary]
    runtime_after = runtime_keep + [summary]
    actual = [owner._get_current_tokens(session_after), owner._get_current_tokens(runtime_after)]
    if any(value is None or value > plan.budget for value in actual):
        owner._summary_recovery_last_state = plan.expected_state
        logger.warning("Summary recovery result exceeds budget: tokens=%s target=%s session_id=%s", actual, plan.budget, owner.session_id)
        return False
    if owner.session_id:
        raw = ctx_manager.get_messages_by_session(owner.session_id, for_raw=True) or []
        if [message_key(item.message) for item in raw] != [message_key(message) for message in session_before]:
            raise RuntimeError("Summary recovery persisted context changed; originals retained")
        keep_keys = {message_key(message) for message in session_keep}
        delete_ids = [item.msg_id for item in raw if message_key(item.message) not in keep_keys]
        if ctx_manager.add_session_message(owner.session_id, summary) is False:
            raise RuntimeError("Summary recovery session summary write failed")
        if delete_ids and ctx_manager.del_session_messages(owner.session_id, delete_ids) is False:
            raise RuntimeError("Summary recovery history deletion failed after summary write")
        owner.reset_messages()
    else:
        owner.set_messages(session_after)
    if owner.ai_agent:
        owner.ai_agent.messages = runtime_after
        owner.ai_agent.runtime.token_stat.add_msgs(owner.ai_agent.messages, reset_cached_tokens=False)
    after = owner._get_current_tokens(list(owner.ai_agent.messages) if owner.ai_agent else owner.messages)
    logger.info("Summary recovery applied: actual_runtime_tokens=%s target=%s session_id=%s", after, plan.budget, owner.session_id)
    owner._summary_recovery_last_state = fingerprint(
        owner.session_id, owner.messages, owner.ai_agent.messages if owner.ai_agent else [],
    )
    if after is not None and after > plan.budget:
        logger.warning("Summary recovery missed target: actual=%s target=%s session_id=%s", after, plan.budget, owner.session_id)

    return True


def unchanged_recovery(owner):
    """Suppress an identical completed or overlong-result state until inputs change."""
    if not owner.summary_recovery_config.enabled or not owner._summary_recovery_last_state:
        return False
    current = fingerprint(owner.session_id, owner.messages, owner.ai_agent.messages if owner.ai_agent else [])
    return current == owner._summary_recovery_last_state


def recovery_prompt():
    """Request a compact summary that explicitly carries task constraints."""
    return (
        "The opening observations will be replaced by this summary. Preserve all "
        "user requirements, safety constraints, source references, decisions and "
        "unfinished work. Be concise; do not repeat large source files verbatim."
    )
