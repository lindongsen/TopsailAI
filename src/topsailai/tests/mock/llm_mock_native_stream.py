"""Bounded native SSE fixture validation. Author: DawsonLin."""

import json


def freeze_native_deltas(responses):
    """Detach JSON fixture deltas into bounded immutable encoded responses."""
    if responses is None:
        return ()
    if not isinstance(responses, tuple) or len(responses) > 128:
        raise ValueError('native responses must be a tuple of at most 128 entries')
    frozen = []
    budget = 0
    for response in responses:
        if response is None:
            frozen.append(None)
            continue
        if not isinstance(response, tuple) or not 0 < len(response) <= 128:
            raise ValueError('native response must contain 1 to 128 deltas')
        encoded = tuple(_encode_delta(delta) for delta in response)
        budget += sum(len(item.encode('utf-8')) for item in encoded)
        if budget > 1048576:
            raise ValueError('native fixture exceeds 1 MiB')
        frozen.append(encoded)
    return tuple(frozen)


def _encode_delta(delta):
    """Validate exact wire shapes before JSON serialization."""
    if type(delta) is not dict or set(delta) != {'tool_calls'}:
        raise ValueError('native delta requires only tool_calls')
    calls = delta['tool_calls']
    if type(calls) is not list or not 0 < len(calls) <= 128:
        raise ValueError('tool_calls requires 1 to 128 entries')
    for call in calls:
        _validate_call(call)
    return json.dumps(delta, ensure_ascii=False, allow_nan=False)


def _validate_call(call):
    """Reject malformed indices, identities and function fragments."""
    if type(call) is not dict or set(call) - {'index', 'id', 'type', 'function'}:
        raise ValueError('invalid native call fields')
    index = call.get('index')
    if type(index) is not int or not 0 <= index < 128:
        raise ValueError('native index must be an integer from 0 to 127')
    for name in ('id', 'type'):
        if name in call and (type(call[name]) is not str or not call[name]):
            raise ValueError('native identity fields must be nonempty strings')
    if 'type' in call and call['type'] != 'function':
        raise ValueError('native type must be function')
    if 'function' not in call:
        return
    function = call['function']
    if type(function) is not dict or set(function) - {'name', 'arguments'}:
        raise ValueError('invalid native function fields')
    if any(type(value) is not str for value in function.values()):
        raise ValueError('native function fragments must be strings')


def response_deltas(config, response_index, content_chunks):
    """Combine content then native deltas without changing content-only defaults."""
    responses = config._native_stream_responses
    native = responses[response_index] if response_index < len(responses) else None
    deltas = [{'content': content} for content in content_chunks]
    deltas.extend(json.loads(item) for item in native or ())
    return deltas, 'tool_calls' if native else 'stop'
