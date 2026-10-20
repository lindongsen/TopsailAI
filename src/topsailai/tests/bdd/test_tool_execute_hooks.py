"""Tool execution observation HTTP BDD. Author: DawsonLin."""

import json
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

import topsailai.hooks as hooks
from topsailai.ai_base.tool_approval import decorator as approval
from tests.bdd.tool_calls_mock_harness import ToolCallsScenario

scenarios('features/tool_execute_hooks.feature')


@pytest.fixture
def tool_scenario(bdd_tmp_path, monkeypatch):
    """Own the private provider, registry entries and Hook Point configuration."""
    from topsailai.workspace import folder_constants

    monkeypatch.setattr(folder_constants, "FOLDER_WORKSPACE_TASK", str(bdd_tmp_path))
    scenario = ToolCallsScenario(bdd_tmp_path, monkeypatch)
    scenario.marker = bdd_tmp_path / 'observations.jsonl'
    hooks.initialize_hook_points({})
    yield scenario
    hooks.initialize_hook_points({})
    scenario.close()


@given(parsers.parse('a private HTTP tool execution environment with outcome "{outcome}"'))
def prepare_tool(tool_scenario, monkeypatch, outcome):
    """Configure real point Modules and the approval decision seam."""
    scenario = tool_scenario
    scenario.outcome = outcome
    monkeypatch.setenv('LLM_RESPONSE_STREAM', '0')
    config = {}
    for phase in ('before', 'after', 'error'):
        module = scenario.tmp_path / f'{phase}_plugin.py'
        module.write_text(
            'import json\n'
            'def main(**payload):\n'
            f'    with open({str(scenario.marker)!r}, "a") as output:\n'
            f'        output.write(json.dumps(["{phase}", payload]) + "\\n")\n'
            '    return {"veto": True, "replace": "forbidden"}\n'
        )
        config[f'hook__aibase__{phase}__tool_execute'] = {'modules': str(module)}
    hooks.initialize_hook_points(config)

    def decide(self):
        """Record actual approval entry before forwarding to the body."""
        assert not scenario.marker.exists()
        scenario.marker.write_text(json.dumps(['approval', {}]) + '\n')
        return SimpleNamespace(action=approval.ApprovalDecision.ALLOW)

    def target(value=''):
        """Return or raise through the actual registry invocation path."""
        records = [json.loads(line) for line in scenario.marker.read_text().splitlines()]
        assert [row[0] for row in records] == ['approval', 'before']
        assert value == 1
        if outcome == 'error':
            raise ValueError('ORIGINAL-TOOL-ERROR')
        return 'ORIGINAL-TOOL-RESULT'

    monkeypatch.setattr(approval.ToolApprovalInstance, 'decide', decide)
    monkeypatch.setattr(scenario, '_safe_tool', target)
    scenario.script_tool_calls('safe_tool')


@when('the provider requests the configured tool')
def request_tool(tool_scenario):
    """Drive native tool execution and its next request over real HTTP."""
    tool_scenario.continue_conversation('tool-observation', 'execute the tool')
    assert tool_scenario.error is None


@then('approval precedes exactly the matching tool execution observations')
def verify_observations(tool_scenario):
    """Assert phase counts, exact metadata shape and secret exclusion."""
    records = [json.loads(line) for line in tool_scenario.marker.read_text().splitlines()]
    terminal = 'after' if tool_scenario.outcome == 'success' else 'error'
    assert [row[0] for row in records] == ['approval', 'before', terminal]
    for phase, payload in records[1:]:
        extra = {'duration_sec'} if phase == 'after' else {'error_category'} if phase == 'error' else set()
        assert set(payload) == {'tool_name', 'argument_count', 'argument_keys'} | extra
        assert payload['tool_name'] == 'safe_tool'
        assert payload['argument_count'] == 1
        assert payload['argument_keys'] == ['value']
        assert 'ORIGINAL-TOOL' not in json.dumps(payload)
    if terminal == 'error':
        assert records[-1][1]['error_category'] == 'ValueError'


@then('the next provider request contains the original paired tool result')
def verify_wire_pair(tool_scenario):
    """Inspect server-captured request two rather than an internal proxy."""
    requests = tool_scenario.state()['request_bodies']
    assert len(requests) == 2
    assert all(record['body']['stream'] is False for record in requests)
    messages = requests[1]['body']['messages']
    results = [message for message in messages if message['role'] == 'tool']
    assert len(results) == 1
    result = results[0]
    assert result['tool_call_id'] == 'call_bdd_runtime_1'
    expected = 'ORIGINAL-TOOL-RESULT' if tool_scenario.outcome == 'success' else 'ORIGINAL-TOOL-ERROR'
    assert result['content'] == 'topsailai.observation\n' + expected
    owners = [message for message in messages[:messages.index(result)]
              if any(call['id'] == result['tool_call_id'] for call in message.get('tool_calls', []))]
    assert len(owners) == 1
