"""Real UDS event-channel acceptance steps.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Drive the real event channel server over a real Unix domain socket
"""

import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from topsailai.ai_base.runtime_data import RuntimeDataStore
from topsailai.events import reset_event_collector
from topsailai.events.models import Event
from topsailai.events.subscribers import (
    SubscriptionRegistry,
    fan_out,
    reset_event_channel_stats,
    set_drop_observer,
    set_subscription_registry,
)
from topsailai.workspace.event_channel import EventChannelConfig, EventChannelServer
from topsailai.workspace.event_channel import runtime_state
from topsailai.workspace.plugin_instruction import runtime as runtime_instruction

RECV_TIMEOUT = 5.0


def _wait_for(predicate, timeout=RECV_TIMEOUT, interval=0.01):
    """Poll a predicate until it becomes true or the timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _connect(state, subscriber_id, event_types=None):
    """Open a real UDS link and complete the subscribe handshake."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(RECV_TIMEOUT)
    sock.connect(state.socket_path)
    frame = {"type": "subscribe", "subscriber_id": subscriber_id}
    if event_types:
        frame["filter"] = {"event_types": event_types}
    sock.sendall(json.dumps(frame).encode("utf-8") + b"\n")
    confirmation = _read_frame(sock)
    assert confirmation["type"] == "subscribed", confirmation
    assert confirmation["subscriber_id"] == subscriber_id
    return sock


_FRAME_BUFFERS = {}


def _read_frame(sock):
    """Read exactly one JSONL frame from a link.

    A single ``recv`` can deliver several frames at once, so the bytes after
    the first newline are kept per socket instead of being discarded. Without
    this, two events emitted back to back would lose the second one.
    """
    buffer = _FRAME_BUFFERS.pop(sock, b"")
    while b"\n" not in buffer:
        chunk = sock.recv(65536)
        if not chunk:
            raise AssertionError("link closed before a frame arrived")
        buffer += chunk
    line, _, remainder = buffer.partition(b"\n")
    if remainder:
        _FRAME_BUFFERS[sock] = remainder
    return json.loads(line.decode("utf-8"))


def _send(sock, frame):
    """Send one JSONL frame."""
    sock.sendall(json.dumps(frame).encode("utf-8") + b"\n")


@pytest.fixture
def channel_state(bdd_tmp_path, monkeypatch):
    """Own one real server, its registry, and every link opened by a scenario."""
    state = SimpleNamespace(
        socket_path=str(bdd_tmp_path / "events.sock"),
        server=None,
        registry=None,
        links={},
        recorded=[],
        agent=SimpleNamespace(runtime=SimpleNamespace(runtime_data=RuntimeDataStore())),
    )
    monkeypatch.setattr(runtime_state, "get_agent_object", lambda: state.agent)
    monkeypatch.setattr(runtime_instruction, "get_ai_agent", lambda: state.agent)
    monkeypatch.setenv("TOPSAILAI_EVENTS_ENABLED", "1")
    monkeypatch.setenv(
        "TOPSAILAI_EVENTS_FILE_PATH", str(bdd_tmp_path / "recorded.events")
    )
    reset_event_collector()
    reset_event_channel_stats()
    runtime_state.clear_event_channel_runtime_state()
    try:
        yield state
    finally:
        for sock in state.links.values():
            try:
                sock.close()
            except OSError:
                pass
        if state.server is not None:
            state.server.stop()
            assert not state.server.is_running()
            assert not __import__("os").path.exists(state.socket_path)
        set_subscription_registry(None)
        set_drop_observer(None)
        reset_event_collector()
        reset_event_channel_stats()
        runtime_state.clear_event_channel_runtime_state()
        _FRAME_BUFFERS.clear()


@given(
    parsers.parse('an event channel serving session "{session}"'),
    target_fixture="channel_state",
)
def start_channel(channel_state, session):
    """Start the real server with production defaults."""
    return _start(channel_state, session, queue_size=100, heartbeat_timeout=5.0)


@given(
    parsers.parse(
        'an event channel serving session "{session}" with a {timeout} second heartbeat timeout'
    ),
    target_fixture="channel_state",
)
def start_channel_with_timeout(channel_state, session, timeout):
    """Start the real server with a short heartbeat timeout."""
    return _start(channel_state, session, queue_size=100, heartbeat_timeout=float(timeout))


