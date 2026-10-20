"""Tool execution observation HTTP BDD. Author: DawsonLin."""

import json
import math
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
    try:
        yield scenario
    finally:
        try:
            hooks.initialize_hook_points({})
        finally:
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


@given(parsers.parse('a private SSE tool execution environment with outcome "{outcome}"'))
def prepare_sse_tool(tool_scenario, monkeypatch, outcome):
    """Reuse real tool/Hook configuration with streaming enabled at startup."""
    prepare_tool(tool_scenario, monkeypatch, outcome)
    monkeypatch.setenv('LLM_RESPONSE_STREAM', '1')


@given('the provider streams a native call with arguments split across three deltas')
def script_native_fragments(tool_scenario, monkeypatch):
    """Observe decoded chunks without replacing production argument assembly."""
    from topsailai.ai_base.llm_pool.openai_client_pool import OpenAIResponseAdapter

    tool_scenario.fragments = []
    tool_scenario.chunk_finishes = []
    original = OpenAIResponseAdapter.get_stream_delta

    def record_chunk(chunk):
        """Delegate unchanged while retaining decoded wire evidence."""
        delta = original(chunk)
        tool_scenario.chunk_finishes.extend(choice.finish_reason for choice in chunk.choices)
        if delta and delta.tool_calls:
            tool_scenario.fragments.extend(call.model_dump() for call in delta.tool_calls)
        return delta

    monkeypatch.setattr(OpenAIResponseAdapter, 'get_stream_delta', staticmethod(record_chunk))
    first = {'index': 0, 'id': 'call_bdd_runtime_1', 'type': 'function',
             'function': {'name': 'safe_tool', 'arguments': '{"val'}}
    remaining = tuple({'tool_calls': [{'index': 0, 'function': {'arguments': fragment}}]}
                      for fragment in ('ue": ', '1}'))
    tool_scenario.stream_tool_call_deltas = (({'tool_calls': [first]}, *remaining), None)


@then('the client consumes native SSE deltas and assembles the configured tool arguments')
def verify_native_fragments(tool_scenario):
    """Require real SDK chunks and the original assembled native action."""
    fragments = tool_scenario.fragments
    assert len(fragments) == 3
    assert [call['index'] for call in fragments] == [0, 0, 0]
    assert fragments[0]['id'] == 'call_bdd_runtime_1'
    assert fragments[0]['function']['name'] == 'safe_tool'
    assert [call['function']['arguments'] for call in fragments] == ['{"val', 'ue": ', '1}']
    assert 'tool_calls' in tool_scenario.chunk_finishes
    assert 'stop' in tool_scenario.chunk_finishes
    state = tool_scenario.state()
    assert state['total_requests'] == 2
    assert state['dropped_request_body_count'] == 0
    assert tool_scenario.first_parsed_response
    messages = state['request_bodies'][1]['body']['messages']
    call = next(message['tool_calls'][0] for message in messages if message.get('tool_calls'))
    assert call['id'] == 'call_bdd_runtime_1'
    assert call['function']['name'] == 'safe_tool'
    assert json.loads(call['function']['arguments']) == {'value': 1}


@then('exactly the matching terminal observation exposes only permitted metadata')
def verify_terminal_metadata(tool_scenario):
    """Check finite timing or bounded classification in the exact-key payload."""
    verify_observations(tool_scenario)
    records = [json.loads(line) for line in tool_scenario.marker.read_text().splitlines()]
    payload = records[-1][1]
    if tool_scenario.outcome == 'success':
        duration = payload['duration_sec']
        assert type(duration) in (int, float) and math.isfinite(duration) and duration >= 0
    else:
        assert payload['error_category'] == 'ValueError'
        assert len(payload['error_category']) <= 128


@then('the next streaming provider request contains the original paired tool result')
def verify_streaming_wire_pair(tool_scenario):
    """Assert native schema, transport mode and unchanged exact result ownership."""
    requests = tool_scenario.state()['request_bodies']
    assert len(requests) == 2
    for request in requests:
        body = request['body']
        assert body['stream'] is True
        assert any(tool['function']['name'] == 'safe_tool' for tool in body['tools'])
        assert body['tool_choice'] == 'auto'
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
    assert 'forbidden' not in json.dumps(messages)
    assert tool_scenario.result
