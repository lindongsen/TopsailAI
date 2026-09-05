"""Unique BDD steps for OpenAI SDK client reuse."""

import pytest
from pytest_bdd import given, then, when

from tests.bdd.openai_client_reuse_harness import OpenAIClientReuseScenario


@pytest.fixture
def openai_client_reuse_ctx(monkeypatch):
    """Yield one isolated real-HTTP client-reuse scenario."""
    context = OpenAIClientReuseScenario(monkeypatch)
    yield context
    context.close()


@given("an OpenAI client reuse environment with a private mock LLM server")
def given_openai_client_reuse_environment(openai_client_reuse_ctx):
    """Provide one private provider and one production Agent2LLM model."""
    assert openai_client_reuse_ctx.server_thread.is_alive()


@when("Agent2LLM and runtime summarization each send one real LLM request")
def when_openai_client_reuse_paths_run(openai_client_reuse_ctx):
    """Exercise both production LLM paths against the loopback provider."""
    openai_client_reuse_ctx.exercise_both_paths()


@then("the OpenAI client reuse mock server received exactly 2 completion requests")
def then_openai_client_reuse_server_count(openai_client_reuse_ctx):
    """Assert both paths crossed the provider boundary exactly once."""
    state = openai_client_reuse_ctx.state()
    assert state["total_requests"] == 2, state
    assert len(state["request_bodies"]) == 2, state
    assert all(record["parsed"] for record in state["request_bodies"]), state


@then("the Agent2LLM and summary request bodies reached the mock server")
def then_openai_client_reuse_request_bodies(openai_client_reuse_ctx):
    """Assert the provider observed messages unique to both production paths."""
    state = openai_client_reuse_ctx.state()
    request_messages = [
        record["body"]["messages"] for record in state["request_bodies"]
    ]
    assert any(
        {"role": "user", "content": "agent2llm identity request"} in messages
        for messages in request_messages
    ), state
    assert any(
        any(
            message.get("role") == "user"
            and "runtime context to summarize" in str(message.get("content", ""))
            for message in messages
        )
        for messages in request_messages
    ), state
    assert any(
        any(
            message.get("role") == "user"
            and "Summarize this runtime context." in str(message.get("content", ""))
            for message in messages
        )
        for messages in request_messages
    ), state


@then("runtime summarization uses a distinct OpenAI client lease")
def then_openai_client_reuse_distinct_leases(openai_client_reuse_ctx):
    """Assert separate model owners receive separate lease objects."""
    assert (
        openai_client_reuse_ctx.summary_handle()
        is not openai_client_reuse_ctx.agent_handle()
    )


@then("runtime summarization reuses the Agent2LLM root OpenAI SDK client instance")
def then_openai_client_reuse_root_identity(openai_client_reuse_ctx):
    """Assert both leases refer to the same root ``openai.OpenAI`` object."""
    assert (
        openai_client_reuse_ctx.summary_handle().client
        is openai_client_reuse_ctx.agent_handle().client
    )


@then("runtime summarization reuses the Agent2LLM chat completions instance")
def then_openai_client_reuse_completions_identity(openai_client_reuse_ctx):
    """Assert both paths expose the same SDK chat-completions resource."""
    assert (
        openai_client_reuse_ctx.summary_chat.llm_model.model
        is openai_client_reuse_ctx.agent.llm_model.model
    )
