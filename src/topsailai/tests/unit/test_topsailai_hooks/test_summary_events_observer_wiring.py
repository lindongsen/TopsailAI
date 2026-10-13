"""Opt-in summary observer transport contracts. Author: DawsonLin."""
from dataclasses import replace
from pathlib import Path

import pytest

from topsailai.hooks import ConfiguredHookPoint, ConfiguredHooks
from topsailai.hooks.contracts import ValidationError, _thaw_frozen_json
from topsailai.hooks.module_invocation_protocol import (
    ModuleInvocation, build_module_request, parse_module_request,
)
from topsailai.hooks.captured_module_protocol import (
    CapturedModuleLocator, build_captured_module_request, parse_captured_module_request,
)
from topsailai.hooks.hook_point_plan_contracts import ModuleSource
from topsailai.hooks.points.context.summary_contracts import SUMMARY_POINTS
from topsailai.hooks.points.context.summary_payloads import (
    build_summary_hook_context, build_summary_payload,
)
from topsailai.hooks.worker import _invoke_module
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context

ACTIVE = tuple(point for point in SUMMARY_POINTS if point.phase_one_eligible)


def context(point):
    """Build validated metadata for one active or inactive checkpoint."""
    extra = {}
    if point.outcome == 'error':
        extra = dict(error_category='unknown', failed_stage=sorted(point.failed_stages)[0])
    if point.is_apply_error:
        extra['partial_apply_possible'] = True
    base = _context()
    return replace(base, event=replace(base.event, name=point.name, major_version=1,
        payload=build_summary_payload(point, operation_id=base.event.operation_id, **extra)))


def request(invocation, *, captured=False):
    """Build either protocol around the same opted-in immutable invocation."""
    values = dict(correlation_id='corr', channel_token='token', handler_ref='observer:main',
                  context=context(ACTIVE[0]), invocation=invocation)
    if captured:
        return build_captured_module_request(**values, locator=CapturedModuleLocator(
            '/sealed/observer.py', 'observer', 'python_source', 'a' * 64))
    return build_module_request(**values)


def test_legacy_wire_and_arguments_unchanged():
    """False adds no wire key and does not build a summary projection."""
    invocation = ModuleInvocation([1], {'hook_context': 'legacy'})
    assert request(invocation)['invocation'] == {'args': [1], 'kwargs': {'hook_context': 'legacy'}}
    assert _invoke_module(lambda *args, **kwargs: (args, kwargs), invocation) == (
        (1,), {'hook_context': 'legacy'})
    assert not parse_module_request(request(invocation))[4].inject_hook_context


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
def test_exact_bool_at_contract_mapping_and_protocol(value):
    """Lookalike flags must never authorize context injection."""
    point = ACTIVE[0]
    with pytest.raises(ValidationError):
        ModuleInvocation([], {}, inject_hook_context=value)
    with pytest.raises(ValueError):
        ConfiguredHookPoint(point.name, point.definition, inject_hook_context=value)
    with pytest.raises(ValueError):
        ConfiguredHooks.from_mapping({'hooks': {point.name: {
            'definition': {'name': point.name, 'major_version': 1},
            'inject_hook_context': value}}})


def test_reserved_keyword_and_mapping():
    """Only explicit bool opt-in permits worker-owned context keywords."""
    point = ACTIVE[0]
    with pytest.raises(ValidationError):
        ModuleInvocation([], {'hook_context': None}, inject_hook_context=True)
    with pytest.raises(ValueError):
        ConfiguredHookPoint(point.name, point.definition,
                            module_kwargs={'hook_context': None}, inject_hook_context=True)
    configured = ConfiguredHooks.from_mapping({'hooks': {point.name: {
        'definition': {'name': point.name, 'major_version': 1}, 'inject_hook_context': True}}})
    assert configured.hook_points[0].inject_hook_context is True


@pytest.mark.parametrize('captured', [False, True])
def test_opt_in_protocol_roundtrip(captured):
    """Both v2 and captured v3 retain the explicit declaration."""
    invocation = ModuleInvocation([], {}, inject_hook_context=True)
    wire = request(invocation, captured=captured)
    assert wire['invocation']['inject_hook_context'] is True
    parser = parse_captured_module_request if captured else parse_module_request
    assert parser(wire)[4].inject_hook_context is True
    wire['invocation']['inject_hook_context'] = 'true'
    with pytest.raises(ValidationError):
        parser(wire)


