"""Deterministic provider-error retry classification.

This module owns the rules that decide whether a request-shape ``BadRequestError``
is non-retryable. It is intentionally provider-neutral: it does not import OpenAI,
HTTPX, or HTTPCore exception classes. ``LLMModel.chat()`` remains responsible for
deciding when a caught provider error should be passed to the classifier.
"""

from topsailai.utils import env_tool

# Case-insensitive contextual rules for deterministic request-shape 400 errors.
# Every phrase in one rule must match; generic protocol field names alone remain
# retryable because a gateway may echo them while reporting a transient failure.
_LLM_NON_RETRYABLE_BAD_REQUEST_RULES = (
    ("no tool call found",),
    ("no tool output found for function call",),
    ("function_call_output", "no matching function_call"),
    ("function_call_output", "no function call found"),
    ("tool_call_id", "not found"),
    ("tool_call_id", "preceding message"),
)


def match_non_retryable_bad_request(e_str: str) -> str:
    """Return the first non-retryable request-shape rule matching the error text.

    Built-in contextual rules are always active. The semicolon-separated
    ``TOPSAILAI_LLM_NON_RETRYABLE_BAD_REQUEST_MARKERS`` value adds optional
    provider-specific substring markers without disabling the built-ins.

    Args:
        e_str (str): Provider error text.

    Returns:
        str: The matched rule description or marker, or an empty string.
    """
    e_str = str(e_str).lower()
    for phrases in _LLM_NON_RETRYABLE_BAD_REQUEST_RULES:
        if all(phrase in e_str for phrase in phrases):
            return " + ".join(phrases)

    extra = env_tool.EnvReaderInstance.get_list_str(
        "TOPSAILAI_LLM_NON_RETRYABLE_BAD_REQUEST_MARKERS", separator=";"
    )
    for marker in extra or []:
        marker = str(marker).lower()
        if marker and marker in e_str:
            return marker
    return ""