@given(
    parsers.parse('an event channel serving session "{session}" with a {size} event queue'),
    target_fixture="channel_state",
)
def start_channel_with_queue(channel_state, session, size):
    """Start the real server with a small per-subscriber queue."""
    return _start(channel_state, session, queue_size=int(size), heartbeat_timeout=5.0)


def _start(state, session, queue_size, heartbeat_timeout):
    """Start a real server and install its registry for fan-out."""
    state.session = session
    state.registry = SubscriptionRegistry(max_subscribers=8, queue_size=queue_size)
    set_subscription_registry(state.registry)
    config = EventChannelConfig(
        enabled=True,
        max_subscribers=8,
        queue_size=queue_size,
        heartbeat_interval=0.2,
        heartbeat_timeout=heartbeat_timeout,
    )
    state.server = EventChannelServer(
        socket_path=state.socket_path,
        config=config,
        registry=state.registry,
        read_timeout=0.2,
        reaper_interval=0.1,
    )
    state.server.start()
    assert state.server.is_running()
    return state


@when(
    parsers.parse(
        'a subscriber "{subscriber_id}" connects and subscribes to every event type'
    )
)
def subscribe_all(channel_state, subscriber_id):
    """Subscribe without a filter."""
    channel_state.links[subscriber_id] = _connect(channel_state, subscriber_id)


@given(
    parsers.parse('a subscriber "{subscriber_id}" connects and subscribes to "{pattern}"')
)
@when(
    parsers.parse('a subscriber "{subscriber_id}" connects and subscribes to "{pattern}"')
)
def subscribe_filtered(channel_state, subscriber_id, pattern):
    """Subscribe with one filter pattern."""
    channel_state.links[subscriber_id] = _connect(
        channel_state, subscriber_id, [pattern]
    )


@when(parsers.parse('the session records a "{event_type}" event'))
def record_event(channel_state, event_type):
    """Record one event through the real fan-out entry point."""
    event = Event(event_type=event_type, payload={"marker": event_type})
    channel_state.recorded.append(event)
    fan_out(event)


@then(parsers.parse('subscriber "{subscriber_id}" receives that event over the link'))
def receives_event(channel_state, subscriber_id):
    """Assert the pushed frame carries the recorded event."""
    frame = _read_frame(channel_state.links[subscriber_id])
    assert frame["type"] == "event"
    assert frame["event"]["event_type"] == channel_state.recorded[-1].event_type


@then(parsers.parse('subscriber "{subscriber_id}" receives only the "{event_type}" event'))
def receives_only(channel_state, subscriber_id, event_type):
    """Assert the filtered event arrives and the rejected one never does."""
    frame = _read_frame(channel_state.links[subscriber_id])
    assert frame["type"] == "event"
    assert frame["event"]["event_type"] == event_type

    channel_state.links[subscriber_id].settimeout(0.3)
    with pytest.raises(socket.timeout):
        _read_frame(channel_state.links[subscriber_id])


@when(parsers.parse("the subscriber sends heartbeat sequence {seq:d}"))
def send_heartbeat(channel_state, seq):
    """Send one heartbeat on the most recently opened link."""
    sock = list(channel_state.links.values())[-1]
    _send(sock, {"type": "heartbeat", "seq": seq})


@then(parsers.parse("the server acknowledges heartbeat sequence {seq:d}"))
def heartbeat_ack(channel_state, seq):
    """Assert the acknowledgement echoes the client sequence number."""
    frame = _read_frame(list(channel_state.links.values())[-1])
    assert frame == {"type": "heartbeat_ack", "seq": seq}


@then(parsers.parse('subscriber "{subscriber_id}" is still registered'))
def still_registered(channel_state, subscriber_id):
    """Assert the subscriber survived the heartbeat exchange."""
    assert channel_state.registry.get(subscriber_id) is not None


@when("the subscriber closes the link")
def close_link(channel_state):
    """Close the most recently opened link."""
    sock = list(channel_state.links.values())[-1]
    sock.close()


@then(parsers.parse('subscriber "{subscriber_id}" is no longer registered'))
def not_registered(channel_state, subscriber_id):
    """Assert the server released the subscriber after the link ended."""
    assert _wait_for(lambda: channel_state.registry.get(subscriber_id) is None)


