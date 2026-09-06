"""Unique BDD steps for context-summary cached-token warnings."""

from pytest_bdd import given, then, when

from tests.bdd.summarize_cached_token_warning_harness import (
    SummarizeCachedTokenWarningScenario,
)


def _scenario(monkeypatch, request, mode):
    """Create one scenario and register deterministic teardown."""
    context = SummarizeCachedTokenWarningScenario(monkeypatch, mode)
    request.addfinalizer(context.close)
    assert context.server_thread.is_alive()
    return context


@given(
    "a summarize cache-warning environment that will decrease cached tokens",
    target_fixture="summarize_cache_warning_ctx",
)
def given_decreasing_cache_environment(monkeypatch, request):
    """Arrange a positive cached count followed by an unrelated summary prefix."""
    return _scenario(monkeypatch, request, "decrease")


@given(
    "a summarize cache-warning environment that will increase cached tokens",
    target_fixture="summarize_cache_warning_ctx",
)
def given_increasing_cache_environment(monkeypatch, request):
    """Arrange a cold request followed by a summary sharing its prefix."""
    return _scenario(monkeypatch, request, "increase")


@given(
    "a summarize cache-warning environment with equal zero cached tokens",
    target_fixture="summarize_cache_warning_ctx",
)
def given_equal_cache_environment(monkeypatch, request):
    """Arrange unrelated warm-up and summary requests with zero cache hits."""
    return _scenario(monkeypatch, request, "equal")


@given(
    "a summarize cache-warning environment without provider cache usage",
    target_fixture="summarize_cache_warning_ctx",
)
def given_missing_cache_environment(monkeypatch, request):
    """Arrange a provider that omits optional cached-token telemetry."""
    return _scenario(monkeypatch, request, "missing")


@when("context summarization sends a real request to its private provider")
def when_context_summarization_runs(summarize_cache_warning_ctx):
    """Run warm-up traffic and production runtime summarization."""
    summarize_cache_warning_ctx.exercise()


@then("the summarize cache-warning provider received the expected completion requests")
def then_provider_received_requests(summarize_cache_warning_ctx):
    """Assert every expected request crossed the real HTTP boundary once."""
    state = summarize_cache_warning_ctx.state()
    expected = summarize_cache_warning_ctx.expected_request_count()
    assert state["total_requests"] == expected, state
    assert len(state["request_bodies"]) == expected, state
    assert all(record["parsed"] for record in state["request_bodies"]), state


@then("the summary request contains the runtime context and summary instruction")
def then_summary_request_is_complete(summarize_cache_warning_ctx):
    """Assert the final wire request contains context and summarization intent."""
    state = summarize_cache_warning_ctx.state()
    messages = state["request_bodies"][-1]["body"]["messages"]
    expected_context = summarize_cache_warning_ctx.agent.messages
    assert messages[:len(expected_context)] == expected_context, state
    assert any(
        "Summarize this runtime context for the cache warning test." in str(
            message.get("content", "")
        )
        for message in messages[len(expected_context):]
    ), state


@then("the observed cached-token count decreased")
def then_cached_tokens_decreased(summarize_cache_warning_ctx):
    """Prove provider usage updated TokenStat to a strictly smaller value."""
    state = summarize_cache_warning_ctx.state()
    assert summarize_cache_warning_ctx.before is not None
    assert summarize_cache_warning_ctx.after is not None
    assert summarize_cache_warning_ctx.before > summarize_cache_warning_ctx.after
    assert state["requests"][-1]["cached_tokens"] == summarize_cache_warning_ctx.after


@then("the observed cached-token count increased")
def then_cached_tokens_increased(summarize_cache_warning_ctx):
    """Prove the summary reused the complete warm request prefix."""
    state = summarize_cache_warning_ctx.state()
    assert summarize_cache_warning_ctx.before is not None
    assert summarize_cache_warning_ctx.after is not None
    assert summarize_cache_warning_ctx.after > summarize_cache_warning_ctx.before
    assert state["requests"][-1]["cached_tokens"] == summarize_cache_warning_ctx.after


@then("the observed cached-token counts are both zero")
def then_cached_tokens_equal_zero(summarize_cache_warning_ctx):
    """Prove equality at zero does not satisfy the warning predicate."""
    state = summarize_cache_warning_ctx.state()
    assert summarize_cache_warning_ctx.before == 0
    assert summarize_cache_warning_ctx.after == 0
    assert state["requests"][-1]["cached_tokens"] == 0


@then("the resulting cached-token count is unavailable")
def then_cached_tokens_unavailable(summarize_cache_warning_ctx):
    """Prove omitted provider telemetry is represented as unknown after summary."""
    assert summarize_cache_warning_ctx.server.config.report_cache_usage is False
    assert summarize_cache_warning_ctx.after is None


@then("one exact cached-token decrease warning was printed")
def then_one_exact_warning(summarize_cache_warning_ctx):
    """Assert warning cardinality and exact interpolated text."""
    expected = (
        "[summarize] cached tokens decreased after summarization: "
        f"cached_tokens_before={summarize_cache_warning_ctx.before}, "
        f"cached_tokens_after={summarize_cache_warning_ctx.after}"
    )
    assert summarize_cache_warning_ctx.warnings == [expected]


@then("no cached-token decrease warning was printed")
def then_no_warning(summarize_cache_warning_ctx):
    """Assert normal and unknown telemetry paths do not warn."""
    assert summarize_cache_warning_ctx.warnings == []


@then("context summarization returned a non-empty answer")
def then_summary_answer_returned(summarize_cache_warning_ctx):
    """Assert warning observation never prevents a successful summary."""
    assert summarize_cache_warning_ctx.summary_answer
