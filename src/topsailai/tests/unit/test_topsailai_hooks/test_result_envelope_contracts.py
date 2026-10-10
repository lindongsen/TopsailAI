"""Ordered unified result envelopes independent of Runtime adoption."""
from dataclasses import replace, FrozenInstanceError
import pytest
from topsailai.hooks.result_contracts import HandlerIdentity, ReturnedValue, ResultDiagnostic, ResultTiming, ResultCleanup, ResultDecision, HandlerResult, HookPointResult
from topsailai.hooks.contracts import ValidationError


def handler(kind="module", name="name", id="id", **kwargs):
    """Create one valid local result."""
    identity = kwargs.pop("handler", HandlerIdentity(id, name, kind))
    return HandlerResult("execution", "point", 0, identity, **kwargs)


def default(**kwargs):
    """Create the unique terminal default Hook."""
    return handler("default_script_hook", "hook_script", "default", **kwargs)


def point(handlers=None, **kwargs):
    """Create an explicitly ordered aggregate."""
    return HookPointResult("execution", "point", 0, handlers=[default()] if handlers is None else handlers, **kwargs)


def test_success_values_do_not_block():
    """Return payload never derives status or decision."""
    for value in (False, None, {"error": 1}):
        result = handler(returned=ReturnedValue(True, "direct", value))
        assert result.status == "success"
        assert result.decision.action == "continue"
        assert result.returned.value is value
    assert handler(returned=ReturnedValue(True,"unavailable"), error=ResultDiagnostic("representation", "unavailable")).status == "success"


def test_frozen_ordered_detachment():
    """Collection ownership detaches without sorting or cloning records."""
    children = [handler("script", "z", "z"), handler("script", "a", "a")]
    terminal = default(children=children, status="completed_with_errors", cleanup=ResultCleanup("pending"))
    children.clear()
    assert [c.handler.name for c in terminal.children] == ["z", "a"]
    modules = [handler(name="hook_script"), terminal]
    result = point(modules)
    modules.clear()
    assert result.handlers == (handler(name="hook_script"), terminal)
    assert result.status == "success"
    with pytest.raises(FrozenInstanceError):
        result.status = "error"
    assert not hasattr(result,"__dict__")

@pytest.mark.parametrize("kwargs", [
    {"execution_id":""}, {"hook_point_name":1}, {"plan_version":True}, {"plan_version":-1},
])
def test_correlation_rejection(kwargs):
    """Correlation validates exact types before dependent access."""
    values = dict(execution_id="execution", hook_point_name="point", plan_version=0, handler=HandlerIdentity("id","name","module"))
    values.update(kwargs)
    with pytest.raises(ValidationError):
        HandlerResult(**values)

@pytest.mark.parametrize("args", [("","name","module"),("id",1,"module"),("id","name",[]),("id","name","unknown")])
def test_identity_rejection(args):
    """Identity vocabulary excludes malformed lookalikes."""
    with pytest.raises(ValidationError):
        HandlerIdentity(*args)

@pytest.mark.parametrize("kwargs", [
    {"handler":None}, {"status":[]}, {"status":"bad"}, {"status":"completed_with_errors"},
    {"status":"not_run"}, {"status":"not_run","not_run_reason":""},
    {"status":"not_run","not_run_reason":"x"*1025}, {"not_run_reason":"unexpected"},
    {"status":"error"}, {"status":"timeout","returned":ReturnedValue(True,"direct",False)},
    {"status":"not_run","not_run_reason":"skip","returned":ReturnedValue(True,"direct",None)},
    {"returned":None}, {"error":1}, {"timing":None}, {"cleanup":None}, {"decision":None},
    {"children":{}}, {"children":[None]}, {"children":[handler()]},
])
def test_handler_rejection(kwargs):
    """Nested shape and status constraints reject safely."""
    with pytest.raises(ValidationError):
        handler(**kwargs)


def test_terminal_children_rejections():
    """Child kind, identity and correlations remain bounded and unique."""
    child = handler("script","", "child")
    for children in ([handler()], [child,child], [child,replace(child,handler=HandlerIdentity("other","","script"))], [replace(child,execution_id="other")], [replace(child,hook_point_name="other")], [replace(child,plan_version=1)], [None]):
        with pytest.raises(ValidationError):
            default(children=children)
    with pytest.raises(ValidationError):
        handler(children=[child])


def test_statuses_and_aggregate_decision():
    """Caller reports status; Catalog provenance is descriptive, not executable."""
    for status in ("error", "timeout", "cancelled", "not_run"):
        kwargs = {"error":ResultDiagnostic("failure","")} if status=="error" else {}
        if status=="not_run":
            kwargs["not_run_reason"]="skip"
        assert handler(status=status,**kwargs).status == status
    for status in ("success","completed_with_errors","timeout","cancelled"):
        assert point(status=status).status == status
    assert point([],status="unavailable").handlers == ()
    assert point(status="blocked",decision=ResultDecision("block","catalog")).status == "blocked"