@then("a later recorded event is delivered to nobody")
def delivered_to_nobody(channel_state):
    """Assert fan-out reports no delivery once every link is gone."""
    assert _wait_for(lambda: len(channel_state.registry) == 0)
    assert fan_out(Event(event_type="tool_call.start", payload={})) == 0


@when(parsers.parse('the same subscriber "{subscriber_id}" reconnects'))
def reconnect(channel_state, subscriber_id):
    """Reconnect with the same client-generated identity."""
    channel_state.links[subscriber_id] = _connect(channel_state, subscriber_id)


@then(parsers.parse('only one link exists for subscriber "{subscriber_id}"'))
def one_link(channel_state, subscriber_id):
    """Assert the registry holds exactly one entry for the identity."""
    assert _wait_for(lambda: len(channel_state.registry) == 1)
    assert channel_state.registry.get(subscriber_id) is not None


@then("an event recorded after the reconnect arrives exactly once")
def arrives_once(channel_state):
    """Assert the new link receives the event and no duplicate follows."""
    event = Event(event_type="tool_call.start", payload={"after": "reconnect"})
    assert fan_out(event) == 1

    sock = list(channel_state.links.values())[-1]
    frame = _read_frame(sock)
    assert frame["type"] == "event"
    assert frame["event"]["payload"] == {"after": "reconnect"}

    sock.settimeout(0.3)
    with pytest.raises(socket.timeout):
        _read_frame(sock)


@when("the subscriber unsubscribes")
def unsubscribe(channel_state):
    """Send an explicit unsubscribe frame."""
    _send(list(channel_state.links.values())[-1], {"type": "unsubscribe"})


@then("the server confirms the unsubscribe")
def unsubscribe_confirmed(channel_state):
    """Assert the confirmation frame arrives before the link closes."""
    frame = _read_frame(list(channel_state.links.values())[-1])
    assert frame["type"] == "unsubscribed"


@when("the subscriber stops sending heartbeats")
def stop_heartbeats(channel_state):
    """Keep the link open but stop all liveness signals."""
    assert len(channel_state.registry) == 1


@then(
    parsers.parse('subscriber "{subscriber_id}" is reclaimed without an explicit disconnect')
)
def reclaimed(channel_state, subscriber_id):
    """Assert the reaper removes a silent subscriber."""
    assert _wait_for(lambda: channel_state.registry.get(subscriber_id) is None)


@when(parsers.parse("the subscriber stops reading while {count:d} events are recorded"))
def stop_reading(channel_state, count):
    """Record events while the subscriber never reads its link."""
    channel_state.recorded = []
    started = time.monotonic()
    for index in range(count):
        event = Event(event_type="tool_call.start", payload={"index": index})
        channel_state.recorded.append(event)
        fan_out(event)
    channel_state.record_elapsed = time.monotonic() - started


@then(parsers.parse("recording all {count:d} events completes without blocking"))
def recording_not_blocked(channel_state, count):
    """Assert the producer finished promptly for every event."""
    assert len(channel_state.recorded) == count
    assert channel_state.record_elapsed < 1.0


@then("the subscriber queue stays bounded instead of growing without limit")
def queue_bounded(channel_state):
    """Assert the bounded queue never exceeds its configured capacity."""
    subscriber = channel_state.registry.snapshot()[0]
    assert subscriber.queue_size == 2
    assert subscriber.size <= subscriber.queue_size


@given(parsers.parse('a subscriber "{subscriber_id}" that never drains its queue'))
def register_undrained_subscriber(channel_state, subscriber_id):
    """Register a subscriber with no link, so nothing ever drains its queue.

    A connected subscriber that simply stops reading is not deterministic: its
    writer thread still moves queued events into the socket buffer, so whether
    the queue overflows depends on thread scheduling. Registering the
    subscriber without a link removes the writer entirely and makes the drop
    count exactly predictable.
    """
    subscriber = channel_state.registry.register(subscriber_id, ())
    assert subscriber is not None
    channel_state.undrained = subscriber


