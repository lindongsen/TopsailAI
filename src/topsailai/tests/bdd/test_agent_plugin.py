"""Acceptance of opt-in assistant tool discovery; author: DawsonLin."""

from pytest_bdd import given, when, then, parsers, scenarios

from tests.bdd.agent_plugin_harness import inspect_plugin

scenarios("features/agent_plugin.feature")


@given(parsers.parse('assistant plugin configuration is "{configuration}"'), target_fixture="configuration")
def plugin_configuration(configuration):
    """Select an operator's explicit configuration."""
    return configuration


@when("the tool registry starts in a fresh process", target_fixture="registry")
def start_registry(configuration, bdd_tmp_path):
    """Discover actual tools without calling an external model."""
    return inspect_plugin(bdd_tmp_path, configuration != "absent",
                          enabled="" if configuration == "default-flag" else "*",
                          disabled="agent_tool" if configuration == "disabled" else "")


@then(parsers.parse('assistant tool availability is "{availability}" and core story helpers remain usable'))
def assert_availability(registry, availability):
    """Assert exact names, registration-owned guardrail, and independent core helper."""
    assert registry["story_callable"]
    expected = sorted("agent_tool-" + name for name in
                      ("WritingAssistant", "ProgrammingAssistant", "WritingAssistantMultiTasks"))
    assert registry["names"] == (expected if availability == "present" else [])
    if availability == "present":
        assert registry["source"] == "topsailai.plugins.tools.agent_tool"
        assert "Unless the user explicitly" in registry["prompt"]
