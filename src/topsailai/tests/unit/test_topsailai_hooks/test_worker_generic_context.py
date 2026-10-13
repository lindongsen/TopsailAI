"""Domain-independent bounded Module context regressions. Author: DawsonLin."""

import ast
import builtins
from dataclasses import replace
from pathlib import Path

import pytest

from topsailai.hooks import worker
from topsailai.hooks.contracts import ValidationError, _thaw_frozen_json
from topsailai.hooks.module_invocation_protocol import ModuleInvocation
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context


def test_worker_has_no_point_layer_imports():
    """Check static imports and reject point-layer imports during real invocation."""
    tree = ast.parse(Path(worker.__file__).read_text())
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or '')
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    assert not any(name.startswith('topsailai.hooks.points') for name in modules)


def test_generic_projection_without_business_imports(monkeypatch):
    """Inject detached nested JSON without requiring any summary authorization."""
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        """Reject the exact forbidden dependency while forwarding other imports."""
        if name.startswith('topsailai.hooks.points'):
            pytest.fail('generic worker imported a point layer')
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded)
    payload = {'items': [{'value': 1}], 'enabled': False}
    base = _context()
    context = replace(base, event=replace(base.event, payload=payload))
    projection = worker._invoke_module(lambda *, hook_context: hook_context,
        ModuleInvocation([], {}, inject_hook_context=True), context)
    plain = _thaw_frozen_json(projection)
    assert plain == {'event_name': 'conversation.started', 'event_version': 1,
                     'operation_id': 'operation-1', 'payload': payload}
    payload['items'][0]['value'] = 2
    plain['payload']['items'][0]['value'] = 3
    assert projection['payload']['items'][0]['value'] == 1
    with pytest.raises(TypeError):
        projection['payload']['items'][0]['value'] = 4


@pytest.mark.parametrize('payload', [object(), {'bad': object()}, {'x': 'x' * 32769},
    {'x': list(range(1025))}, {'x': ['雪' * 30000, '雪' * 30000]}])
def test_generic_projection_rejects_unsafe_or_unbounded_values(payload):
    """Reject unsafe representations and aggregate budgets before Module entry."""
    base = _context()
    # Deliberately bypass protocol validation to exercise the worker's own boundary.
    from types import SimpleNamespace
    context = SimpleNamespace(event=SimpleNamespace(name=base.event.name,
        major_version=1, operation_id=base.event.operation_id, payload=payload))
    calls = []
    with pytest.raises(ValidationError):
        worker._invoke_module(lambda **kwargs: calls.append(kwargs),
            ModuleInvocation([], {}, inject_hook_context=True), context)
    assert calls == []


def test_generic_projection_rejects_cycles_and_depth():
    """Cyclic and deeply nested values cannot cross the injected boundary."""
    cycle = []
    cycle.append(cycle)
    deep = []
    for _ in range(17):
        deep = [deep]
    for payload in (cycle, deep):
        test_generic_projection_rejects_unsafe_or_unbounded_values(payload)


def test_legacy_arguments_and_generic_async_injection():
    """Keep noninjected arguments and worker-owned awaiting behavior unchanged."""
    invocation = ModuleInvocation([1], {'hook_context': 'caller-owned'})
    assert worker._invoke_module(lambda *args, **kwargs: (args, kwargs), invocation) == (
        (1,), {'hook_context': 'caller-owned'})

    async def receive(*, hook_context):
        """Return the same safe generic projection through the awaitable path."""
        return _thaw_frozen_json(hook_context)

    value = worker._invoke_module(receive, ModuleInvocation([], {}, inject_hook_context=True),
                                  _context())
    assert value['payload'] == {'value': 1}