@when(parsers.parse("the session records {count:d} events"))
def record_events(channel_state, count):
    """Record a fixed number of events through the real fan-out entry point."""
    channel_state.recorded = []
    for index in range(count):
        event = Event(event_type="tool_call.start", payload={"index": index})
        channel_state.recorded.append(event)
        fan_out(event)


@then(parsers.parse("the runtime view reports {count:d} dropped events"))
def runtime_reports_drops(channel_state, count):
    """Assert the operator-visible runtime view reports the drop count."""
    text = runtime_instruction.show_runtime()
    assert f"Dropped total: {count}" in text, text
    assert runtime_state.RUNTIME_STATE_KEY in text


@then("the runtime view reports no dropped events")
def runtime_reports_no_drops(channel_state):
    """Assert a healthy channel publishes no drop state at all."""
    text = runtime_instruction.show_runtime()
    assert "Dropped total" not in text


@given(
    parsers.parse('an approval rule that requires a human decision for tool "{tool_name}"')
)
def approval_rule_requires_human(channel_state, tool_name, monkeypatch):
    """Install a real approval rule that routes the tool through the ASK branch."""
    from topsailai.ai_base.tool_approval import decorator as approval_decorator
    from topsailai.ai_base.tool_approval.instance import ApprovalDecision
    from topsailai.ai_base.tool_approval.transport import ApprovalTransport

    class _RecordingTransport(ApprovalTransport):
        """Transport that records requests and resolves them on demand."""

        def __init__(self):
            self.instances = []
            self.request_ready = threading.Event()
            self._lock = threading.Lock()
            self._events = {}

        def send_request(self, instance):
            """Record the request and signal that it is ready to resolve."""
            self.instances.append(instance)
            with self._lock:
                self._events[instance.id] = threading.Event()
            self.request_ready.set()

        def wait_response(self, instance, timeout=None):
            """Block until the decision is resolved or the timeout expires."""
            with self._lock:
                event = self._events.get(instance.id)
            if event is None:
                return instance.status
            effective = timeout if timeout is not None else instance.timeout
            if event.wait(timeout=effective):
                return instance.status
            return instance.STATUS_TIMEOUT

        def on_resolved(self, instance):
            """Wake the waiter for a resolved instance."""
            with self._lock:
                event = self._events.pop(instance.id, None)
            if event is not None:
                event.set()

        def supports_external_resolution(self):
            """Allow another thread to approve or deny while waiting."""
            return True

        def resolve(self, instance_id, status):
            """Resolve one recorded instance with the given status."""
            instance = next((i for i in self.instances if i.id == instance_id), None)
            if instance is None:
                return
            if status == "approve":
                instance.approve()
            elif status == "deny":
                instance.deny()

    transport = _RecordingTransport()
    channel_state.transport = transport
    channel_state.tool_name = tool_name

    def _decide(self):
        """Force the ASK branch for the configured tool."""
        return ApprovalDecision(
            action=ApprovalDecision.ASK,
            rule=SimpleNamespace(name="bdd-rule"),
            timeout=5.0,
            policy="deny",
        )

    monkeypatch.setattr(
        approval_decorator.ToolApprovalInstance, "decide", _decide, raising=True
    )
    monkeypatch.setattr(
        approval_decorator, "_get_default_transport", lambda: transport, raising=True
    )
    return channel_state


@when(parsers.parse('the tool "{tool_name}" is approved by the human'))
def tool_approved_by_human(channel_state, tool_name):
    """Run the real decorated tool call and approve it from another thread."""
    from topsailai.ai_base.tool_approval.decorator import with_tool_approval

    executed = []

    def _danger_tool(tool_func, args, tool_name=None, **kwargs):
        """Stand-in tool body that records its own execution."""
        executed.append(tool_name)
        return "executed"

    decorated = with_tool_approval(_danger_tool)

    def _approve_later():
        """Approve the pending request once the transport has it."""
        if not channel_state.transport.request_ready.wait(timeout=RECV_TIMEOUT):
            return
        instance = channel_state.transport.instances[0]
        channel_state.transport.resolve(instance.id, "approve")

    thread = threading.Thread(target=_approve_later, daemon=True)
    thread.start()
    channel_state.tool_result = decorated(
        tool_func=_danger_tool, args={"path": "/tmp/x"}, tool_name=tool_name
    )
    thread.join(timeout=RECV_TIMEOUT)
    channel_state.executed = executed
    assert channel_state.tool_result == "executed"
    assert executed == [tool_name]


