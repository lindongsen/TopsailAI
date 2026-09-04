"""BDD steps for tool startup context message roles."""

import pytest
from pytest_bdd import given, then, when

from tests.bdd.tool_prompt_message_role_harness import (
    NESTED_STARTUP_MARKER,
    TOOL_STARTUP_MARKER,
    ManagerSubagentPromptMessageRoleScenario,
    ToolPromptMessageRoleScenario,
)


@pytest.fixture
def tool_prompt_role_ctx(monkeypatch):
    """Yield one isolated real-HTTP prompt-role scenario."""
    context = ToolPromptMessageRoleScenario(monkeypatch)
    yield context
    context.close()


@given("a tool prompt scenario with a private mock LLM server")
def given_tool_prompt_scenario(tool_prompt_role_ctx):
    """Provide a running private provider and configured agent."""
    assert tool_prompt_role_ctx.server_thread.is_alive()


@when("the agent sends one task through the real LLM client")
def when_agent_sends_task(tool_prompt_role_ctx):
    """Send one task through the real client boundary."""
    tool_prompt_role_ctx.send_task()


@then("the tool startup marker is present in a system message")
def then_marker_is_in_system_message(tool_prompt_role_ctx):
    """Assert the provider receives tool context as a system instruction."""
    system_contents = [
        message.get("content", "")
        for message in tool_prompt_role_ctx.request_messages()
        if message.get("role") == "system"
    ]
    assert any(TOOL_STARTUP_MARKER in content for content in system_contents)


@then("the tool startup marker is absent from every user message")
def then_marker_is_absent_from_user_messages(tool_prompt_role_ctx):
    """Assert no user message carries tool startup context."""
    user_contents = [
        message.get("content", "")
        for message in tool_prompt_role_ctx.request_messages()
        if message.get("role") == "user"
    ]
    assert user_contents
    assert all(TOOL_STARTUP_MARKER not in content for content in user_contents)


@then("the tool prompt mock server received exactly 1 completion request")
def then_server_received_one_request(tool_prompt_role_ctx):
    """Assert one real completion request crossed the HTTP boundary."""
    state = tool_prompt_role_ctx.state()
    assert state["total_requests"] == 1, state
    assert len(state["request_bodies"]) == 1, state


@pytest.fixture
def manager_subagent_prompt_role_ctx(monkeypatch):
    """Yield one isolated real-HTTP Manager-to-Subagent scenario."""
    context = ManagerSubagentPromptMessageRoleScenario(monkeypatch)
    yield context
    context.close()


@given("a manager and subagent prompt scenario with a private mock LLM server")
def given_manager_subagent_prompt_scenario(manager_subagent_prompt_role_ctx):
    """Provide a running provider and a real Manager agent."""
    assert manager_subagent_prompt_role_ctx.server_thread.is_alive()


@when("the manager delegates one task through the real subagent tool")
def when_manager_delegates_task(manager_subagent_prompt_role_ctx):
    """Drive the Manager through its real native delegation tool loop."""
    manager_subagent_prompt_role_ctx.delegate_task()


@then("the nested agent requests contain startup context only in system messages")
def then_nested_marker_is_only_in_system_messages(manager_subagent_prompt_role_ctx):
    """Assert every nested request has one system-context marker copy."""
    groups = manager_subagent_prompt_role_ctx.request_message_groups()
    assert groups
    for messages in groups:
        system_contents = [
            message.get("content", "")
            for message in messages
            if message.get("role") == "system"
        ]
        marker_count = sum(
            content.count(NESTED_STARTUP_MARKER) for content in system_contents
        )
        assert marker_count == 1


@then("the nested agent requests contain no startup marker in user messages")
def then_nested_marker_is_absent_from_user_messages(manager_subagent_prompt_role_ctx):
    """Assert inherited and new user messages contain no startup marker."""
    groups = manager_subagent_prompt_role_ctx.request_message_groups()
    assert groups
    for messages in groups:
        user_contents = [
            message.get("content", "")
            for message in messages
            if message.get("role") == "user"
        ]
        assert user_contents
        assert all(
            NESTED_STARTUP_MARKER not in content for content in user_contents
        )


@then("the nested tool prompt mock server received exactly 3 completion requests")
def then_nested_server_received_three_requests(manager_subagent_prompt_role_ctx):
    """Assert Manager, Subagent, and resumed Manager crossed HTTP."""
    state = manager_subagent_prompt_role_ctx.state()
    assert state["total_requests"] == 3, state
    assert len(state["request_bodies"]) == 3, state
    assert manager_subagent_prompt_role_ctx.result == "done"
