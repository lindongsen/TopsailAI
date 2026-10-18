"""Handler automatic and explicit request controls. Author: DawsonLin."""
from dataclasses import asdict
import os
from types import SimpleNamespace
from uuid import UUID

import pytest

from topsailai.ai_base.llm_control.attempt_control import AttemptTarget
from topsailai.ai_base.llm_control.control_runtime import ControlRoute
from topsailai.ai_base.llm_control.request_control import RequestControl
from topsailai.workspace.control_channel.protocol import ControlContext, ControlRequest
import topsailai.workspace.control_handlers.llm_control as module


@pytest.fixture
def case(monkeypatch):
    """Use an isolated consumer registry and real route lock."""
    service = RequestControl()
    monkeypatch.setattr(module, "REQUEST_CONTROL", service)
    agent = object()
    route = ControlRoute("session", os.getpid(), agent, interrupt_supported=True)
    route.reconcile = lambda: None
    route.target = AttemptTarget(route.binding_id, 1, "invocation", "a")
    service.bind(route.target)
    chat = SimpleNamespace(ai_agent=agent, _llm_control_route=route)
    context = ControlContext(session_id="session", pid=os.getpid(), agent_chat=chat)
    return service, route, context


def call(case, **payload):
    """Execute the production Handler and preserve transport correlation."""
    request = ControlRequest(request_id="transport", action="llm_control", payload=payload)
    response = module.LLMControlHandler().handle(request, case[2])
    assert response.request_id == "transport"
    return response


@pytest.mark.parametrize("operation", ["force_retry", "hard_interrupt"])
def test_action_only_ids_and_explicit_replay(case, operation):
    """Action-only receipts expose fresh IDs and exact frozen targets."""
    service, route, _ = case
    receipts = [call(case, operation=operation) for _ in range(2)]
    ids = [value.result["proposal"]["command_id"] for value in receipts]
    assert ids[0] != ids[1]
    for receipt, command_id in zip(receipts, ids):
        assert UUID(command_id).hex == command_id
        assert receipt.status == "ok"
        assert receipt.result["state"] == "queued"
        assert receipt.result["proposal"]["target"] == asdict(route.target)
        assert call(case, operation=operation, command_id=command_id,
                    target=asdict(route.target)).result == receipt.result


def test_history_before_target_and_capacity(case):
    """A stable ID never rebinds after target retirement or fallback."""
    service, route, _ = case
    receipt = call(case, operation="force_retry", command_id="stable")
    a = route.target
    service.retire(a)
    route.target = AttemptTarget(route.binding_id, 1, "invocation", "b")
    service.bind(route.target)
    replay = call(case, operation="force_retry", command_id="stable")
    assert replay.result["proposal"] == receipt.result["proposal"]
    assert service.probe(route.target, "creating") is None
    route.target = None
    route.reason = "control_capacity"
    assert call(case, operation="force_retry", command_id="stable").result == replay.result
    assert call(case, operation="hard_interrupt", command_id="stable").result["reason"] == "conflict"
    assert call(case, operation="force_retry").error == "unavailable/control_capacity"
    route.reason = None
    assert call(case, operation="force_retry").error == "no_active_target"


@pytest.mark.parametrize("value", [None, {}, [], "bad", {"binding_id": "x"}])
def test_explicit_invalid_never_falls_back(case, value):
    """Presence rather than truthiness distinguishes automatic selection."""
    assert call(case, operation="force_retry", target=value).status == "error"
    assert case[0].probe(case[1].target, "creating") is None


@pytest.mark.parametrize("value", [None, "", 1, "x" * 129])
def test_bad_command_id(case, value):
    """Malformed stable IDs fail before history or issuance."""
    assert call(case, operation="force_retry", command_id=value).error == "invalid control identifier"


@pytest.mark.parametrize("change", ["closed", "agent", "session", "pid", "missing", "replace"])
def test_ownership_before_replay(case, change):
    """Rejected owners cannot replay retained control history."""
    _, route, context = case
    call(case, operation="force_retry", command_id="stable")
    if change == "closed":
        route.closed = True
    elif change == "agent":
        context.agent_chat.ai_agent = object()
    elif change == "session":
        route.session_id = "other"
    elif change == "pid":
        route.pid = -1
    elif change == "missing":
        context.agent_chat._llm_control_route = None
    else:
        route.reconcile = lambda: setattr(context.agent_chat, "_llm_control_route", None)
    assert call(case, operation="force_retry", command_id="stable").error == "unavailable"


