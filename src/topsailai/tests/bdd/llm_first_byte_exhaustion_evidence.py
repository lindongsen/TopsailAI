"""Independent evidence and supervision primitives for U5 exhaustion tests."""

from __future__ import annotations

import inspect
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from tests.bdd.llm_first_byte_deadline_observation import ProvenanceLedger, current_invocation
from topsailai.ai_base.llm_control.exception import LLMProviderTimeoutError


@dataclass
class AttemptEvidence:
    """Store one attempt identity and its bounded evidence bundle."""

    ordinal: int
    invocation: Any = None
    owner: Any = None
    events: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[str] = field(default_factory=list)
    settlement_deadline: float | None = None
    adapter_entry: float | None = None
    release_returned: float | None = None
    raw_event: dict[str, Any] | None = None
    completed_bundle: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        """Expose compatibility reads from the authoritative row."""
        if hasattr(self, key):
            return getattr(self, key)
        return self.metadata[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Read a row field without creating another authority."""
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self, key: str, value: Any) -> None:
        """Store semantic or dynamically observed row data."""
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            self.metadata[key] = value

    def update(self, values: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """Update the same authoritative row."""
        merged = dict(values or {})
        merged.update(kwargs)
        for key, value in merged.items():
            self[key] = value

    def setdefault(self, key: str, default: Any = None) -> Any:
        """Initialize a row field only when it is absent."""
        value = self.get(key)
        if value is None:
            self[key] = default
            return default
        return value

    def accept_event(self, event: dict[str, Any]) -> None:
        """Reject duplicate, null, or conflicting event identity."""
        if event.get("owner") is not self.owner:
            raise AssertionError(f"wrong owner evidence for attempt {self.ordinal}")
        identity = (event.get("kind"), event.get("owner"), event.get("at"))
        if any((item.get("kind"), item.get("owner"), item.get("at")) == identity for item in self.events):
            raise AssertionError(f"duplicate evidence for attempt {self.ordinal}")
        if event.get("kind") == "response_before" and event.get("raw") is None:
            raise AssertionError(f"null raw evidence for attempt {self.ordinal}")
        if len(self.events) >= 256:
            raise AssertionError("attempt event capacity exceeded")
        if event.get("kind") == "response_before" and self.raw_event is not None:
            raise AssertionError("duplicate raw publication")
        self.events.append(dict(event))
        if event.get("kind") == "response_before":
            self.raw_event = next(item for item in self.events if item.get("kind") == "response_before")

    def validate_raw(self, deadline: float) -> dict[str, Any]:
        """Validate exactly one raw response event."""
        candidates = [item for item in self.events if item.get("kind") == "response_before"]
        if len(candidates) != 1:
            raise AssertionError(f"expected one raw event for attempt {self.ordinal}")
        event = candidates[0]
        if event.get("at", float("inf")) > deadline:
            raise AssertionError(f"raw evidence exceeded deadline for attempt {self.ordinal}")
        response = event.get("response")
        raw = event.get("raw")
        if response is None or raw is None or getattr(response, "_response", None) is not raw:
            raise AssertionError(f"raw identity conflict for attempt {self.ordinal}")
        return event


class RunState:
    """Own authoritative attempt state and diagnostic identities."""

    def __init__(self) -> None:
        """Initialize state before workers or resources start."""
        self.condition = threading.Condition()
        self.records: dict[int, AttemptEvidence] = {}
        self.settlements: dict[int, dict[str, Any]] = {}
        self.next_ordinal = 1
        self.first_failure: BaseException | None = None
        self.diagnostics = [[]]
        self.first_host = None
        self.failure_contexts = {}
        self.emergency_error = None
        self.retention_failed = False
        self.overflow_error = AssertionError("diagnostic display capacity exceeded")
        self.overflow_reported = False
        self.annotation_attempted = False
        self.emergency_diagnostic = None
        self.failure_head = None
        self.failure_reserve = [self._new_reserve_cell() for _ in range(256)]
        self.reserve_cursor = 0
        self.publication_saturated = False
        self.saturation_error = AssertionError("diagnostic identity reserve exhausted")
        self.ledger = ProvenanceLedger()
        self.deadline = None
        self.settlement_supervisor_done = False
        self.terminal_error: BaseException | None = None
        self.terminal_at: float | None = None
        self.no_more_settlers = False
        self.coordinator_done = False

    def _new_reserve_cell(self) -> list[Any]:
        """Allocate one independent cell during reserve construction."""
        return [None, None, None, False]


    def _select_failure(self, error):
        """Select primary references before any fallible diagnostic allocation."""
        if self.first_failure is None:
            self.first_failure = error
        if not isinstance(error, Exception) and self.first_host is None:
            self.first_host = error

    def _new_failure_node(self, error, context, previous):
        """Provide a RunState-local allocation seam, independent of display chunks."""
        return [error, context, previous, True]

    def _reserve_failure(self, error, context):
        """Arm one preallocated identity cell without overwriting earlier custody."""
        node = self.failure_head
        while node is not None:
            if node[0] is error:
                return True
            node = node[2]
        if self.reserve_cursor == len(self.failure_reserve):
            self.publication_saturated = True
            return False
        cell = self.failure_reserve[self.reserve_cursor]
        cell[0] = error
        cell[1] = context
        cell[2] = self.failure_head
        cell[3] = True
        self.failure_head = cell
        self.reserve_cursor += 1
        return True

    def _retain_failure(self, error, context):
        """Commit an identity or preserve original and allocator errors in reserve."""
        self._select_failure(error)
        node = self.failure_head
        while node is not None:
            if node[0] is error:
                return True
            node = node[2]
        try:
            node = self._new_failure_node(error, context, self.failure_head)
        except BaseException as allocation_error:
            self.retention_failed = True
            self._select_failure(allocation_error)
            if self.emergency_error is None:
                self.emergency_error = error
                self.emergency_diagnostic = allocation_error
            original_retained = self._reserve_failure(error, context)
            secondary_retained = self._reserve_failure(allocation_error, "journal allocation")
            return original_retained and secondary_retained
        self.failure_head = node
        return True

    def iter_failures(self):
        """Present exact journal and reserve identities in publication order."""
        errors = []
        node = self.failure_head
        while node is not None:
            errors.append(node[0])
            node = node[2]
        return tuple(reversed(errors))

    def publish_failure(self, error, context=None):
        """Report without replacing delegate outcomes or aborting independent cleanup."""
        with self.condition:
            self._select_failure(error)
            try:
                if not self._retain_failure(error, context):
                    return False
                if all(item is not error for chunk in self.diagnostics for item in chunk):
                    if len(self.diagnostics[-1]) == 128:
                        self.diagnostics.append([])
                    self.diagnostics[-1].append(error)
                    self.failure_contexts[id(error)] = context
                    if not self.overflow_reported and sum(map(len, self.diagnostics)) > 128:
                        self.overflow_reported = True
                        self.publish_failure(self.overflow_error, "diagnostic overflow")
            except BaseException as retention_error:
                self.retention_failed = True
                if self.emergency_error is None:
                    self.emergency_error = error
                    self.emergency_diagnostic = retention_error
                self._retain_failure(retention_error, "diagnostic display")
            finally:
                self.condition.notify_all()
            return not self.publication_saturated

    @staticmethod
    def _reaches(error, target):
        """Exclude only attachments that would create an exception-graph cycle."""
        pending = [error]
        seen = set()
        while pending:
            current = pending.pop()
            if current is target:
                return True
            if current is None or id(current) in seen:
                continue
            seen.add(id(current))
            pending.extend((current.__cause__, current.__context__))
            if isinstance(current, BaseExceptionGroup):
                pending.extend(current.exceptions)
            attached = getattr(current, "u5_diagnostics", ())
            pending.extend((attached,) if isinstance(attached, BaseExceptionGroup) else attached)
        return False

    def failure_to_raise(self):
        """Select the earliest original host interruption, otherwise ordinary failure."""
        selected = self.first_host if self.first_host is not None else self.first_failure
        if selected is not None and not self.annotation_attempted:
            self.annotation_attempted = True
            try:
                others = [error for error in self.iter_failures()
                          if error is not selected and not self._reaches(error, selected)]
                # Dedicated references preserve graphs without modifying cause/context edges.
                selected.u5_diagnostics = BaseExceptionGroup("U5 diagnostics", others) if others else ()
            except BaseException as annotation_error:
                self.publish_failure(annotation_error, "diagnostic annotation")
        selected = self.first_host if self.first_host is not None else self.first_failure
        return selected

    def raise_failure(self):
        """Fail before granting normal progress without changing exception identity."""
        error = self.failure_to_raise()
        if error is not None:
            raise error

    def publish_terminal(self, error: BaseException | None = None, at: float | None = None) -> None:
        """Publish terminal exhaustion without classifying it as failure."""
        with self.condition:
            self.terminal_error = error
            self.terminal_at = time.monotonic() if at is None else at
            self.condition.notify_all()

    def seal_settlers(self) -> None:
        """Close settler admission after the final registration."""
        with self.condition:
            self.no_more_settlers = True
            self.condition.notify_all()

    def wait_until(self, predicate, deadline):
        """Check failure before and after every predicate-notified absolute wait."""
        with self.condition:
            while True:
                self.raise_failure()
                if time.monotonic() > deadline:
                    raise AssertionError("state deadline exceeded")
                if predicate():
                    return True
                self.condition.wait(max(0.0, deadline - time.monotonic()))

    def allocate(self, invocation: Any, deadline: float | None = None) -> AttemptEvidence:
        """Allocate one authoritative row and reject a nineteenth attempt."""
        with self.condition:
            ordinal = self.next_ordinal
            if ordinal > 18:
                raise AssertionError("nineteenth attempt observed")
            self.next_ordinal += 1
            row = AttemptEvidence(ordinal=ordinal, invocation=invocation)
            row["entered_at"] = time.monotonic()
            if deadline is not None:
                row["scenario_deadline"] = deadline
            self.records[ordinal] = row
            self.condition.notify_all()
            return row


    def row_for_owner(self, owner):
        """Derive owner lookup from the eighteen authoritative rows."""
        rows = [row for row in self.records.values() if row.owner is owner]
        if len(rows) != 1:
            raise AssertionError("missing or ambiguous owner row")
        return rows[0]

    def active_row(self):
        """Resolve the independently bound invocation, never a thread-ID index."""
        invocation = current_invocation()
        rows = [row for row in self.records.values() if row.invocation is invocation]
        if len(rows) != 1:
            raise AssertionError("missing active invocation")
        return rows[0]

    def safe(self, callback):
        """Keep observation failures from replacing a delegate result or exception."""
        try:
            return callback()
        except BaseException as error:
            self.publish_failure(error)
            return None

    def transparent(self, observer, delegate, *args, **kwargs):
        """Run the delegate exactly once even if an enclosing observer fails."""
        outcome = {}
        def once(*call_args, **call_kwargs):
            """Retain the exact return or raised object before observer finalization."""
            if "called" in outcome:
                raise AssertionError("duplicate delegated call")
            outcome["called"] = True
            try:
                outcome["result"] = delegate(*call_args, **call_kwargs)
                return outcome["result"]
            except BaseException as error:
                outcome["error"] = error
                if not isinstance(error, Exception):
                    self.publish_failure(error, "delegate host")
                raise
        try:
            observer(once)
        except BaseException as error:
            if error is not outcome.get("error"):
                self.publish_failure(error, "delegate observation")
        if "called" not in outcome:
            return once(*args, **kwargs)
        if "error" in outcome:
            raise outcome["error"]
        return outcome["result"]

    def accept_event(self, event):
        """Publish exact owner events after the observer lock has been released."""
        owner = event.get("owner")
        if owner is None:
            if event.get("kind") == "extract" and str(event.get("content", "")).startswith("STALE_"):
                self.publish_failure(AssertionError("stale primary content extracted"))
            return
        row = self.row_for_owner(owner)
        with self.condition:
            row.accept_event(event)
            self.condition.notify_all()

    def wait_raw(self, ordinal, deadline):
        """Validate unique raw publication without polling filtered candidates."""
        row = self.records[ordinal]
        self.wait_until(lambda: row.raw_event is not None, deadline)
        with self.condition:
            return row.validate_raw(deadline)

    def publish_candidate(self, ordinal, candidate):
        """Publish candidate evidence only; the supervisor supplies join proof."""
        with self.condition:
            row = self.records[ordinal]
            row["candidate"] = candidate
            row.transitions.append("settlement_ready")
            self.condition.notify_all()

    def complete_settlement(self, ordinal, joined, *, now):
        """Exclude completed rows before any old-deadline-sensitive validation."""
        with self.condition:
            row = self.records[ordinal]
            if row.completed_bundle is not None:
                return row.completed_bundle
            if joined["thread"] is not row.get("settlement_worker") or joined.get("never_started") is not False:
                raise AssertionError("wrong settler join proof")
            if joined["at"] > row.settlement_deadline or now > row.settlement_deadline:
                raise AssertionError("late completed settlement")
            candidate = row.get("candidate")
            if candidate is None:
                raise AssertionError("settler has no validated candidate")
            row.completed_bundle = dict(candidate, success=True, settler_join=joined, validated_at=now)
            self.settlements[ordinal] = row.completed_bundle
            row.transitions.append("completed")
            self.condition.notify_all()
            return row.completed_bundle

    def snapshot_attempt(self, ordinal):
        """Snapshot external close and callback state outside the Condition."""
        row = self.records[ordinal]
        owner = row.owner
        callbacks = [item for item in self.ledger.snapshot() if item["invocation"] is row.invocation]
        self.ledger.validate(callbacks)
        return {"owner": owner, "invocation": row.invocation, "callbacks": callbacks,
                "events": tuple(dict(item) for item in row.events),
                "close_finished": owner.close_finished_event.is_set(),
                "close_state": getattr(owner._close_state, "name", None),
                "close_error": owner.close_error, "disposal_error": owner.disposal_error,
                "primary_error": owner.primary_error}

    def install(self, model, resources):
        """Install transparent delegates through the sole support patch authority."""
        from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner, current_response_owner
        from topsailai.ai_base.llm_control.first_byte_deadline import current_first_byte_budget
        self.model = model
        observation = resources.prepare_observation(model, self.accept_event, self.publish_failure)
        chat_model = model.chat_model
        original_sdk_create = chat_model.create

        def sdk_create(*args, **kwargs):
            """Capture actual SDK timeout, normalized client and retries at real I/O entry."""
            owner = current_response_owner()
            def capture():
                """Publish transport facts without replacing the original network outcome."""
                row = self.row_for_owner(owner)
                client = chat_model._client
                row["transport"] = {"timeout": kwargs.get("timeout"), "client": client,
                                    "max_retries": client.max_retries, "base_url": str(client.base_url),
                                    "body": {key: value for key, value in kwargs.items() if key != "timeout"}}
            self.safe(capture)
            return original_sdk_create(*args, **kwargs)

        resources.patch(chat_model, "create", sdk_create)
        http_client = chat_model._client._client
        original_send = http_client._send_single_request

        def send(request):
            """Observe actual transport extensions and phase starts on this private client."""
            row = self.safe(lambda: self.row_for_owner(current_response_owner()))
            previous_trace = request.extensions.get("trace")
            def trace(name, info):
                """Retain real HTTP phase anchors without synthesizing network deadlines."""
                self.safe(lambda: row.setdefault("http_phases", []).append({
                    "name": name, "at": time.monotonic(), "thread": threading.current_thread(),
                }))
                if previous_trace is not None:
                    previous_trace(name, info)
            def capture():
                """Copy timeout values used by HTTP transport, not SDK input normalization."""
                row["transport_normalized"] = dict(request.extensions["timeout"], units="seconds")
                row["http_request"] = request
                row["http_thread"] = threading.current_thread()
                request.extensions["trace"] = trace
            self.safe(capture)
            return original_send(request)

        resources.patch(http_client, "_send_single_request", send)
        original_init = AttemptResponseOwner.__init__
        original_call = model.call_llm_model_by_stream
        original_create = model._create_first_byte_response
        original_config = model._get_first_byte_timeout_config
        original_start = model._start_llm_request

        def owner_init(owner, *args, **kwargs):
            """Register cleanup custody before provenance and never seal a constructor ticket."""
            result = original_init(owner, *args, **kwargs)
            self.safe(lambda: resources.register_owner(owner))
            def bind():
                """Bind only through the independently active invocation."""
                self.ledger.register_owner(owner)
                row = self.active_row()
                row.owner = owner
            self.safe(bind)
            return result

        def attempt(*args, **kwargs):
            """Retain exact decorated result/error and close its scheduling scope finally."""
            invocation = self.safe(self.ledger.begin)
            token = self.safe(lambda: self.ledger.bind(invocation)) if invocation is not None else None
            row = self.safe(lambda: self.allocate(invocation, self.deadline))
            self.safe(lambda: row.update(invocation_thread=threading.current_thread()))
            def record(**values):
                """Publish decorated outcome without replacing the delegate."""
                if row is not None:
                    with self.condition:
                        row.update(values)
                        self.condition.notify_all()
            try:
                result = original_call(*args, **kwargs)
                self.safe(lambda: record(result=result))
                return result
            except BaseException as error:
                self.safe(lambda: record(error=error, timeout=isinstance(error, LLMProviderTimeoutError), error_at=time.monotonic()))
                raise
            finally:
                self.safe(lambda: record(invocation_exited=True))
                if token is not None:
                    self.safe(lambda: self.ledger.reset(token))

        def config(*args, **kwargs):
            """Return the exact configuration result while recording actual reads."""
            before = time.monotonic()
            value = original_config(*args, **kwargs)
            after = time.monotonic()
            def record():
                """Bind the configuration return to its actual invocation and thread."""
                row = self.active_row()
                row.setdefault("configs", []).append(value)
                row.setdefault("config_boundaries", []).append({
                    "value": value, "invocation": row.invocation,
                    "thread": threading.current_thread(), "before": before, "after": after,
                })
            self.safe(record)
            return value

        def start(*args, **kwargs):
            """Seal the real returned start ticket with an independently bound owner."""
            owner = current_response_owner()
            before = time.monotonic()
            value = original_start(*args, **kwargs)
            after = time.monotonic()
            def record():
                """Retain the actual timing checkpoint."""
                self.ledger.seal_ticket(value, owner)
                self.ledger.record_start(owner, value)
                self.row_for_owner(owner).update(
                    ticket=value, start_at=after,
                    start_boundary={"before": before, "after": after, "owner": owner,
                                    "thread": threading.current_thread(), "ticket": value,
                                    "invocation": self.row_for_owner(owner).invocation},
                )
            self.safe(record)
            return value

        def create(params):
            """Publish adapter entry before performing the saved network operation."""
            def publish():
                """Publish pre-I/O entry without allowing observation to suppress I/O."""
                row = self.row_for_owner(current_response_owner())
                with self.condition:
                    row.adapter_entry = time.monotonic()
                    row.update(params=dict(params), release_deadline=min(self.deadline, row.adapter_entry + 3),
                               raw_deadline=min(self.deadline, row.adapter_entry + 4))
                    self.condition.notify_all()
            self.safe(publish)
            return original_create(params)

        def wrap_schedule(name):
            """Observe actual owner scheduling calls and preserve delegate outcomes."""
            original = getattr(AttemptResponseOwner, name)
            def scheduled(owner, *args, **kwargs):
                """Exit scheduling authority even when the original raises."""
                token = object()
                self.safe(lambda: resources.note_spawn_scope(owner, name, token, "ENTERED"))
                try:
                    result = original(owner, *args, **kwargs)
                finally:
                    self.safe(lambda: resources.note_spawn_scope(owner, name, token, "EXITED"))
                def record():
                    """Record observations without changing the delegated result."""
                    row = self.row_for_owner(owner)
                    if name == "abandon":
                        row.update(abandoned=owner._abandoned, abandoned_at=time.monotonic())
                    if name == "publish_response":
                        row.update(response=args[0], publication=result)
                    with self.condition:
                        self.condition.notify_all()
                self.safe(record)
                return result
            resources.patch(AttemptResponseOwner, name, scheduled)

        def wrap_callback(name):
            """Use the existing ledger for exact callback provenance."""
            original = getattr(model, name)
            def callback(ticket):
                """Record the real callback without replacing its raised object."""
                before = time.monotonic()
                def observe(call):
                    """Bracket the actual callback and retain the ledger's independent binding."""
                    def completed(record):
                        """Publish after the real callback returns without changing its outcome."""
                        row = self.row_for_owner(record["initiator"])
                        self.safe(lambda: row.setdefault("callback_boundaries", []).append(
                            dict(record, before=before, after=time.monotonic())))
                    return self.ledger.observe_callback(
                        name.removeprefix("_").removesuffix("_llm_request"), call, ticket,
                        on_completion=completed)
                return self.transparent(observe, original, ticket)
            resources.patch(model, name, callback)

        def guard(*args, **kwargs):
            """Observe the actual shared create budget and spawning scope."""
            row = self.safe(self.active_row)
            arguments = inspect.signature(original_guard).bind(*args, **kwargs)
            arguments.apply_defaults()
            budget = kwargs.get("budget")
            if budget is None:
                budget = current_first_byte_budget()
            self.safe(lambda: row.update(budget=budget))
            before = time.monotonic()
            self.safe(lambda: row.update(create_budget_facts={
                "budget": budget, "timeout": budget.timeout, "deadline": budget.deadline,
                "before": before, "remaining": budget.remaining(), "after": time.monotonic(),
                "timeout_seconds": arguments.arguments["first_byte_timeout"],
                "raise_on_timeout": arguments.arguments["raise_on_timeout"],
            }))
            token = object()
            self.safe(lambda: resources.note_spawn_scope(row.owner, "create_guard", token, "ENTERED"))
            try:
                return original_guard(*args, **kwargs)
            finally:
                self.safe(lambda: resources.note_spawn_scope(row.owner, "create_guard", token, "EXITED"))

        original_stream_guard = model.iter_stream_with_first_byte_timeout

        def stream_guard(*args, **kwargs):
            """Observe generator execution and its real first-entry spawning authority."""
            row = self.safe(self.active_row)
            budget = current_first_byte_budget()
            self.safe(lambda: row.update(first_item_budget=budget))
            before = time.monotonic()
            self.safe(lambda: row.update(first_item_budget_facts={
                "budget": budget, "timeout": budget.timeout, "deadline": budget.deadline,
                "before": before, "remaining": budget.remaining(), "after": time.monotonic(),
            }))
            token = object()
            self.safe(lambda: resources.note_spawn_scope(row.owner, "first_item_guard", token, "ENTERED"))
            try:
                yield from original_stream_guard(*args, **kwargs)
            finally:
                self.safe(lambda: resources.note_spawn_scope(row.owner, "first_item_guard", token, "EXITED"))

        original_guard = model._create_with_first_byte_timeout
        resources.patch(AttemptResponseOwner, "__init__", owner_init)
        for name in ("abandon", "publish_response", "dispose"):
            wrap_schedule(name)
        for name in ("_pause_llm_request", "_resume_llm_request", "_finish_llm_request"):
            wrap_callback(name)
        resources.patch(model, "call_llm_model_by_stream", attempt)
        resources.patch(model, "_get_first_byte_timeout_config", config)
        resources.patch(model, "_start_llm_request", start)
        resources.patch(model, "_create_first_byte_response", create)
        resources.patch(model, "_create_with_first_byte_timeout", guard)
        resources.patch(model, "iter_stream_with_first_byte_timeout", stream_guard)
        return observation





__all__ = ["AttemptEvidence", "RunState"]
