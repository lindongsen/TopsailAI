"""Opaque return and bounded result metadata contracts."""
from dataclasses import FrozenInstanceError
import pytest
from topsailai.hooks.result_contracts import ReturnedValue, ResultDiagnostic, ResultTiming, ResultCleanup, ResultDecision
from topsailai.hooks.contracts import ValidationError

class Hostile:
    """Fail if framework metadata observes an opaque payload."""
    def __repr__(self):
        """Reject formatting."""
        raise AssertionError("payload touched")
    __str__ = __repr__
    __bool__ = __repr__
    __hash__ = __repr__
    def __eq__(self, other):
        """Reject comparison."""
        raise AssertionError("payload touched")
    def __deepcopy__(self, memo):
        """Reject copying."""
        raise AssertionError("payload touched")

@pytest.mark.parametrize("value", [False, None, {"error": 1}, Hostile()])
@pytest.mark.parametrize("representation", ["direct", "transported"])
def test_payload_is_opaque(value, representation):
    """Payload identity survives generated metadata methods without interpretation."""
    a = ReturnedValue(True, representation, value)
    b = ReturnedValue(True, representation, Hostile())
    assert a.value is value
    assert a == b
    repr(a)
    hash(a)
    with pytest.raises(FrozenInstanceError):
        a.present = False

def test_presence_and_shallow_ownership():
    """Returned None differs from absence; mutable payload is deliberately shallow."""
    assert ReturnedValue(True, "direct", None) != ReturnedValue()
    assert ReturnedValue(True, "unavailable").present
    data = []
    returned = ReturnedValue(True, "direct", data)
    data.append(1)
    assert returned.value is data

@pytest.mark.parametrize("kwargs", [
    {"present": 1}, {"representation": []}, {"representation": "other"},
    {"representation": "reference"}, {"present": True, "representation": "reference", "reference": "owned"},
    {"representation": "direct"}, {"value": Hostile()}, {"reference": Hostile()},
    {"present": True, "representation": "direct", "reference": Hostile()},
    {"present": True, "representation": "unavailable", "value": Hostile()},
])
def test_invalid_returns(kwargs):
    """Invalid combinations reject without formatting rejected values."""
    with pytest.raises(ValidationError):
        ReturnedValue(**kwargs)

@pytest.mark.parametrize("category,message", [("", "ok"), ("x"*129,"ok"), (Hostile(),"ok"), ("x",Hostile()), ("x","x"*1025)])
def test_diagnostic_rejection(category, message):
    """Only bounded exact strings enter diagnostics."""
    with pytest.raises(ValidationError):
        ResultDiagnostic(category, message)

def test_metadata_boundaries():
    """Boundary strings, absent timestamps and cleanup states remain independent."""
    d = ResultDiagnostic("x"*128, "x"*1024)
    assert ResultTiming().started_at is None
    assert ResultTiming(1, 2.5, 0).elapsed_ms == 0
    for state in ("safe", "pending", "failed"):
        assert ResultCleanup(state, d).diagnostic is d
    assert ResultDecision().authority is None
    assert ResultDecision("block", "catalog").action == "block"
    assert ResultDecision("continue", "catalog").action == "continue"

@pytest.mark.parametrize("kwargs", [
    {"started_at": True}, {"started_at": "1"}, {"started_at": float("nan")},
    {"finished_at": float("inf")}, {"started_at": 2, "finished_at": 1},
    {"elapsed_ms": -1}, {"elapsed_ms": True}, {"elapsed_ms": 1.5},
])
def test_timing_rejection(kwargs):
    """Time validation does not derive elapsed time."""
    with pytest.raises(ValidationError):
        ResultTiming(**kwargs)

@pytest.mark.parametrize("factory,args", [
    (ResultCleanup, ([],)), (ResultCleanup,("unsafe",)), (ResultCleanup,("safe", Hostile())),
    (ResultDecision,([],)), (ResultDecision,("unknown",)), (ResultDecision,("block",None)),
    (ResultDecision,("continue",Hostile())),
])
def test_cleanup_decision_rejection(factory,args):
    """Descriptive decisions and cleanup reject malformed shapes."""
    with pytest.raises(ValidationError):
        factory(*args)
