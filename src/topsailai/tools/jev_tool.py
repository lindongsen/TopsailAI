"""JEV semantic decision tool."""

import json
import os

from topsailai.tools.jev_tool_utils.client import error_result, evaluate_remote
from topsailai.tools.jev_tool_utils.config import JevConfigError, load_config
from topsailai.tools.jev_tool_utils.context import JevContextError, build_state
from topsailai.utils.thread_local_tool import get_agent_object

_ALLOWED_FIELDS = {"type", "instructions", "criteria"}
_ALLOWED_TYPES = {"choice", "score", "noul"}


def _validate_questions(value) -> tuple[dict | None, str | None]:
    """Parse and validate the string-first JEV question object."""
    if not isinstance(value, str):
        return None, "questions_must_be_json_string"
    try:
        questions = json.loads(value)
    except (TypeError, ValueError):
        return None, "invalid_questions_json"
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 32:
        return None, "questions_must_contain_1_to_32_entries"
    for question_id, question in questions.items():
        if not isinstance(question_id, str) or not question_id.strip():
            return None, "invalid_question_id"
        if not isinstance(question, dict):
            return None, "question_must_be_object"
        if set(question) - _ALLOWED_FIELDS:
            return None, "unknown_question_field"
        question_type = question.get("type")
        if question_type not in _ALLOWED_TYPES:
            return None, "invalid_question_type"
        instructions = question.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            return None, "invalid_question_instructions"
        criteria = question.get("criteria")
        if question_type == "choice":
            if not isinstance(criteria, dict) or not criteria:
                return None, "missing_question_criteria"
        elif question_type == "score":
            if not isinstance(criteria, list) or not 2 <= len(criteria) <= 10:
                return None, "score_criteria_must_contain_2_to_10_levels"
            if any(not isinstance(level, (str, dict, list)) for level in criteria):
                return None, "invalid_score_criteria_level"
        elif "criteria" in question:
            return None, "noul_criteria_not_supported"
    return questions, None


def evaluate(questions: str) -> dict:
    """Evaluate typed questions against the current Agent2LLM conversation.

    Args:
        questions: A JSON-object string keyed by question ID. Every value needs
            ``type`` (``noul``, ``choice``, or ``score``) and non-empty
            ``instructions``. A ``choice`` needs a non-empty ``criteria`` object.
            A ``score`` needs an ordered ``criteria`` array containing 2–10
            string, object, or array levels. One call accepts 1–32 questions.

        Example:
            ``evaluate('{"refund":{"type":"noul","instructions":"Does the user request a refund?"},"priority":{"type":"choice","instructions":"Choose the priority.","criteria":{"low":"Can wait","high":"Needs prompt attention"}},"quality":{"type":"score","instructions":"Rate the response quality.","criteria":["poor","acceptable","good"]}}')``

    Context:
        Sends eligible user, assistant, and complete paired tool interactions
        from the current Agent2LLM runtime. System messages and the active JEV
        tool-call declaration are excluded.

    Returns:
        A dictionary with ``status=ok``, model, structured answers, and usage;
        otherwise status is ``invalid_request``, ``unavailable``, ``timeout``,
        ``upstream_error``, or ``invalid_response`` with a machine-readable
        reason. Numeric ``noul`` values are returned without boolean conversion.
    """
    parsed_questions, reason = _validate_questions(questions)
    if reason:
        return error_result("invalid_request", reason, "Invalid JEV questions")
    try:
        config = load_config()
    except JevConfigError as exc:
        return error_result("invalid_request", exc.reason, "Invalid JEV configuration")
    try:
        state = build_state(
            get_agent_object(),
            config.api_key,
            config.max_context_messages,
            config.max_context_chars,
        )
    except JevContextError as exc:
        return error_result("unavailable", str(exc), "Agent2LLM context is unavailable")
    return evaluate_remote(config, state, parsed_questions)


PROMPT = """
## jev_tool (evaluate)

Use this tool for fast, structured semantic decisions over the current Agent2LLM
conversation and completed tool results. Pass a JSON-object string containing
1–32 named ``noul``, ``choice``, or ``score`` questions. Choice criteria are a
non-empty object; score criteria are an ordered array of 2–10 string, object, or
array levels. System messages are not sent. The service configuration is
controlled only by TOPSAILAI_JEV_* settings.
"""

TOOLS = {"evaluate": evaluate}
FLAG_TOOL_ENABLED = bool(os.getenv("TOPSAILAI_JEV_BASE_URL", "").strip())
