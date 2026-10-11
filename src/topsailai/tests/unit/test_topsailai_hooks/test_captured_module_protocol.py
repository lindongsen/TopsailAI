"""Exact bounded captured invocation envelopes. Author: DawsonLin."""
import copy
import pytest
from topsailai.hooks.captured_module_protocol import (
    CapturedModuleLocator, build_captured_module_request, parse_captured_module_request,
)
from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.module_invocation_protocol import ModuleInvocation
from topsailai.hooks.worker_protocol import ProtocolLimits
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context


def request():
    """Build an independent valid address and invocation."""
    return build_captured_module_request(
        locator=CapturedModuleLocator('/sealed/entry-000000/plugin.py', 'plugin', 'python_source', 'a'*64),
        correlation_id='corr', channel_token='token', handler_ref='pkg.plugin:main',
        context=_context(), invocation=ModuleInvocation([False], {'x': None}),
    )


def test_roundtrip_detachment():
    """Address and invocation remain distinct from registered aliases."""
    wire = request()
    before = copy.deepcopy(wire)
    parsed = parse_captured_module_request(wire)
    assert wire == before and parsed[2] == 'pkg.plugin:main'
    assert parsed[-1].logical_name == 'plugin'
    wire['captured']['path'] = '/different'
    assert parsed[-1].path == '/sealed/entry-000000/plugin.py'


@pytest.mark.parametrize('key,value', [
    ('path', None), ('path', ''), ('path', 'relative.py'), ('path', '/x\x00'), ('path', '/'+'x'*32768),
    ('logical_name', None), ('logical_name', 'a.b'), ('kind', None), ('kind', 'script'),
    ('content_sha256', None), ('content_sha256', 'A'*64), ('content_sha256', 'a'*63),
])
def test_locator_rejection(key, value):
    """Type checks precede dependent operations without coercion."""
    fields = request()['captured']
    fields[key] = value
    with pytest.raises(ValidationError):
        CapturedModuleLocator(**fields)


@pytest.mark.parametrize('key,value', [
    ('protocol_version', True), ('protocol_version', 2), ('captured', None),
    ('captured', {}), ('captured', []), ('extra', 1), ('invocation', {}),
])
def test_wire_rejection(key, value):
    """Malformed complete envelopes fail before loading anything."""
    wire = request()
    wire[key] = value
    with pytest.raises(ValidationError):
        parse_captured_module_request(wire)


def test_uncorrelated_and_aggregate_limit():
    """Logical import identity and one aggregate budget constrain addresses."""
    wire = request()
    wire['captured']['logical_name'] = 'different'
    with pytest.raises(ValidationError):
        parse_captured_module_request(wire)
    with pytest.raises(ValidationError):
        parse_captured_module_request(request(), limits=ProtocolLimits(256, 65536))
    with pytest.raises(ValidationError):
        build_captured_module_request(locator=object())
    with pytest.raises(ValidationError):
        parse_captured_module_request([])
