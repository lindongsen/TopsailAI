"""Real HTTP/SSE harness for abandoned first-byte request ownership."""
from __future__ import annotations
import json
import threading
import time
from typing import Any
from unittest.mock import patch
from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_pool.openai_client_pool import (
    OpenAIClientPool,
    OpenAIResponseAdapter,
)
from topsailai.ai_base.llm_pool.provider_registry import (
    LLMProviderBackend,
    LLMProviderRegistry,
    default_provider_registry,
)
from topsailai.ai_base.llm_control.exception import LLMProviderReadError
from topsailai.ai_base.llm_control.response_ownership import (
    AttemptResponseOwner,
    current_response_owner,
)
from topsailai.events import record_event as real_record_event
STALE_OLD = "STALE_OLD"
FRESH_SECOND = "FRESH_SECOND"
SIBLING = "SIBLING"
class FirstByteOwnershipScenario:
    """Own one real loopback provider, model, and observable request attempt."""
    def __init__(self, monkeypatch: Any, phase: str):
        """Initialize the scenario and clean partial setup on failure."""
        self.monkeypatch = monkeypatch
        self.phase = phase
        self.server = None
        self.server_thread = None
        self._server_started = False
        self.model = None
        self._sibling_model = None
        self._sibling_thread = None
        self._patches = []
        self._attempt_workers = []
        self._attempt_owners = []
        self._owner_by_worker_ident = {}
        try:
            self._initialize(monkeypatch, phase)
        except BaseException as error:
            try:
                self.close(primary=error)
            except BaseException as cleanup_error:
                raise cleanup_error from error
            raise
    def _initialize(self, monkeypatch: Any, phase: str):
        """Configure a phase-specific delayed first request."""
        self.monkeypatch = monkeypatch
        self.phase = phase
        header_delays = (60.0, 0.0, 0.0, 0.0) if phase == "headers" else (0.0, 0.0, 0.0, 0.0)
        first_item_delays = (5.0, 0.0, 5.0, 0.0) if phase == "first_item" else (0.0, 0.0, 60.0, 0.0)
        self.server = create_server(MockServerConfig(
            port=0,
            request_body_capacity=8,
            lifecycle_capacity=8,
            stream_response_chunks=((STALE_OLD,), (FRESH_SECOND,), (SIBLING,), ("FOLLOW_UP",)),
            response_header_delays=header_delays,
            first_chunk_delays=first_item_delays,
        ))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-first-byte-server",
            daemon=True,
        )
        self.server_thread.start()
        self._server_started = True
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        for key, value in {
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "bdd-first-byte",
            "OPENAI_MODEL": "topsailai-first-byte",
            "LLM_RESPONSE_STREAM": "1",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0.25",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE": "1",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "1",
            "TOPSAILAI_EVENTS_ENABLED": "0",
            "TOPSAILAI_PRINT_TOOL_STAT": "0",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
        }.items():
            monkeypatch.setenv(key, value)
        self.pool = OpenAIClientPool()
        self.pool_close_count = 0
        self.pool_invalidate_count = 0
        self.pool_acquisition_events: list[dict[str, Any]] = []
        self._install_isolated_provider()
        self.model = LLMModel(provider_registry=self.provider_registry)
        self.model_lease = self.model.snapshot_llm_model_leases()[0]
        self.sent: list[str] = []
        self.usage: list[Any] = []
        self.events: list[dict[str, Any]] = []
        self.closed_raw: list[tuple[int, bool, dict[str, Any] | None]] = []
        self.raw_by_request: dict[int, Any] = {}
        self.raw_close_events: dict[int, threading.Event] = {}
        self.raw_close_started_events: dict[int, threading.Event] = {}
        self.raw_ready_events: dict[int, threading.Event] = {}
        self.close_counts: dict[int, int] = {}
        self.late_errors: dict[int, list[BaseException]] = {}
        self.adapter_attempts: list[Any] = []
        self.worker_ledger: list[dict[str, Any]] = []
        self._owner_observations: dict[int, dict[str, Any]] = {}
        self._raw_owner_by_id: dict[int, Any] = {}
        self._late_errors_by_owner: dict[int, list[BaseException]] = {}
        self._late_errors: list[BaseException] = []
        self._sibling_started = False
        self._attempt_workers: list[threading.Thread] = []
        self._attempt_owners: list[Any] = []
        self._patches = []
        self._install_observers()
    def _install_isolated_provider(self) -> None:
        """Route scenario models through one isolated observable client pool."""
        backend = default_provider_registry.resolve("openai")
        original_acquire = self.pool.acquire
        original_invalidate = self.pool.invalidate
        original_close_entries = self.pool._close_entries
        def acquire(config):
            """Record the real pool acquisition boundary before returning a lease."""
            handle = original_acquire(config)
            event = {
                "acquisition_id": len(self.pool_acquisition_events) + 1,
                "client": handle.client,
                "client_id": id(handle.client),
                "key": handle.key,
                "generation": handle.generation,
                "lease_token": object(),
                "thread_id": threading.get_ident(),
                "chat_model": None,
            }
            self.pool_acquisition_events.append(event)
            return handle
        def get_chat_model(client):
            """Return a lease-bound proxy before the adapter admits a request."""
            actual = backend.get_chat_model(client)
            candidates = [event for event in self.pool_acquisition_events
                          if event["client"] is client and event["chat_model"] is None]
            assert len(candidates) == 1, (id(client), candidates)
            event = candidates[0]
            class LeaseBoundChatModel:
                """Keep the actual acquisition token on the model used by the adapter."""
                def __init__(proxy):
                    proxy.lease_token = event["lease_token"]
                    proxy.actual = actual
                def create(proxy, *args, **kwargs):
                    """Delegate the real request without changing transport behavior."""
                    return proxy.actual.create(*args, **kwargs)
            chat_model = LeaseBoundChatModel()
            event["chat_model"] = chat_model
            event["actual_chat_model"] = actual
            event["chat_model_token"] = chat_model.lease_token
            return chat_model
        def invalidate(value):
            self.pool_invalidate_count += 1
            return original_invalidate(value)
        def close_entries(entries):
            self.pool_close_count += len(entries)
            return original_close_entries(entries)
        self.pool.acquire = acquire
        self.pool.invalidate = invalidate
        self.pool._close_entries = close_entries
        self.provider_registry = LLMProviderRegistry()
        self.provider_registry.register(LLMProviderBackend(
            name=backend.name,
            config_factory=backend.config_factory,
            acquire=self.pool.acquire,
            invalidate=self.pool.invalidate,
            get_chat_model=get_chat_model,
            response_adapter=backend.response_adapter,
            model_name_resolver=backend.model_name_resolver,
            api_base_resolver=backend.api_base_resolver,
            api_key_resolver=backend.api_key_resolver,
        ))
    def _install_observers(self) -> None:
        """Wrap real adapter close and real event dispatch without replacing I/O."""
        original_close = OpenAIResponseAdapter._ClosableOpenAIStream.close
        def close(stream):
            """Call the real raw HTTP response close and record its state."""
            raw = stream._response.response
            request_body = None
            request = getattr(raw, "request", None)
            content = getattr(request, "content", None)
            if content:
                try:
                    request_body = json.loads(content)
                except (TypeError, ValueError):
                    request_body = None
            raw_id = id(raw)
            result = original_close(stream)
            self.closed_raw.append((raw_id, bool(getattr(raw, "is_closed", False)), request_body))
            self.close_counts[raw_id] = self.close_counts.get(raw_id, 0) + 1
            for ordinal, candidate in self.raw_by_request.items():
                if candidate is raw:
                    self.raw_close_events[ordinal].set()
                    break
            return result
        original_create_response = OpenAIResponseAdapter.create_response
        def create_response(adapter_cls, chat_model, params):
            """Record request admission before invoking the real SDK call."""
            ordinal = len(self.adapter_attempts) + 1
            owner = current_response_owner()
            observation = {"ordinal": ordinal, "params": json.loads(json.dumps(params)),
                           "owner": owner, "chat_model": id(chat_model), "wrapper": None, "raw": None,
                           "raw_ready": threading.Event(), "late_errors": [],
                           "admitted": True,
                           "acquisition_count": len(self.pool_acquisition_events),
                           "acquisition_id": None,
                           "acquisition_use": None,
                           "acquisition_token": getattr(chat_model, "lease_token", None)}
            acquisition = next((event for event in self.pool_acquisition_events
                                if event["chat_model"] is chat_model), None)
            observation["acquisition_id"] = acquisition["acquisition_id"] if acquisition else None
            assert acquisition is not None, (ordinal, chat_model, self.pool_acquisition_events)
            acquisition["used_by"] = ordinal
            assert observation["acquisition_token"] is acquisition["lease_token"]
            observation["acquisition_use"] = {"acquisition_id": acquisition["acquisition_id"],
                                               "chat_model": chat_model,
                                               "thread_id": threading.get_ident()}
            self.adapter_attempts.append(observation)
            if owner is not None:
                self._owner_observations[id(owner)] = observation
                if owner not in self._attempt_owners:
                    self._attempt_owners.append(owner)
            wrapped = original_create_response.__func__(adapter_cls, chat_model, params)
            if params.get("stream"):
                observation["wrapper"] = wrapped
                observation["raw"] = wrapped._response.response
                self._raw_owner_by_id[id(observation["raw"])] = owner
                self.raw_by_request[ordinal] = observation["raw"]
                self.raw_close_events[ordinal] = threading.Event()
                self.raw_close_started_events[ordinal] = threading.Event()
                self.raw_ready_events[ordinal] = observation["raw_ready"]
                self.late_errors[ordinal] = observation["late_errors"]
                raw_close = observation["raw"].close
                observation["raw_close_invocations"] = []
                def mark_raw_close(*args, _raw_close=raw_close, _ordinal=ordinal, **kwargs):
                    observation = self.adapter_attempts[_ordinal - 1]
                    thread_id = threading.get_ident()
                    mapped_owner = self._raw_owner_by_id.get(id(observation["raw"]))
                    executing_owner = next((candidate for candidate in self._attempt_owners
                                            for name in ("create_thread", "fetch_thread", "cleanup_thread")
                                            if getattr(candidate, name, None) is not None
                                            and getattr(candidate, name).ident == thread_id), None)
                    invoking_owner = current_response_owner() or executing_owner
                    observation["raw_close_invocations"].append({
                        "owner": mapped_owner,
                        "invoking_owner": invoking_owner,
                        "executing_owner": executing_owner,
                        "thread_id": thread_id,
                    })
                    self.raw_close_started_events[_ordinal].set()
                    return _raw_close(*args, **kwargs)
                observation["raw"].close = mark_raw_close
                observation["raw_ready"].set()
            return wrapped
        self._patches.append(patch.object(
            OpenAIResponseAdapter, "create_response", classmethod(create_response)
        ))
        self._patches.append(patch.object(
            OpenAIResponseAdapter._ClosableOpenAIStream, "close", close
        ))
        self._patches.append(patch(
            "topsailai.events.record_event", self._record_event
        ))
        original_owner_init = AttemptResponseOwner.__init__
        def owner_init(owner):
            """Register owner custody at owner creation, before publication."""
            original_owner_init(owner)
            self._attempt_owners.append(owner)
            self.worker_ledger.append({"ordinal": self._owner_observations.get(id(owner), {}).get("ordinal"), "owner": owner, "workers": {}, "status": "created"})
        self._patches.append(patch.object(AttemptResponseOwner, "__init__", owner_init))
        original_publish_response = AttemptResponseOwner.publish_response
        def publish_response(owner, response):
            accepted = original_publish_response(owner, response)
            for observation in self.adapter_attempts:
                if response is observation.get("wrapper") or response is observation.get("raw"):
                    self._owner_observations[id(owner)] = observation
                    observation["owner"] = owner
                    if owner not in self._attempt_owners:
                        self._attempt_owners.append(owner)
                    break
            return accepted
        self._patches.append(patch.object(AttemptResponseOwner, "publish_response", publish_response))
        original_publish_error = AttemptResponseOwner.publish_error
        def publish_error(owner, error, *, phase="create"):
            accepted = original_publish_error(owner, error, phase=phase)
            if not accepted and phase == "first_item":
                self._late_errors.append(error)
                self._late_errors_by_owner.setdefault(id(owner), []).append(error)
                observation = self._owner_observations.get(id(owner))
                if observation is not None:
                    observation["late_errors"].append(error)
            return accepted
        self._patches.append(patch.object(AttemptResponseOwner, "publish_error", publish_error))
        for active_patch in self._patches:
            active_patch.start()
        class Sender:
            """Capture production content sends and completion."""
            def __init__(sender):
                sender.finished = False
            def send(sender, content):
                """Capture content delivered by the production stream loop."""
                self.sent.append(content)
            def send_content(sender, content):
                """Retain the legacy helper while using the production protocol."""
                sender.send(content)
            def finish(sender):
                """Record sender completion."""
                sender.finished = True
        self.root_close_started = 0
        self.root_close_events = []
        root_client = self.model_lease.client
        original_root_close = root_client.close
        def observed_root_close(*args, **kwargs):
            self.root_close_started += 1
            self.root_close_events.append(id(root_client))
            return original_root_close(*args, **kwargs)
        root_client.close = observed_root_close
        self._root_client = root_client
        self._original_root_close = original_root_close
        self.model.content_senders.append(Sender())
        original_finalize = self.model.tokenStat.finalize_usage
        def finalize(ticket, request_ticket, content):
            """Record usage finalization while preserving the real operation."""
            self.usage.append(content)
            return original_finalize(ticket, request_ticket, content)
        self.model.tokenStat.finalize_usage = finalize
    def _record_event(self, name, *, payload, source):
        """Record the real event payload without sending it to the backend."""
        self.events.append({"name": name, "payload": payload, "source": source})
        return real_record_event(name, payload=payload, source=source)
    def run_retry(self):
        """Run the production chat/retry pipeline against the real server."""
        return self.model.chat(
            [{"role": "user", "content": "ownership request"}],
            for_raw=True,
            for_stream=True,
        )
    def state(self) -> dict[str, Any]:
        """Read request counts, bodies, and lifecycle records over HTTP."""
        import urllib.request
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.server.server_port}/debug/state", timeout=5
        ) as response:
            return json.load(response)
    def release_old(self) -> None:
        """Release the first request after the replacement succeeded."""
        self.server.lifecycle_capture.request_handle(1).release_delay()
    def wait_for_raw_ready_registration(self, ordinal: int, timeout: float = 5) -> threading.Event:
        """Wait until the real adapter has registered an ordinal's raw-ready event."""
        deadline = time.monotonic() + timeout
        while ordinal not in self.raw_ready_events and time.monotonic() < deadline:
            time.sleep(0.01)
        event = self.raw_ready_events.get(ordinal)
        assert event is not None, (ordinal, self.adapter_attempts)
        return event
    def join_attempt_workers(self, *, ordinals=None) -> None:
        """Join exact registered attempt workers and require expected attempts."""
        wanted = set(ordinals) if ordinals is not None else None
        observations = [item for item in self.adapter_attempts if wanted is None or item["ordinal"] in wanted]
        if wanted is not None:
            assert {item["ordinal"] for item in observations} == wanted, (wanted, observations)
        for observation in observations:
            owner = observation.get("owner")
            assert owner is not None, ("missing response owner", observation["ordinal"])
            if owner not in self._attempt_owners:
                self._attempt_owners.append(owner)
            ledger = {"ordinal": observation["ordinal"], "owner": owner, "workers": {}}
            for name in ("create_thread", "fetch_thread", "cleanup_thread"):
                worker = getattr(owner, name, None)
                if worker is None:
                    continue
                if worker not in self._attempt_workers:
                    self._attempt_workers.append(worker)
                if worker.ident is not None:
                    self._owner_by_worker_ident[worker.ident] = owner
                worker.join(timeout=30)
                assert not worker.is_alive(), (observation["ordinal"], name)
                ledger["workers"][name] = worker
            assert owner.close_error is None, (observation["ordinal"], owner.close_error)
            ledger["close_state"] = getattr(owner._close_state, "name", None)
            self.worker_ledger.append(ledger)
    def assert_first_item_settled(self) -> None:
        """Assert first-item close initiation and expected late read evidence."""
        observation = next((item for item in self.adapter_attempts if item["ordinal"] == 1), None)
        assert observation is not None, self.adapter_attempts
        owner = observation["owner"]
        assert owner is not None, observation
        old_raw = self.raw_by_request.get(1)
        assert old_raw is not None, self.adapter_attempts
        assert self.raw_close_started_events[1].wait(5)
        assert observation["raw"] is old_raw, (observation["raw"], old_raw)
        assert observation["raw_close_invocations"], observation
        invocation = observation["raw_close_invocations"][0]
        assert invocation["owner"] is owner
        assert invocation["executing_owner"] is owner, invocation
        assert invocation["invoking_owner"] is owner, invocation
        assert isinstance(invocation["thread_id"], int) and invocation["thread_id"] > 0
        deadline = time.monotonic() + 15
        late_errors = observation["late_errors"]
        while not late_errors and not self._late_errors_by_owner.get(id(owner)) and time.monotonic() < deadline:
            time.sleep(0.01)
        late_errors = late_errors or self._late_errors_by_owner.get(id(owner), [])
        assert late_errors, (observation, owner.close_error)
        assert len(late_errors) == 1, late_errors
        late_error = late_errors[0]
        assert getattr(owner._close_state, "name", None) != "FAILED", owner._close_state
        assert owner.disposal_error is None, owner.disposal_error
        assert owner.close_error in (None, late_error), (owner.close_error, late_error)
        assert isinstance(late_error, LLMProviderReadError), late_errors
        assert str(late_error).casefold().endswith("bad file descriptor"), late_errors
        self.join_attempt_workers(ordinals={2})
        assert self.sent == [FRESH_SECOND], self.sent
        assert self.usage == [FRESH_SECOND], self.usage
        assert all(STALE_OLD not in str(item) for item in self.events)
    def assert_body_mismatch_rejected(self) -> None:
        """Require the body contract assertion to reject a mismatched body."""
        state = self.state()
        bodies = [record["body"] for record in state["request_bodies"]]
        assert len(bodies) == 2, state
        mismatched = json.loads(json.dumps(bodies[1]))
        mismatched["messages"][-1]["content"] = "unexpected body"
        try:
            self._assert_request_body_contract(bodies[0], mismatched)
        except AssertionError:
            return
        raise AssertionError("body mismatch was not rejected")
    @staticmethod
    def _assert_request_body_contract(actual, expected) -> None:
        """Validate the complete request body contract used by the scenario."""
        assert actual == expected, (actual, expected)
    def assert_post_settlement_root_close(self) -> None:
        """Require a direct root-client close event after worker settlement."""
        assert self.root_close_started == 0
        self._root_client.close()
        assert self.root_close_started == 1
        assert self.root_close_events == [id(self._root_client)]
    def assert_settled(self, expected_content: str) -> None:
        """Assert exact retry evidence and absence of stale publication."""
        state = self.state()
        assert state["total_requests"] == 2, state
        bodies = [record["body"] for record in state["request_bodies"]]
        assert len(bodies) == 2
        self._assert_request_body_contract(bodies[0], bodies[1])
        assert bodies[0]["model"] == "topsailai-first-byte"
        assert bodies[0]["messages"] == bodies[1]["messages"]
        assert bodies[0]["messages"][-1] == {"role": "user", "content": "ownership request"}
        assert self.adapter_attempts[0]["params"] == bodies[0]
        assert self.adapter_attempts[1]["params"] == bodies[1]
        assert expected_content == FRESH_SECOND
        if self.phase == "first_item":
            self.assert_first_item_settled()
            return
        self.join_attempt_workers()
        assert self.sent == [FRESH_SECOND], self.sent
        assert self.usage == [FRESH_SECOND], self.usage
        assert all(STALE_OLD not in str(item) for item in self.events)
        assert self.wait_for_raw_ready_registration(1).wait(5)
        old_raw = self.raw_by_request.get(1)
        assert old_raw is not None, self.adapter_attempts
        assert self.raw_close_events[1].wait(5)
        assert old_raw.is_closed
        assert any(raw_id == id(old_raw) and is_closed for raw_id, is_closed, _ in self.closed_raw)
        old = self.server.lifecycle_capture.request_handle(1)
        assert old.response_finished.wait(5)
        assert old.connection_closed.wait(5)
        assert old.wait_for_thread_exit(5)
    def _assert_server_thread_exited(self) -> None:
        """Join the server only when started and report failure to exit."""
        thread = getattr(self, "server_thread", None)
        if thread is None:
            return
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("server worker did not exit during teardown")
    def close(self, primary: BaseException | None = None) -> None:
        """Release resources, settle exact workers, and preserve all failures."""
        failures: list[BaseException] = []
        server = getattr(self, "server", None)
        if server is not None:
            for number in range(1, 9):
                try:
                    server.lifecycle_capture.request_handle(number).release_delay()
                except KeyError:
                    pass
                except BaseException as error:
                    failures.append(error)
        sibling_thread = getattr(self, "_sibling_thread", None)
        if sibling_thread is not None:
            try:
                sibling_thread.join(timeout=5)
                if sibling_thread.is_alive():
                    failures.append(RuntimeError("sibling worker did not exit during teardown"))
            except BaseException as error:
                failures.append(error)
        # Discover every worker from every owner, including attempts not reached by assertions.
        for owner in list(getattr(self, "_attempt_owners", [])):
            for name in ("create_thread", "fetch_thread", "cleanup_thread"):
                worker = getattr(owner, name, None)
                if worker is not None and worker not in self._attempt_workers:
                    self._attempt_workers.append(worker)
                if worker is None:
                    continue
                try:
                    worker.join(timeout=30)
                    if worker.is_alive():
                        message = f"attempt worker did not exit: {worker.name}"
                        ordinal = self._owner_observations.get(id(owner), {}).get("ordinal")
                        invocations = self._owner_observations.get(id(owner), {}).get("raw_close_invocations", [])
                        entered_raw_close = any(item["owner"] is owner
                                                and item["executing_owner"] is owner
                                                and item["thread_id"] == worker.ident
                                                for item in invocations)
                        allowed = (getattr(self, "phase", None) == "first_item"
                                   and ordinal == 1 and getattr(owner, "_abandoned", False)
                                   and name in {"fetch_thread", "cleanup_thread"}
                                   and (name == "fetch_thread" or entered_raw_close))
                        if allowed:
                            report = {"ordinal": ordinal, "owner_id": id(owner), "worker_name": worker.name,
                                      "status": "reported-exempt-blocked"}
                            self.worker_ledger.append(report)
                            print(f"U2 unresolved worker report: {report}", flush=True)
                        else:
                            failures.append(RuntimeError(message))
                except BaseException as error:
                    failures.append(error)
            close_error = getattr(owner, "close_error", None)
            disposal_error = getattr(owner, "disposal_error", None)
            if disposal_error is not None:
                failures.append(disposal_error)
            ordinal = self._owner_observations.get(id(owner), {}).get("ordinal")
            expected_late = (getattr(self, "phase", None) == "first_item" and ordinal == 1
                             and getattr(owner, "_abandoned", False)
                             and isinstance(close_error, LLMProviderReadError)
                             and "bad file descriptor" in str(close_error).casefold())
            if close_error is not None and disposal_error is None and not expected_late:
                failures.append(close_error)
            if getattr(owner._close_state, "name", None) == "FAILED" and disposal_error is None:
                failures.append(RuntimeError(f"owner disposal state FAILED without disposal_error: {ordinal}"))
        operations = (
            lambda: getattr(self, "model", None) and self.model.close(),
            lambda: getattr(self, "_sibling_model", None) and self._sibling_model.close(),
            lambda: server and server.stop_handlers(timeout=5),
            lambda: getattr(self, "pool", None) and self.pool.close_all(),
            lambda: server and server.shutdown() if getattr(self, "_server_started", False) else None,
            lambda: server and server.server_close(),
            lambda: self._assert_server_thread_exited(),
        )
        for operation in operations:
            try:
                operation()
            except BaseException as error:
                failures.append(error)
        root_client = getattr(self, "_root_client", None)
        original_root_close = getattr(self, "_original_root_close", None)
        if root_client is not None and original_root_close is not None:
            root_client.close = original_root_close
        for active_patch in reversed(getattr(self, "_patches", [])):
            try:
                active_patch.stop()
            except BaseException as error:
                failures.append(error)
        if primary is not None:
            if failures:
                raise BaseExceptionGroup("scenario cleanup failed", [primary, *failures]) from primary
            return
        if failures:
            raise BaseExceptionGroup("scenario cleanup failed", failures)