def test_status_explicit_invalid_operation_and_lock(case, monkeypatch):
    """Original status/explicit paths survive and admission holds route lock."""
    service, route, _ = case
    original = service.submit_current
    def locked(*args, **kwargs):
        """Observe route lock at the actual unified admission seam."""
        assert route.lock._is_owned()
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "submit_current", locked)
    receipt = call(case, operation="force_retry", command_id="stable")
    assert call(case, operation="status", command_id="stable").result == receipt.result
    assert call(case, operation="status").result["target"] == asdict(route.target)
    assert call(case, operation="status", command_id="unknown").error == "unknown_command"
    assert call(case, operation="bad").error == "invalid_operation"
    wrong = asdict(route.target)
    wrong["generation"] = 2
    assert call(case, operation="force_retry", target=wrong).error == "stale_target"
    route.reason = "control_capacity"
    assert call(case, operation="force_retry", target=asdict(route.target)).error == "unavailable/control_capacity"


@pytest.mark.parametrize("change", ["binding", "generation"])
def test_history_scope_conflict_is_opaque(case, change):
    """Foreign history never escapes in the response envelope."""
    _, route, _ = case
    receipt = call(case, operation="force_retry", command_id="stable")
    if change == "binding":
        route.binding_id = "replacement"
    else:
        route.generation += 1
    response = call(case, operation="force_retry", command_id="stable")
    assert response.status == "error"
    assert response.error == "conflict"
    assert response.result is None
    assert receipt.result["proposal"]["target"]["generation"] == 1


@pytest.mark.parametrize("mutation", ["clear", "publish"])
def test_competing_target_mutation_waits_for_admission(case, monkeypatch, mutation):
    """Prove a competing route writer cannot pass snapshot-and-submit admission."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    service, route, _ = case
    original_target = route.target
    replacement = AttemptTarget(route.binding_id, route.generation, "next", "b")
    entered, blocked = Event(), Event()
    original_submit = service.submit_current

    def paused(*args, **kwargs):
        """Pause with route lock held until a competitor proves exclusion."""
        entered.set()
        assert blocked.wait(5)
        assert route.target == original_target
        assert args[2] == original_target
        return original_submit(*args, **kwargs)

    def mutate():
        """Try the real route lock, then mutate under the production lock order."""
        assert entered.wait(5)
        acquired = route.lock.acquire(blocking=False)
        if acquired:
            route.lock.release()
        blocked.set()
        assert not acquired, "target mutation bypassed atomic admission"
        with route.lock:
            service.retire(original_target)
            route.target = None if mutation == "clear" else replacement
            if route.target is not None:
                service.bind(replacement)

    monkeypatch.setattr(service, "submit_current", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(mutate)
        receipt = pool.submit(call, case, operation="force_retry", command_id="race").result(10)
        writer.result(10)
    monkeypatch.setattr(service, "submit_current", original_submit)
    assert receipt.result["proposal"]["target"] == asdict(original_target)
    assert call(case, operation="force_retry", command_id="race").result["proposal"] == receipt.result["proposal"]
    assert service.probe(replacement, "creating") is None


def test_socket_idle_capacity_replay_and_scope_secrecy(case, tmp_path):
    """Assert actual encoded socket responses across idle, fallback and owners."""
    import json
    import socket
    from uuid import uuid4
    from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
    from topsailai.workspace.control_channel.server import ControlServer

    service, route, context = case
    registry = ControlHandlerRegistry()
    registry.register(module.LLMControlHandler())
    root = next(parent for parent in tmp_path.parents if parent.name == ".tmp")
    path = str(root / (uuid4().hex[:12] + ".sock"))
    channel = ControlServer(path, registry, context, timeout=0.1)

    def send(**payload):
        """Use production JSONL dispatch and response encoding, not direct calls."""
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(5)
            peer.connect(path)
            peer.sendall(json.dumps({"request_id": "wire", "action": "llm_control",
                                   "payload": payload}).encode() + b"\n")
            with peer.makefile("rb") as stream:
                return json.loads(stream.readline())

    channel.start()
    try:
        first = send(operation="force_retry", command_id="stable")
        assert first["result"]["state"] == "queued"
        service.retire(route.target)
        route.target = None
        replay = send(operation="force_retry", command_id="stable")
        assert replay["result"]["proposal"] == first["result"]["proposal"]
        assert send(operation="force_retry", command_id="idle")["error"] == "no_active_target"
        assert service.status("idle") is None
        route.reason = "control_capacity"
        assert send(operation="force_retry", command_id="stable")["result"] == replay["result"]
        assert send(operation="force_retry", command_id="full")["error"] == "unavailable/control_capacity"
        assert service.status("full") is None
        changed = send(operation="hard_interrupt", command_id="stable")
        assert changed["result"]["reason"] == "conflict"
        for binding, generation in [(route.binding_id, 2), ("foreign", 1)]:
            route.binding_id, route.generation = binding, generation
            response = send(operation="force_retry", command_id="stable")
            assert response["status"] == "error"
            assert response["error"] == "conflict"
            assert response.get("result") is None
            assert "invocation" not in json.dumps(response)
        route.closed = True
        assert send(operation="force_retry", command_id="stable")["error"] == "unavailable"
    finally:
        channel.stop()
    assert not channel.is_running()
