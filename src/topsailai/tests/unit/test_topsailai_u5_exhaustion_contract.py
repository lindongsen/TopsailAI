"""Unit contracts for exhaustion transport, timing and control publication."""

import pytest

from tests.bdd.steps.test_llm_first_byte_timeout_exhaustion_steps import (
    _CONTEXTS, exact_counts, terminal_settlement,
)

def test_u5_real_transport_shapes_and_disposal_diagnostics():
    """Accept SDK unbounded phases and retained late reads, never invalid budgets or disposal."""
    import pytest
    from types import SimpleNamespace
    from tests.unit.test_topsailai_u5_exhaustion_acceptance import _u5_valid_candidate
    from tests.bdd.llm_first_byte_exhaustion_harness import validate_settlement
    for mode in ("headers", "first_item"):
        row, facts = _u5_valid_candidate(mode)
        for key in ("write", "pool"):
            row["transport_normalized"][key] = row["http_request"].extensions["timeout"][key] = None
        raw = row.raw_event["raw"]
        raw.response = SimpleNamespace(is_closed=True)
        row["abandoned"] = True
        late = facts["close_error"] = RuntimeError("late fetch")
        facts["events"].append(dict(kind="error", error=late))
        assert validate_settlement(row, facts, now=4)["close_error"] is late
        for key in ("connect", "read", "write", "pool"):
            saved = row["transport_normalized"][key]
            for bad in (0, -1, float("nan"), float("inf"), True, "5"):
                row["transport_normalized"][key] = row["http_request"].extensions["timeout"][key] = bad
                with pytest.raises(AssertionError):
                    validate_settlement(row, facts, now=4)
            row["transport_normalized"][key] = row["http_request"].extensions["timeout"][key] = saved
        for bad in (dict(disposal_error=late), dict(close_error=RuntimeError("unattributed"))):
            with pytest.raises(AssertionError):
                validate_settlement(row, dict(facts, **bad), now=4)
        raw.response.is_closed = False
        with pytest.raises(AssertionError):
            validate_settlement(row, facts, now=4)



def test_u5_phase_specific_timing_and_physical_settlement():
    """Keep exact callbacks and settlement authority separate in both actual consumers."""
    from types import SimpleNamespace
    from tests.unit.test_topsailai_u5_exhaustion_acceptance import _completed_scenario
    check_u5_control_publication_notification()
    request = SimpleNamespace(node=SimpleNamespace(nodeid="u5-phase-contract"))
    try:
        for mode in ("headers", "first_item"):
            scenario = _completed_scenario(mode)
            _CONTEXTS[request.node.nodeid] = scenario
            row = scenario.records[18]
            bundle = row.completed_bundle
            boundaries = row["callback_boundaries"]
            callbacks = bundle["callbacks"]
            if mode == "first_item":
                for event, at in zip(bundle["events"], (1.2, 1.3, 1.4)):
                    event["at"] = at
            for consumer in (exact_counts, terminal_settlement):
                consumer(request)
            cases = [
                (bundle, "callbacks", callbacks[:-1]),
                (bundle, "callbacks", callbacks + [dict(callbacks[-1])]),
                (callbacks[-1], "operation", "pause"),
                (callbacks[-1], "completed", False),
                (callbacks[-1], "initiator", object()),
                (boundaries[-1], "ticket", object()),
                (boundaries[-1], "after", 2.9 if mode == "headers" else 3.5),
            ]
            if mode == "headers":
                cases.append((bundle["events"][1], "at", 2.9))
            else:
                cases.append((bundle["handler"], "connection_closed", False))
            for target, key, bad in cases:
                saved = target[key]
                try:
                    target[key] = bad
                    for consumer in (exact_counts, terminal_settlement):
                        with pytest.raises(AssertionError):
                            consumer(request)
                finally:
                    target[key] = saved
                for consumer in (exact_counts, terminal_settlement):
                    consumer(request)
    finally:
        _CONTEXTS.pop(request.node.nodeid, None)



def check_u5_control_publication_notification():
    """Require exact stream publication notification before held iteration can block."""
    import threading
    from types import SimpleNamespace
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources
    notifications = []
    data = {"stream": None}
    class Condition:
        """Record publication observed by the condition notification boundary."""
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def notify_all(self): notifications.append(data["stream"])
    class Stream:
        """Assert publication reached waiters before iteration."""
        def __iter__(self):
            assert notifications == [self]
            return iter(())
    stream = Stream()
    create = lambda **kwargs: stream
    resources = SimpleNamespace(control_data=data, condition=Condition(), publish_failure=lambda e: (_ for _ in ()).throw(e), control_lease=SimpleNamespace(client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))), retain=lambda key, value: value, register_worker=lambda worker, role, deadline: worker.run())
    ScenarioResources._prepare_control_worker(resources)
    assert notifications == [stream, stream] and data["stream"] is stream
