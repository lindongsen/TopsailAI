"""Real SDK tests of opt-in native SSE fixtures. Author: DawsonLin."""

import json
import threading
from contextlib import contextmanager
from http.client import HTTPConnection

import pytest
from openai import BadRequestError, OpenAI

from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server


def delta(index=0, **fields):
    """Build one native wire delta."""
    return {'tool_calls': [dict(index=index, **fields)]}


@contextmanager
def provider(**options):
    """Own the server, SDK client and exact serving/handler threads."""
    server = create_server(MockServerConfig(**options))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = OpenAI(base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key='mock', max_retries=0)
    try:
        yield client, server
    finally:
        client.close()
        server.shutdown()
        server.stop_handlers(timeout=5)
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def consume(client, stream=True):
    """Consume decoded SDK events until DONE closes the response."""
    response = client.chat.completions.create(
        model='mock', messages=[{'role': 'user', 'content': 'test'}], stream=stream,
    )
    if not stream:
        return response
    with response:
        return list(response)


@pytest.mark.parametrize('native_options', [
    {}, {'stream_tool_call_deltas': None}, {'stream_tool_call_deltas': ()},
    {'stream_tool_call_deltas': (None,)},
], ids=['absent', 'none', 'empty', 'request-none'])
@pytest.mark.parametrize('content_options', [
    {'stream_chunks': ('first', '', '最后')},
    {'stream_response_chunks': (('first', '', '最后'),)},
    {'stream_response_chunks': (), 'stream_chunks': ('first', '', '最后')},
], ids=['global', 'per-request', 'global-fallback'])
def test_content_only_wire_frames_unchanged(native_options, content_options):
    """Preserve exact legacy SSE frame shapes/order without native fixtures."""
    with provider(**content_options, **native_options, report_usage=False) as (_, server):
        connection = HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            connection.request('POST', '/v1/chat/completions', json.dumps({
                'model': 'mock', 'messages': [{'role': 'user', 'content': 'test'}],
                'stream': True,
            }), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            assert response.status == 200
            assert response.getheader('Content-Type') == 'text/event-stream; charset=utf-8'
            wire = response.read().decode('utf-8')
        finally:
            connection.close()
        frames = wire.split('\n\n')
        assert frames[-2:] == ['data: [DONE]', '']
        assert len(frames) == 6
        assert all(frame.startswith('data: ') for frame in frames[:-1])
        chunks = [json.loads(frame[6:]) for frame in frames[:-2]]
        envelope = {key: chunks[0][key] for key in ('id', 'object', 'created', 'model')}
        assert envelope['object'] == 'chat.completion.chunk'
        assert envelope['model'] == 'mock'
        expected = [dict(envelope, choices=[{
            'index': 0, 'delta': {'content': content}, 'finish_reason': None,
        }]) for content in ('first', '', '最后')]
        expected.append(dict(envelope, choices=[{
            'index': 0, 'delta': {}, 'finish_reason': 'stop',
        }]))
        assert chunks == expected


def test_native_delta_without_function_is_accepted():
    """Accept identity-only native deltas without inventing a function field."""
    from topsailai.tests.mock.llm_mock_native_stream import freeze_native_deltas

    item = delta(id='call_identity', type='function')
    frozen = freeze_native_deltas(((item,),))
    assert json.loads(frozen[0][0]) == item
    item['tool_calls'][0]['id'] = 'mutated'
    assert json.loads(frozen[0][0]) == delta(id='call_identity', type='function')


def test_fragmented_interleaved_native_stream_and_fallback():
    """Preserve indices, fragments, finish/usage, content ordering and fallback."""
    native = (
        delta(id='call_a', type='function', function={'name': 'alpha', 'arguments': '{"x":'}),
        delta(1, id='call_b', type='function', function={'name': 'beta', 'arguments': '{}'}),
        delta(function={'arguments': '1}'}),
    )
    with provider(stream_tool_call_deltas=(native, None), stream_response_chunks=(('intro',), ('done',))) as (client, server):
        chunks = consume(client)
        assert chunks[0].choices[0].delta.content == 'intro'
        calls = [chunk.choices[0].delta.tool_calls[0] for chunk in chunks if chunk.choices[0].delta.tool_calls]
        assert [call.index for call in calls] == [0, 1, 0]
        assert calls[0].id == 'call_a' and calls[0].function.name == 'alpha'
        assert calls[1].id == 'call_b' and calls[1].function.name == 'beta'
        assert json.loads(calls[0].function.arguments + calls[2].function.arguments) == {'x': 1}
        assert chunks[-1].choices[0].finish_reason == 'tool_calls'
        assert chunks[-1].usage.total_tokens > 0
        fallback = consume(client)
        assert fallback[0].choices[0].delta.content == 'done'
        assert fallback[-1].choices[0].finish_reason == 'stop'
        assert server.prompt_cache.state()['total_requests'] == 2


def test_native_only_detaches_fixture_and_omits_usage():
    """Native configuration alone enables streaming and captures a detached copy."""
    item = delta(id='original', function={'name': 'alpha', 'arguments': '{}'})
    with provider(stream_tool_call_deltas=((item,),), report_usage=False) as (client, server):
        item['tool_calls'][0]['id'] = 'mutated'
        chunks = consume(client)
        assert chunks[0].choices[0].delta.tool_calls[0].id == 'original'
        assert chunks[-1].choices[0].finish_reason == 'tool_calls'
        assert chunks[-1].usage is None
        assert server.lifecycle_capture.request_handle(1).record["first_item_sent"]


def test_defaults_and_nonstreaming_unchanged():
    """Unconfigured streaming still rejects; non-streaming still returns reply."""
    with provider(reply='legacy') as (client, _):
        with pytest.raises(BadRequestError, match='streaming is not supported'):
            consume(client)
        assert consume(client, stream=False).choices[0].message.content == 'legacy'


@pytest.mark.parametrize('fixture', [
    [], tuple(None for _ in range(129)), ((),), (({},),),
    (({'tool_calls': []},),), (({'tool_calls': {}},),),
    ((delta(True),),), ((delta(-1),),), ((delta(128),),),
    ((delta(0, id=1),),), ((delta(0, id=''),),),
    ((delta(0, type='other'),),), ((delta(0, function=[]),),),
    ((delta(0, function={'unknown': ''}),),),
    ((delta(0, function={'arguments': 1}),),),
    (({'tool_calls': [{'index': 0, 'unknown': 1}]},),),
    (({'tool_calls': [None]},),),
    ((delta(0, function={'arguments': 'x' * 1048577}),),),
])
def test_malformed_native_configuration_rejected(fixture):
    """Reject invalid fixture shapes before opening a server socket."""
    with pytest.raises(ValueError):
        MockServerConfig(stream_tool_call_deltas=fixture)


def test_scripted_errors_precede_native_data():
    """Retain HTTP and SSE error precedence over configured native events."""
    from openai import InternalServerError

    native = ((delta(function={'arguments': '{}'}),),)
    with provider(stream_tool_call_deltas=native, stream_http_error_responses=((503, 'busy'),)) as (client, _):
        with pytest.raises(InternalServerError, match='busy'):
            consume(client)
    with provider(stream_tool_call_deltas=native, stream_error_messages=('failed',)) as (client, _):
        from openai import APIError
        with pytest.raises(APIError, match='failed'):
            consume(client)
