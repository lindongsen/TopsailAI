"""Safe v2 Module wire contracts, independent of worker adoption.

Author: DawsonLin
"""
import copy
import json
import struct
import pytest
from topsailai.hooks.contracts import ValidationError, _thaw_frozen_json
from topsailai.hooks.module_invocation_protocol import (
    MODULE_PROTOCOL_VERSION, ModuleInvocation, build_module_request,
    parse_module_request, build_module_response, validate_module_response,
)
from topsailai.hooks.worker_protocol import (
    PROTOCOL_VERSION, ProtocolLimits, build_request, parse_request, encode_frame, decode_frame,
)
from topsailai.tests.unit.test_topsailai_hooks.test_process_backend import _context


class Hostile:
    """Fail if an unsupported object is observed rather than rejected by type."""
    def __repr__(self):
        """Forbid formatting."""
        raise AssertionError("secret repr")
    __str__ = __repr__
    def __bool__(self):
        """Forbid truthiness."""
        raise AssertionError("bool")
    def __eq__(self, other):
        """Forbid equality."""
        raise AssertionError("eq")
    def __hash__(self):
        """Forbid hashing."""
        raise AssertionError("hash")
    def __deepcopy__(self, memo):
        """Forbid copying."""
        raise AssertionError("copy")


class SubList(list):
    """Reject even JSON-looking subclasses."""


def request(**changes):
    """Build a valid v2 request."""
    fields = dict(correlation_id="corr", channel_token="token", handler_ref="包.mod:main",
                  context=_context(), invocation=ModuleInvocation([None, False], {"参数": [1]}))
    fields.update(changes)
    return build_module_request(**fields)


def response(value=None, **changes):
    """Build one normal response with independently selected output."""
    fields = dict(correlation_id="corr", channel_token="token", delivery_id="delivery-1", value=value)
    fields.update(changes)
    return build_module_response(**fields)


def validate(value, **changes):
    """Validate against expected transport correlation."""
    fields = dict(correlation_id="corr", channel_token="token", delivery_id="delivery-1")
    fields.update(changes)
    return validate_module_response(value, **fields)


def test_versions_roundtrip_and_owned_arguments():
    """v1 stays byte-compatible and v2 owns an immutable argument snapshot."""
    old = build_request(correlation_id="c", channel_token="t", handler_ref="x:f", context=_context())
    before = encode_frame(old, 131072)
    assert PROTOCOL_VERSION == 1 and MODULE_PROTOCOL_VERSION == 2
    assert encode_frame(old, 131072) == before
    assert parse_request(decode_frame(before, 131072))[2] == "x:f"
    args, kwargs = [[1]], {"x": [2]}
    invocation = ModuleInvocation(args, kwargs)
    args[0].append(3); kwargs["x"].append(4)
    assert _thaw_frozen_json(invocation.args) == [[1]]
    assert _thaw_frozen_json(invocation.kwargs) == {"x": [2]}
    parsed = parse_module_request(decode_frame(encode_frame(request(), 131072), 131072))
    assert parsed[:3] == ("corr", "token", "包.mod:main")
    assert _thaw_frozen_json(parsed[4].args) == [None, False]


@pytest.mark.parametrize("value", [Hostile(), SubList(), (1,), {1: 2}, float('nan'), float('inf'), '\ud800', 'x'*32769, [0]*1025])
def test_unsupported_args_and_normal_unavailable_returns(value):
    """No rejected output becomes an execution error or leaks object data."""
    with pytest.raises(ValidationError):
        ModuleInvocation([value], {})
    wire = response(value)
    result = validate(wire)
    assert result['status'] == 'success'
    assert result['returned'].present is True
    assert result['returned'].representation == 'unavailable'
    assert result['transport_diagnostic'].category == 'return_unavailable'


@pytest.mark.parametrize("value", [False, None, 0, '', [], {}, {'error': 1}, {'字': [True, 1.5]}])
def test_transported_values(value):
    """Normal content retains transported presence regardless of its value."""
    result = validate(response(value))
    assert result['returned'].representation == 'transported'
    assert result['returned'].present is True
    assert result['returned'].value == value
    assert result['error_category'] is None


