"""Tests for the JEV HTTP client."""

import httpx
import pytest

from topsailai.tools.jev_tool_utils.client import evaluate_remote
from topsailai.tools.jev_tool_utils.models import JevConfig


def config(retries=0):
    """Build deterministic client configuration."""
    return JevConfig("https://example.test/v1/systemone", "secret", "jev-latest", 1, retries, 50, 60000)


def questions():
    """Build one noul question."""
    return {"refund": {"type": "noul", "instructions": "refund?"}}


def factory(handler, records):
    """Build an httpx client factory using a mock transport."""
    def create(**kwargs):
        records.append(kwargs)
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)
    return create


def test_success_preserves_numeric_noul_and_authorization():
    """A valid response is normalized without thresholding noul."""
    seen = {}
    def handler(request):
        seen["authorization"] = request.headers["Authorization"]
        return httpx.Response(200, json={"model": "jev-latest", "answers": {"refund": {"type": "noul", "noul": 0.61}}, "usage": {"input_tokens": 3, "output_tokens": 1}})
    result = evaluate_remote(config(), {"agent2llm_messages": []}, questions(), factory(handler, []))
    assert result["answers"]["refund"]["noul"] == 0.61
    assert seen["authorization"] == "Bearer secret"

@pytest.mark.parametrize("status,retryable", [(401, False), (422, False), (429, True), (503, True)])
def test_http_mapping_and_retry_policy(status, retryable):
    """HTTP failures expose stable categories and allowlisted retryability."""
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="sensitive upstream body")
    result = evaluate_remote(config(1), {}, questions(), factory(handler, []), sleep=lambda _: None)
    assert result["status"] == "upstream_error"
    assert "sensitive" not in result["message"]
    assert len(calls) == (2 if retryable else 1)


def test_timeout_retries_and_stays_bounded():
    """Timeout retries stop at the configured attempt cap."""
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret", request=request)
    result = evaluate_remote(config(1), {}, questions(), factory(handler, []), sleep=lambda _: None)
    assert result["status"] == "timeout"
    assert len(calls) == 2

@pytest.mark.parametrize("body", [
    {},
    {"answers": {}},
    {"answers": {"refund": {"type": "choice", "choice": "yes"}}},
    {"answers": {"refund": {"type": "noul", "noul": "yes"}}},
])
def test_invalid_response_is_not_retried(body):
    """Malformed accepted responses fail without retry."""
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=body)
    result = evaluate_remote(config(2), {}, questions(), factory(handler, []))
    assert result["status"] == "invalid_response"
    assert len(calls) == 1


def test_transport_error_retries_and_returns_safe_error():
    """Transport failures retry within the configured attempt budget."""
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        raise httpx.ConnectError("secret endpoint detail")

    result = evaluate_remote(config(1), {}, questions(), create, sleep=lambda _: None)
    assert result == {
        "status": "upstream_error",
        "reason": "transport_error",
        "message": "JEV transport failed",
        "retryable": True,
    }
    assert len(calls) == 2


def test_unlisted_server_error_is_not_retried():
    """Only explicitly allowlisted HTTP statuses are retried."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500)

    result = evaluate_remote(config(2), {}, questions(), factory(handler, []), sleep=lambda _: None)
    assert result["reason"] == "http_500"
    assert result["retryable"] is False
    assert len(calls) == 1


def test_choice_and_score_answers_preserve_upstream_fields():
    """Choice and score answers retain their complete structured payloads."""
    requested = {
        "route": {"type": "choice", "instructions": "route?", "criteria": {"a": "A"}},
        "risk": {"type": "score", "instructions": "risk?", "criteria": {"1": "low"}},
    }
    answers = {
        "route": {"type": "choice", "choice": "a", "confidence": 0.8, "probabilities": {"a": 0.8}},
        "risk": {"type": "score", "score": 1.0, "legend": {"1": "low"}, "confidence": 0.9, "probabilities": {"1": 0.9}},
    }
    usage = {"input_tokens": 5, "output_tokens": 2}

    def handler(request):
        return httpx.Response(200, json={"model": "resolved", "answers": answers, "usage": usage})

    result = evaluate_remote(config(), {}, requested, factory(handler, []))
    assert result == {"status": "ok", "model": "resolved", "answers": answers, "usage": usage}


@pytest.mark.parametrize("answer", [
    {"type": "choice"},
    {"type": "score", "score": "high"},
    {"type": "noul", "noul": True},
])
def test_rejects_invalid_answer_values(answer):
    """Missing, wrong-typed, and boolean numeric answers are rejected."""
    question_type = answer["type"]
    requested = {"q": {"type": question_type, "instructions": "q?"}}
    if question_type != "noul":
        requested["q"]["criteria"] = {"a": "A"}

    def handler(request):
        return httpx.Response(200, json={"answers": {"q": answer}, "usage": {}})

    assert evaluate_remote(config(), {}, requested, factory(handler, []))["status"] == "invalid_response"


def test_rejects_non_object_json_and_usage():
    """A non-object response or usage field is rejected safely."""
    responses = [httpx.Response(200, json=[]), httpx.Response(200, json={"answers": {"refund": {"type": "noul", "noul": 1}}, "usage": []})]

    def handler(request):
        return responses.pop(0)

    create = factory(handler, [])
    assert evaluate_remote(config(), {}, questions(), create)["status"] == "invalid_response"
    assert evaluate_remote(config(), {}, questions(), create)["status"] == "invalid_response"


@pytest.mark.parametrize("usage", [None, [], {}, {"input_tokens": True, "output_tokens": 1}])
def test_rejects_invalid_usage_shapes_without_raising(usage):
    """Missing or malformed usage is returned as an invalid response."""
    body = {
        "model": "jev-latest",
        "answers": {"refund": {"type": "noul", "noul": 1}},
        "usage": usage,
    }

    def handler(request):
        return httpx.Response(200, json=body)

    result = evaluate_remote(config(), {}, questions(), factory(handler, []))
    assert result["status"] == "invalid_response"