@pytest.mark.parametrize('point', ACTIVE, ids=lambda point: point.name)
def test_worker_injects_exact_immutable_safe_context(point):
    """All eight points receive only detached contract-approved scalar metadata."""
    projection = _invoke_module(lambda *, hook_context: hook_context,
        ModuleInvocation([], {}, inject_hook_context=True), context(point))
    plain = _thaw_frozen_json(projection)
    assert set(plain) == {'event_name', 'event_version', 'operation_id', 'payload'}
    assert set(plain['payload']) == point.allowed_fields
    assert plain['event_name'] == plain['payload']['point_name'] == point.name
    assert 'layer' not in plain['payload']
    with pytest.raises(TypeError):
        projection['payload']['outcome'] = 'changed'


def validate_projection(*, hook_context):
    """Apply the domain contract within the point layer after generic injection."""
    return build_summary_hook_context(**_thaw_frozen_json(hook_context))


@pytest.mark.parametrize('point', tuple(point for point in SUMMARY_POINTS if not point.phase_one_eligible))
def test_point_layer_rejects_inactive_summary_points(point):
    """Phase-two metadata is rejected by point-layer validation, not the worker."""
    with pytest.raises(ValidationError):
        _invoke_module(validate_projection, ModuleInvocation([], {}, inject_hook_context=True), context(point))


def test_point_layer_rejects_non_summary_or_extra_fields():
    """Summary validation rejects generic or unknown data before observation."""
    invocation = ModuleInvocation([], {}, inject_hook_context=True)
    with pytest.raises(ValidationError):
        _invoke_module(validate_projection, invocation, _context())
    base = context(ACTIVE[0])
    payload = _thaw_frozen_json(base.event.payload)
    payload['secret'] = '/sensitive/path'
    with pytest.raises(ValidationError):
        _invoke_module(validate_projection, invocation,
                       replace(base, event=replace(base.event, payload=payload)))


def test_module_source_reconstruction_preserves_declaration():
    """Reconstructed source owns the opt-in rather than resetting its default."""
    invocation = ModuleInvocation([], {}, inject_hook_context=True)
    source = ModuleSource('observer', Path('/trusted/observer.py'), 'observer',
                          'python_source', 'observer:main', invocation)
    assert source.invocation.inject_hook_context is True
    assert replace(source).invocation.inject_hook_context is True


def test_backend_handoff_preserves_opt_in(monkeypatch, tmp_path):
    """Captured backend forwards the declaration without changing delivery options."""
    from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_plan_contracts import captured
    from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _backend
    module = captured('module')
    module = replace(module, source=replace(module.source,
        invocation=ModuleInvocation([], {}, inject_hook_context=True)))
    backend = _backend(tmp_path)
    received = {}

    def receive(*args, **kwargs):
        """Capture only the launch handoff without spawning a process."""
        received.update(kwargs)
        return 'received'

    monkeypatch.setattr(backend, '_execute_delivery', receive)
    assert backend.execute_captured_module(module, context(ACTIVE[0]), 1000) == 'received'
    assert received['inject_hook_context'] is True
    assert received['args'] == [] and received['kwargs'] == {}


def test_process_execution_rebuilds_opt_in(monkeypatch, tmp_path):
    """Observe rebuilt invocation at encoding without spawning or mutating transport."""
    from topsailai.hooks import process_execution
    from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _backend
    backend = _backend(tmp_path)
    monkeypatch.setattr(backend, '_preflight', lambda timeout: None)
    monkeypatch.setattr(backend, '_resolve_interpreter', lambda: '/interpreter')
    seen = []

    def capture(**kwargs):
        """Stop after the actual invocation reconstruction and before process launch."""
        seen.append(kwargs['invocation'])
        raise ValidationError('test stop before spawn')

    monkeypatch.setattr(process_execution, 'build_module_request', capture)
    backend._execute_delivery('observer:main', context(ACTIVE[0]), 1000,
                              module=True, inject_hook_context=True)
    assert len(seen) == 1 and seen[0].inject_hook_context is True