@pytest.mark.parametrize("handlers,kwargs", [
    ([],{}), ([handler()],{}), ([default(),handler()],{}), ([default(),default()],{}),
    ([handler("script"),default()],{}), ([handler(),handler(),default()],{}),
    ([handler(),handler(id="other"),default()],{}), ([replace(handler(),plan_version=1),default()],{}),
    ([None],{}), ({},{}), ([default()],{"status":[]}), ([default()],{"status":"bad"}),
    ([default()],{"status":"blocked"}), ([default()],{"decision":ResultDecision("block","catalog")}),
    ([default()],{"timing":None}), ([default()],{"cleanup":None}), ([default()],{"decision":None}),
])
def test_aggregate_rejection(handlers, kwargs):
    """Aggregate preserves plan shape without inferring an execution algorithm."""
    with pytest.raises(ValidationError):
        point(handlers,**kwargs)


def test_collection_limits():
    """Both envelopes accept 256 and reject 257 owned records."""
    scripts = [handler("script",str(i),str(i)) for i in range(257)]
    assert len(default(children=scripts[:256]).children)==256
    with pytest.raises(ValidationError):
        default(children=scripts)
    modules = [handler(name=str(i),id=str(i)) for i in range(256)]
    assert len(point(modules[:255]+[default()]).handlers)==256
    with pytest.raises(ValidationError):
        point(modules+[default()])


class OpaquePayload:
    """Reject accidental observations through generated envelope methods."""
    def __repr__(self):
        """Reject payload formatting."""
        raise AssertionError("opaque payload observed")
    __str__ = __repr__
    __bool__ = __repr__
    __hash__ = __repr__
    def __eq__(self, other):
        """Reject payload comparison."""
        raise AssertionError("opaque payload observed")
    def __deepcopy__(self, memo):
        """Reject payload cloning."""
        raise AssertionError("opaque payload observed")


def test_generated_envelopes_keep_payload_opaque():
    """Repr, equality and hash never reach arbitrary returned objects."""
    a = handler(returned=ReturnedValue(True, "direct", OpaquePayload()))
    b = handler(returned=ReturnedValue(True, "direct", OpaquePayload()))
    assert a == b
    assert point([a,default()]) == point([b,default()])
    repr(point([a,default()]))
    hash(point([a,default()]))


@pytest.mark.parametrize("kind", ["module", "script", "default_script_hook"])
@pytest.mark.parametrize("started_at", [0, -1, 1])
@pytest.mark.parametrize("finished_at", [None, 2])
def test_not_run_rejects_started_timing(kind, started_at, finished_at):
    """Unrun handlers reject every supplied start without observing return values."""
    with pytest.raises(ValidationError, match="^not_run handler cannot have a start timestamp$"):
        handler(kind, status="not_run", not_run_reason="skip",
                timing=ResultTiming(started_at, finished_at, 10))


@pytest.mark.parametrize("kind", ["module", "script", "default_script_hook"])
@pytest.mark.parametrize("cleanup_state", ["safe", "pending", "failed"])
def test_not_run_absent_start_preserves_cleanup(kind, cleanup_state):
    """Absent starts remain valid without inventing end or duration semantics."""
    timing = ResultTiming(None, 2, 10)
    cleanup = ResultCleanup(cleanup_state)
    result = handler(kind, status="not_run", not_run_reason="skip",
                     timing=timing, cleanup=cleanup)
    assert result.timing is timing
    assert result.cleanup is cleanup
    assert not result.returned.present


@pytest.mark.parametrize("status", ["success", "error", "timeout", "cancelled", "completed_with_errors"])
@pytest.mark.parametrize("cleanup_state", ["safe", "pending", "failed"])
def test_run_statuses_preserve_started_timing(status, cleanup_state):
    """The new not-run invariant does not constrain other statuses or cleanup."""
    timing = ResultTiming(-1, 2, 10)
    cleanup = ResultCleanup(cleanup_state)
    kwargs = {"error": ResultDiagnostic("failure", "")} if status == "error" else {}
    result = default(status=status, timing=timing, cleanup=cleanup, **kwargs)
    assert result.timing is timing
    assert result.cleanup is cleanup


@pytest.mark.parametrize("kind", ["module", "script", "default_script_hook"])
@pytest.mark.parametrize("kwargs,message", [
    ({}, "not_run reason must be a bounded valid string"),
    ({"not_run_reason": "skip", "returned": ReturnedValue(True, "direct", None)},
     "failed or unrun handler cannot return normally"),
])
def test_not_run_validation_priority(kind, kwargs, message):
    """Existing reason and returned-value errors precede the new timing error."""
    with pytest.raises(ValidationError) as caught:
        handler(kind, status="not_run", timing=ResultTiming(0), **kwargs)
    assert str(caught.value) == message


@pytest.mark.parametrize("kind", ["module", "script", "default_script_hook"])
def test_not_run_timing_type_checked_before_access(kind):
    """Reject malformed nested timing before reading its attributes."""
    with pytest.raises(ValidationError, match="^invalid timing$"):
        handler(kind, status="not_run", not_run_reason="skip", timing=object())