def test_cycles_depth_and_aggregate_budget():
    """Combined request admission rejects cycles and shared-budget overflow."""
    cycle = []; cycle.append(cycle)
    deep = 1
    for _ in range(18):
        deep = [deep]
    for value in (cycle, deep):
        with pytest.raises(ValidationError):
            ModuleInvocation([value], {})
        assert validate(response(value))['returned'].representation == 'unavailable'
    with pytest.raises(ValidationError):
        ModuleInvocation([0]*600, {str(i): 0 for i in range(600)})
    with pytest.raises(ValidationError):
        ModuleInvocation(["x"*32768]*3, {"x": "x"*32768})


@pytest.mark.parametrize('args,kwargs', [(Hostile(), {}), ([], Hostile()), ([], {1: 2}), (SubList(), {}), ([], {'x': Hostile()})])
def test_top_level_admission(args, kwargs):
    """Admission never coerces caller containers."""
    with pytest.raises(ValidationError):
        ModuleInvocation(args, kwargs)


@pytest.mark.parametrize('ref', ['a:f', 'a..b:main', 'a²:main', ':main', 'a:main:main', Hostile()])
def test_main_reference(ref):
    """Main references require exact dotted Python identifiers."""
    with pytest.raises(ValidationError):
        request(handler_ref=ref)


@pytest.mark.parametrize('key,value', [('protocol_version', True), ('protocol_version', 1), ('correlation_id', Hostile()), ('channel_token',''), ('invocation', {}), ('context', {}), ('extra', 1)])
def test_bad_request_fields(key, value):
    """Exact v2 envelope/type checks precede metadata comparisons."""
    wire = request(); wire[key] = value
    with pytest.raises(ValidationError):
        parse_module_request(wire)


@pytest.mark.parametrize('key,value', [('protocol_version',True), ('protocol_version',1), ('correlation_id',Hostile()), ('correlation_id','wrong'), ('channel_token','wrong'), ('delivery_id','wrong'), ('status',Hostile()), ('status','invalid_output'), ('error_category','unexpected'), ('transport_diagnostic','unexpected'), ('extra',1)])
def test_bad_response_fields(key, value):
    """Malformed responses are protocol failures rather than normal return."""
    wire = response(); wire[key] = value
    with pytest.raises(ValidationError):
        validate(wire)


@pytest.mark.parametrize('key,value', [('present',False), ('present',1), ('representation','direct'), ('representation','reference'), ('reference','fake'), ('value',Hostile()), ('extra',1)])
def test_bad_return_fields(key, value):
    """Wire permits transported/unavailable only with consistent presence."""
    wire = response(); wire['returned'][key] = value
    with pytest.raises(ValidationError):
        validate(wire)


def test_error_and_compact_boundary():
    """Errors are absent returns; oversized normal results fall back, never truncate."""
    wire = response(status='error', error_category='plugin_exception')
    assert validate(wire)['returned'].present is False
    for change in ({'error_category': None}, {'error_category': Hostile()}, {'error_category': 'x'*129}):
        bad = dict(wire, **change)
        with pytest.raises(ValidationError):
            validate(bad)
    bad = copy.deepcopy(wire); bad['returned']['present'] = True
    with pytest.raises(ValidationError):
        validate(bad)
    compact = response(Hostile())
    size = len(encode_frame(compact, 65536))-4
    limits = ProtocolLimits(response_bytes=size)
    assert response('x'*1000, limits=limits) == compact
    with pytest.raises(ValidationError):
        response(Hostile(), limits=ProtocolLimits(response_bytes=size-1))
    transported = response(False)
    exact = len(encode_frame(transported, 65536))-4
    assert response(False, limits=ProtocolLimits(response_bytes=exact)) == transported


def test_invalid_metadata_and_shapes():
    """Helpers reject lookalikes without formatting untrusted inputs."""
    for bad in (None, [], Hostile()):
        with pytest.raises(ValidationError): parse_module_request(bad)
        with pytest.raises(ValidationError): validate(bad)
    with pytest.raises(ValidationError): request(context=Hostile())
    with pytest.raises(ValidationError): request(invocation=Hostile())
    with pytest.raises(ValidationError): response(status='other')
    with pytest.raises(ValidationError): validate(response(), correlation_id=Hostile())


