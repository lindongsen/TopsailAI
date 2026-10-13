"""Internal v2 Module wire vocabulary, without worker or Runtime adoption.

Author: DawsonLin
Unsupported normal output is unavailable, not an execution error.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from topsailai.hooks.contracts import (
    HookContext, ValidationError, _snapshot_json, _thaw_frozen_json,
)
from topsailai.hooks.result_contracts import ReturnedValue, ResultDiagnostic
from topsailai.hooks.validation import freeze_json
from topsailai.hooks.worker_protocol import (
    ProtocolLimits, build_request, parse_request, encode_frame,
)

MODULE_PROTOCOL_VERSION = 2
_REQUEST_KEYS = frozenset(('protocol_version', 'correlation_id', 'channel_token',
                           'handler_ref', 'context', 'invocation'))
_RESPONSE_KEYS = frozenset(('protocol_version', 'correlation_id', 'channel_token',
                            'delivery_id', 'status', 'returned', 'error_category',
                            'transport_diagnostic'))
_RETURN_KEYS = frozenset(('present', 'representation', 'value', 'reference'))


def _text(value: Any) -> None:
    """Check exact bounded metadata before comparison or formatting."""
    if type(value) is not str or not value or len(value) > 128:
        raise ValidationError('invalid module protocol metadata')


def _envelope(value: Any, keys: frozenset[str], limit: int) -> dict:
    """Detach the entire envelope under one aggregate budget."""
    safe = freeze_json(value, max_bytes=limit)
    if type(safe) is not dict or set(safe) != keys:
        raise ValidationError('invalid module protocol envelope')
    if type(safe['protocol_version']) is not int or safe['protocol_version'] != MODULE_PROTOCOL_VERSION:
        raise ValidationError('invalid module protocol version')
    return safe


def _main(value: Any) -> None:
    """Validate Unicode Python module components without importing anything."""
    if type(value) is not str or len(value) > 32768 or value.count(':') != 1:
        raise ValidationError('invalid module main reference')
    module, entry = value.split(':')
    if entry != 'main' or not all(part.isidentifier() for part in module.split('.')):
        raise ValidationError('invalid module main reference')


@dataclass(frozen=True, slots=True)
class ModuleInvocation:
    """Own deeply immutable safe arguments under a single request budget."""
    args: Any
    kwargs: Any
    inject_hook_context: bool = False

    def __post_init__(self) -> None:
        """Reject lookalikes before iterating and detach both fields together."""
        if type(self.args) not in (list, tuple) or type(self.kwargs) is not dict:
            raise ValidationError('invalid module invocation containers')
        if type(self.inject_hook_context) is not bool:
            raise ValidationError('invalid context injection declaration')
        if self.inject_hook_context and 'hook_context' in self.kwargs:
            raise ValidationError('reserved context injection keyword')
        if len(self.args) > 1024 or len(self.kwargs) > 1024:
            raise ValidationError('module invocation exceeds maximum item count')
        owned = _snapshot_json({'args': list(self.args), 'kwargs': self.kwargs},
                               immutable=True, max_bytes=131072)
        object.__setattr__(self, 'args', owned['args'])
        object.__setattr__(self, 'kwargs', owned['kwargs'])


def build_module_request(*, correlation_id: str, channel_token: str, handler_ref: str,
                         context: HookContext, invocation: ModuleInvocation,
                         limits: ProtocolLimits = ProtocolLimits()) -> dict:
    """Build and admit a bounded v2 invocation without spawning a process."""
    if type(context) is not HookContext or type(invocation) is not ModuleInvocation:
        raise ValidationError('invalid module request records')
    _text(correlation_id)
    _text(channel_token)
    _main(handler_ref)
    wire = build_request(correlation_id=correlation_id, channel_token=channel_token,
                         handler_ref=handler_ref, context=context)
    wire['protocol_version'] = MODULE_PROTOCOL_VERSION
    wire['invocation'] = {'args': _thaw_frozen_json(invocation.args),
                          'kwargs': _thaw_frozen_json(invocation.kwargs)}
    if invocation.inject_hook_context:
        wire['invocation']['inject_hook_context'] = True
    parse_module_request(wire, limits=limits)
    return wire


def parse_module_request(value: Any, *, limits: ProtocolLimits = ProtocolLimits()) -> tuple:
    """Validate v2 before explicitly adapting only framework context to v1."""
    safe = _envelope(value, _REQUEST_KEYS, limits.request_bytes)
    _text(safe['correlation_id'])
    _text(safe['channel_token'])
    _main(safe['handler_ref'])
    raw = safe.pop('invocation')
    if type(raw) is not dict or set(raw) not in ({'args', 'kwargs'}, {'args', 'kwargs', 'inject_hook_context'}) or type(raw['args']) is not list:
        raise ValidationError('invalid module invocation envelope')
    invocation = ModuleInvocation(raw['args'], raw['kwargs'],
                                  inject_hook_context=raw.get('inject_hook_context', False))
    safe['protocol_version'] = 1
    correlation, token, ref, context = parse_request(safe)
    return correlation, token, ref, context, invocation


def build_module_response(*, correlation_id: str, channel_token: str, delivery_id: str,
                          value: Any = None, status: str = 'success',
                          error_category: str | None = None,
                          limits: ProtocolLimits = ProtocolLimits()) -> dict:
    """Encode safe normal output or compact unavailable presence, never truncate."""
    for metadata in (correlation_id, channel_token, delivery_id):
        _text(metadata)
    if type(status) is not str or status not in ('success', 'error'):
        raise ValidationError('invalid module response status')
    if status == 'error':
        _text(error_category)
    elif error_category is not None:
        raise ValidationError('success cannot have execution error')
    wire = dict(protocol_version=MODULE_PROTOCOL_VERSION, correlation_id=correlation_id,
                channel_token=channel_token, delivery_id=delivery_id, status=status,
                returned=dict(present=status == 'success', representation='unavailable',
                              value=None, reference=None),
                error_category=error_category, transport_diagnostic=None)
    if status == 'success':
        try:
            wire['returned'] = dict(present=True, representation='transported',
                                    value=freeze_json(value, max_bytes=limits.response_bytes), reference=None)
            encode_frame(wire, limits.response_bytes)
        except ValidationError:
            wire['returned'] = dict(present=True, representation='unavailable', value=None, reference=None)
            wire['transport_diagnostic'] = 'return_unavailable'
    encode_frame(wire, limits.response_bytes)
    validate_module_response(wire, correlation_id=correlation_id,
                             channel_token=channel_token, delivery_id=delivery_id, limits=limits)
    return wire


def validate_module_response(value: Any, *, correlation_id: str, channel_token: str,
                             delivery_id: str, limits: ProtocolLimits = ProtocolLimits()) -> dict:
    """Validate wire contradictions and expose detached typed return metadata."""
    safe = _envelope(value, _RESPONSE_KEYS, limits.response_bytes)
    for key, expected in (('correlation_id', correlation_id), ('channel_token', channel_token),
                          ('delivery_id', delivery_id)):
        _text(expected)
        _text(safe[key])
        if safe[key] != expected:
            raise ValidationError('module response correlation mismatch')
    status = safe['status']
    if type(status) is not str or status not in ('success', 'error'):
        raise ValidationError('invalid module response status')
    raw = safe['returned']
    if type(raw) is not dict or set(raw) != _RETURN_KEYS:
        raise ValidationError('invalid module return envelope')
    if type(raw['representation']) is not str or raw['representation'] not in ('transported', 'unavailable'):
        raise ValidationError('invalid module wire representation')
    returned = ReturnedValue(**raw)
    diagnostic = safe['transport_diagnostic']
    category = safe['error_category']
    if status == 'error':
        _text(category)
        if returned.present or diagnostic is not None:
            raise ValidationError('invalid module error return')
    else:
        if not returned.present or category is not None:
            raise ValidationError('invalid module success return')
        expected = 'return_unavailable' if returned.representation == 'unavailable' else None
        if diagnostic != expected:
            raise ValidationError('invalid module transport diagnostic')
    safe['returned'] = returned
    safe['transport_diagnostic'] = (
        ResultDiagnostic('return_unavailable', '') if diagnostic is not None else None
    )
    return safe
