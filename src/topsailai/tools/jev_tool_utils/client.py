"""HTTP transport and response validation for the JEV decision tool."""

import math
import random
import time
from typing import Callable

import httpx

from topsailai.tools.jev_tool_utils.models import JevConfig

_RETRYABLE_STATUS = {408, 429, 502, 503, 504}


def error_result(status: str, reason: str, message: str, retryable: bool = False) -> dict:
    """Build a stable bounded error result."""
    return {
        "status": status,
        "reason": reason,
        "message": message[:300],
        "retryable": retryable,
    }


def _is_finite_number(value) -> bool:
    """Return whether a value is a finite JSON number rather than a boolean."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_probability_map(value) -> bool:
    """Return whether a value is a string-keyed map of finite probabilities."""
    return isinstance(value, dict) and all(
        isinstance(key, str) and _is_finite_number(item)
        for key, item in value.items()
    )


def _validate_answer(answer: dict, answer_type: str) -> None:
    """Validate one typed answer against the deployed OpenAPI contract."""
    if answer_type == "noul":
        if set(answer) != {"type", "noul"} or not _is_finite_number(answer.get("noul")):
            raise ValueError("invalid_noul_answer")
        return
    common = {"type", answer_type, "probabilities", "confidence"}
    if answer_type == "choice":
        if set(answer) != common or not isinstance(answer.get("choice"), str):
            raise ValueError("invalid_choice_answer")
    elif answer_type == "score":
        if set(answer) != common | {"legend"} or not _is_finite_number(answer.get("score")):
            raise ValueError("invalid_score_answer")
        legend = answer.get("legend")
        if not isinstance(legend, dict) or not all(
            isinstance(key, str) and isinstance(item, str) for key, item in legend.items()
        ):
            raise ValueError("invalid_score_answer")
    if not _is_probability_map(answer.get("probabilities")) or not _is_finite_number(
        answer.get("confidence")
    ):
        raise ValueError(f"invalid_{answer_type}_answer")


def _validate_response(data, questions: dict) -> dict:
    """Validate answer identity/type parity and normalize a successful result."""
    if not isinstance(data, dict):
        raise ValueError("response_not_object")
    if set(data) != {"model", "answers", "usage"} or not isinstance(data.get("model"), str):
        raise ValueError("invalid_response_fields")
    answers = data.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("answer_keys_mismatch")
    for question_id, question in questions.items():
        answer = answers.get(question_id)
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise ValueError("answer_type_mismatch")
        _validate_answer(answer, question["type"])
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("invalid_usage")
    if set(usage) != {"input_tokens", "output_tokens"} or not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in usage.values()
    ):
        raise ValueError("invalid_usage")
    return {
        "status": "ok",
        "model": data["model"],
        "answers": answers,
        "usage": usage,
    }


def _http_error(response: httpx.Response) -> dict:
    """Map an HTTP failure without exposing its response body."""
    status_code = response.status_code
    if status_code in {401, 403}:
        reason = "authentication_failed"
    elif status_code in {400, 422}:
        reason = "request_rejected"
    else:
        reason = f"http_{status_code}"
    retryable = status_code in _RETRYABLE_STATUS
    return error_result(
        "upstream_error", reason, f"JEV service returned HTTP {status_code}", retryable
    )


def evaluate_remote(
    config: JevConfig,
    state: dict,
    questions: dict,
    client_factory: Callable[..., httpx.Client] = httpx.Client,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Call JEV with bounded retries and validate its structured response."""
    payload = {"model": config.model, "state": state, "questions": questions}
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    attempts = config.max_retries + 1
    for attempt in range(attempts):
        try:
            with client_factory(timeout=config.timeout_seconds) as client:
                response = client.post(config.endpoint, headers=headers, json=payload)
        except httpx.TimeoutException:
            result = error_result("timeout", "request_timeout", "JEV request timed out", True)
        except httpx.TransportError:
            result = error_result(
                "upstream_error", "transport_error", "JEV transport failed", True
            )
        else:
            if response.status_code >= 400:
                result = _http_error(response)
            else:
                try:
                    return _validate_response(response.json(), questions)
                except (ValueError, TypeError):
                    return error_result(
                        "invalid_response",
                        "invalid_response_schema",
                        "JEV response did not match the required schema",
                    )
        if not result["retryable"] or attempt + 1 >= attempts:
            return result
        delay = min(0.1 * (2**attempt) + random.uniform(0, 0.05), 1.0)
        sleep(delay)
    return error_result("upstream_error", "retry_exhausted", "JEV retry budget exhausted")