def test_builder_error_priority_and_host_interrupt(monkeypatch):
    """Execution errors are explicit; host cancellation must propagate unchanged."""
    with pytest.raises(ValidationError, match='execution error'):
        response(error_category='secret')
    from topsailai.hooks import module_invocation_protocol as codec
    def interrupted(*args, **kwargs):
        """Model host cancellation, not transfer rejection."""
        raise KeyboardInterrupt
    monkeypatch.setattr(codec, 'freeze_json', interrupted)
    with pytest.raises(KeyboardInterrupt):
        response(1)


def test_request_final_boundary_and_immutable_snapshot():
    """Metadata consumes the same final envelope budget; snapshots cannot mutate."""
    wire = request()
    size = len(encode_frame(wire, 131072))-4
    assert request(limits=ProtocolLimits(request_bytes=size)) == wire
    with pytest.raises(ValidationError):
        request(limits=ProtocolLimits(request_bytes=size-1))
    inv = ModuleInvocation(([1],), {'x': [2]})
    with pytest.raises(TypeError):
        inv.args[0][0] = 2
    with pytest.raises(TypeError):
        inv.kwargs['x'] = 1
    with pytest.raises(AttributeError):
        inv.args = ()
    assert not hasattr(inv, '__dict__')
    expected = json.dumps(build_request(correlation_id='c', channel_token='t', handler_ref='x:f', context=_context()),
                          ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    assert encode_frame(json.loads(expected), 131072) == struct.pack('!I', len(expected)) + expected


@pytest.mark.parametrize('patch', [
    {'returned': None}, {'returned': {'present': True}},
    {'returned': {'present': True, 'representation': 'unavailable', 'value': 1, 'reference': None}},
    {'returned': {'present': False, 'representation': 'transported', 'value': None, 'reference': None}},
    {'transport_diagnostic': {'category': 'return_unavailable'}},
])
def test_additional_response_contradictions(patch):
    """Reject malformed or contradictory returned-value envelopes."""
    with pytest.raises(ValidationError):
        validate(dict(response(), **patch))
    wire = response(status='error', error_category='plugin_exception')
    wire['transport_diagnostic'] = 'return_unavailable'
    with pytest.raises(ValidationError):
        validate(wire)


@pytest.mark.parametrize('raw', [None, {'args': [], 'kwargs': {}, 'extra': 1}, {'args': {}, 'kwargs': {}}, {'args': [], 'kwargs': []}])
def test_invocation_wire_shapes(raw):
    """Do not normalize malformed wire invocation shapes."""
    wire = request(); wire['invocation'] = raw
    with pytest.raises(ValidationError):
        parse_module_request(wire)


def test_return_subclasses_and_exact_limits():
    """Subclass serializers and oversized envelopes cannot expand the safe subset."""
    class SubString(str):
        """A string subclass is not admitted."""
    class SubInt(int):
        """An integer subclass is not admitted."""
    class SubDict(dict):
        """A mapping subclass is not admitted."""
    for bad in (SubString('x'), SubInt(1), SubDict(), {'x': Hostile()}, 10**5000):
        with pytest.raises(ValidationError):
            ModuleInvocation([bad], {})
        assert validate(response(bad))['returned'].representation == 'unavailable'
    assert validate(response('x'*32768))['returned'].representation == 'transported'
    assert validate(response([0]*1024))['returned'].representation == 'unavailable'
    wire = request(); wire['channel_token'] = 'x'*129
    with pytest.raises(ValidationError):
        parse_module_request(wire)
    wire = response(); wire['protocol_version'] = 2.0
    with pytest.raises(ValidationError):
        validate(wire)


def test_top_level_size_before_copy():
    """Oversized top-level sequences/mappings reject before snapshot allocation."""
    for args, kwargs in ((tuple(range(1025)), {}), ([], {str(i): 0 for i in range(1025)})):
        with pytest.raises(ValidationError, match='maximum item count'):
            ModuleInvocation(args, kwargs)