@then(parsers.parse('subscriber "{subscriber_id}" receives the approval request event'))
def receives_approval_request(channel_state, subscriber_id):
    """Assert the request event arrives over the real link."""
    frame = _read_frame(channel_state.links[subscriber_id])
    assert frame["type"] == "event", frame
    assert frame["event"]["event_type"] == "tool_approval.request", frame
    payload = frame["event"]["payload"]
    assert payload["tool_name"] == channel_state.tool_name
    assert payload["rule_name"] == "bdd-rule"
    assert payload["instance_id"]
    channel_state.approval_instance_id = payload["instance_id"]
    assert "tool_args" not in payload
    assert "/tmp/x" not in json.dumps(payload)


@then(parsers.parse('subscriber "{subscriber_id}" receives the approval decision event'))
def receives_approval_decision(channel_state, subscriber_id):
    """Assert the decision event arrives over the real link."""
    frame = _read_frame(channel_state.links[subscriber_id])
    assert frame["type"] == "event", frame
    assert frame["event"]["event_type"] == "tool_approval.decision", frame
    channel_state.decision_payload = frame["event"]["payload"]


@then(parsers.parse('the approval decision event reports status "{status}"'))
def decision_reports_status(channel_state, status):
    """Assert the decision payload carries the human's real answer."""
    assert channel_state.decision_payload["status"] == status, channel_state.decision_payload
    assert channel_state.decision_payload["tool_name"] == channel_state.tool_name
    assert (
        channel_state.decision_payload["instance_id"]
        == channel_state.approval_instance_id
    ), channel_state.decision_payload


@when("an LLM request is stopped by a hard interrupt")
def hard_interrupt_llm_request(channel_state, monkeypatch):
    """Run the production chat lifecycle until its real interrupt checkpoint."""
    from topsailai.ai_base import llm_base
    from topsailai.ai_base.exception import HardInterruptError

    interrupt = HardInterruptError("BDD hard interrupt")

    class _InterruptingAgent:
        """Raise the exact interruption supplied by the scenario."""

        def _check_hard_interrupt(self):
            raise interrupt

    model = object.__new__(llm_base.LLMModel)
    model.model_name = "bdd-model"
    monkeypatch.setattr(llm_base, "get_agent_object", lambda: _InterruptingAgent())
    try:
        model.chat([{"role": "user", "content": "private BDD prompt"}])
    except HardInterruptError as error:
        channel_state.original_interrupt = interrupt
        channel_state.observed_interrupt = error
    else:
        raise AssertionError("HardInterruptError did not reach the caller")


@then(parsers.parse('subscriber "{subscriber_id}" receives the LLM request start event'))
def receives_llm_request_start(channel_state, subscriber_id):
    """Read the real start frame and retain its operation identifier."""
    frame = _read_frame(channel_state.links[subscriber_id])
    assert frame["type"] == "event", frame
    event = frame["event"]
    assert event["event_type"] == "llm.request.start", frame
    payload = event["payload"]
    assert payload["model_name"] == "bdd-model"
    assert payload["message_count"] == 1
    assert "private BDD prompt" not in json.dumps(payload)
    channel_state.llm_operation_id = payload["operation_id"]


@then(
    parsers.parse(
        'subscriber "{subscriber_id}" receives the interrupted LLM request end event'
    )
)
def receives_interrupted_llm_request_end(channel_state, subscriber_id):
    """Read the real terminal frame and verify interruption classification."""
    frame = _read_frame(channel_state.links[subscriber_id])
    assert frame["type"] == "event", frame
    event = frame["event"]
    assert event["event_type"] == "llm.request.end", frame
    payload = event["payload"]
    assert payload["operation_id"] == channel_state.llm_operation_id
    assert payload["outcome"] == "interrupted"
    assert payload["error_category"] == "HardInterruptError"
    assert payload["attempt_count"] == 0


@then("the original hard interrupt still reaches the caller")
def original_hard_interrupt_preserved(channel_state):
    """Assert telemetry did not replace or swallow the business control signal."""
    assert channel_state.observed_interrupt is channel_state.original_interrupt