class SharedPoolOwnershipScenario(FirstByteOwnershipScenario):
    """Exercise abandoned close while a sibling request shares the root client."""
    def run_sibling_flow(self):
        """Run retry and keep the sibling genuinely held for later checks."""
        fresh = self.run_retry()
        sibling_model = LLMModel(model_name="topsailai-first-byte", provider_registry=self.provider_registry)
        sibling_lease = sibling_model.snapshot_llm_model_leases()[0]
        assert sibling_lease.client is self.model_lease.client
        assert sibling_lease.key == self.model_lease.key
        assert sibling_lease.generation == self.model_lease.generation
        self.sibling_lease = sibling_lease
        self.root_identity = id(self.model_lease.client)
        self.root_generation = self.model_lease.generation
        sibling_result: list[Any] = []
        sibling_error: list[BaseException] = []
        def run_sibling() -> None:
            try:
                sibling_result.append(sibling_model.chat(
                    [{"role": "user", "content": "sibling request"}],
                    for_raw=True, for_stream=True,
                ))
            except BaseException as error:
                sibling_error.append(error)
        sibling_thread = threading.Thread(target=run_sibling, name="bdd-sibling-request")
        self._sibling_model = sibling_model
        self._sibling_thread = sibling_thread
        self._sibling_result = sibling_result
        self._sibling_error = sibling_error
        sibling_thread.start()
        self._sibling_started = True
        assert self.server.lifecycle_capture.wait_for_request(3, timeout=5)
        assert self.server.lifecycle_capture.wait_for_phase(3, "first_item", timeout=5)
        return fresh, None
    def assert_sibling_held(self) -> None:
        """Prove the sibling remains held and has not produced output."""
        assert id(self.sibling_lease.client) == self.root_identity
        assert self.sibling_lease.generation == self.root_generation
        assert self.pool_invalidate_count == 0
        assert self.pool_close_count == 0
        handle = self.server.lifecycle_capture.request_handle(3)
        assert handle.record["waiting_phase"] == "first_item"
    def release_old_and_prove_isolation(self) -> None:
        """Release only the old request and verify the sibling remains held."""
        self.release_old()
        if self.phase == "first_item":
            self.assert_first_item_settled()
        else:
            old = self.server.lifecycle_capture.request_handle(1)
            assert old.response_finished.wait(5)
            assert old.connection_closed.wait(5)
            assert old.wait_for_thread_exit(5)
            assert self.wait_for_raw_ready_registration(1).wait(5)
            old_raw = self.raw_by_request.get(1)
            assert old_raw is not None, self.adapter_attempts
            assert self.raw_close_events[1].wait(5)
            assert old_raw.is_closed
            self.join_attempt_workers(ordinals={1})
        self.assert_sibling_held()
    def run_follow_up_while_sibling_held(self):
        """Run a follow-up before releasing the sibling request."""
        self.assert_sibling_held()
        result = self.model.chat(
            [{"role": "user", "content": "follow up"}],
            for_raw=True, for_stream=True,
        )
        follow_up_observations = [item for item in self.adapter_attempts
                                  if item["params"].get("messages", [{}])[-1].get("content") == "follow up"]
        assert len(follow_up_observations) == 1, follow_up_observations
        follow_up_observation = follow_up_observations[0]
        assert follow_up_observation.get("owner") is not None
        assert follow_up_observation["acquisition_count"] >= 1
        acquisition = next((event for event in self.pool_acquisition_events
                            if event["acquisition_id"] == follow_up_observation["acquisition_id"]), None)
        assert acquisition is not None, self.pool_acquisition_events
        assert acquisition["chat_model"] is not None
        assert acquisition["lease_token"] is follow_up_observation["acquisition_token"]
        assert acquisition["chat_model"] is not None
        assert id(acquisition["chat_model"]) == follow_up_observation["chat_model"]
        assert acquisition["client"] is self.model_lease.client
        assert acquisition["key"] == self.sibling_lease.key
        assert acquisition["generation"] == self.root_generation
        assert acquisition.get("used_by") == follow_up_observation["ordinal"]
        assert follow_up_observation["acquisition_use"]["acquisition_id"] == acquisition["acquisition_id"]
        assert follow_up_observation["acquisition_use"]["chat_model"] is acquisition["chat_model"]
        assert follow_up_observation["acquisition_use"]["acquisition_id"] == acquisition["acquisition_id"]
        assert follow_up_observation.get("raw") is not None
        follow_up_lease = self.model.snapshot_llm_model_leases()[0]
        self.assert_sibling_held()
        assert id(follow_up_lease.client) == self.root_identity
        assert follow_up_lease.key == self.sibling_lease.key
        assert follow_up_lease.generation == self.root_generation
        assert self.pool_invalidate_count == 0
        assert self.pool_close_count == 0
        assert self.root_close_started == 0
        self.follow_up_lease = follow_up_lease
        return result
    def release_sibling_and_follow_up(self):
        """Release, join, and verify the exact sibling worker."""
        self.server.lifecycle_capture.request_handle(3).release_delay()
        self._sibling_thread.join(timeout=5)
        assert not self._sibling_thread.is_alive()
        if self.phase == "first_item":
            self.join_attempt_workers(ordinals={2, 3, 4})
        else:
            self.join_attempt_workers()
        if self._sibling_error:
            raise self._sibling_error[0]
        assert self._sibling_result == [SIBLING]
        state = self.state()
        bodies = [record["body"] for record in state["request_bodies"]]
        assert len(bodies) == 4
        assert bodies[0] == bodies[1]
        assert self.adapter_attempts[2]["params"] == bodies[2]
        assert self.adapter_attempts[3]["params"] == bodies[3]
        assert bodies[2]["messages"][-1] == {"role": "user", "content": "sibling request"}
        assert bodies[3]["messages"][-1] == {"role": "user", "content": "follow up"}
        assert bodies[2]["model"] == bodies[3]["model"] == bodies[0]["model"]
        assert self.sent == [FRESH_SECOND, "FOLLOW_UP"], self.sent
        assert all(STALE_OLD not in str(value) for value in self.usage)
        assert all(STALE_OLD not in str(value) for value in self.events)
        self.assert_post_settlement_root_close()
        return self.release_old()
