"""Concrete resource custody for the U5 exhaustion scenario."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from pytest import MonkeyPatch
from tests.bdd.llm_first_byte_deadline_harness import ScenarioPatchRecovery
from tests.mock.llm_mock_server import create_server, MockServerConfig
from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
from tests.bdd.llm_first_byte_warning_observation import WarningObservation
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_pool.openai_client_pool import OpenAIClientConfig, OpenAIClientPool
from topsailai.ai_base.llm_pool.provider_registry import (
    LLMProviderBackend, LLMProviderRegistry, default_provider_registry,
)


class NotifyingObservation(WarningObservation):
    """Publish exact observer evidence after releasing the observer lock."""

    def __init__(self, emit: Callable[[dict[str, Any]], None] | None = None,
                 publish_failure: Callable[[BaseException], None] | None = None):
        """Initialize explicit event and failure sinks."""
        super().__init__()
        self.emit = emit
        self.publish_failure = publish_failure

    def _append(self, kind, **values):
        """Capture one append and return no synthetic event value."""
        event = None
        error = None
        with self._lock:
            before = len(self.events)
            try:
                super()._append(kind, **values)
                candidates = self.events[before:]
                if len(candidates) != 1:
                    raise AssertionError(f"ambiguous observer publication: {kind}")
                event = dict(candidates[0])
                for key in ("owner", "response", "raw", "stream"):
                    if key in values and event.get(key) is not values[key]:
                        raise AssertionError(f"conflicting observer identity: {key}")
            except BaseException as caught:
                error = caught
        if error is not None:
            if self.publish_failure is not None:
                self.publish_failure(error)
            if self.emit is not None:
                try:
                    self.emit({"kind": "observer_error", "error": error, **values})
                except BaseException as emit_error:
                    if self.publish_failure is not None:
                        self.publish_failure(emit_error)
            return None
        if self.emit is not None:
            try:
                self.emit(event)
            except BaseException as emit_error:
                if self.publish_failure is not None:
                    self.publish_failure(emit_error)
        return None


@dataclass
class ServerThread:
    """Keep the socket reachable before its serving thread exists."""

    server: Any
    thread: Any = None

    @property
    def base_url(self):
        """Return the loopback origin."""
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"


class ScenarioResources:
    """Own resources, patches, spawning scopes and exact worker joins."""

    def __init__(self, state, limits, legacy_limits=None):
        """Allocate no external resources; accept the old unit-test seam."""
        self.state = state if isinstance(state, RunState) else RunState()
        self.condition = self.state.condition
        self.publish_failure = self.state.publish_failure
        if legacy_limits is not None:
            self.publish_failure = limits
            limits = legacy_limits
        self.limits = limits
        self.entries = {}
        self.workers = {}
        self.handles = {}
        self.scopes = {}
        self.patches = []
        self.recovery_armed = False
        self.restoration_complete = False
        self.prepared = False
        self.recovery_gate = ScenarioPatchRecovery(owner_patch=self, settle=self._restoration_ready)

    def __getattr__(self, name):
        """Expose resource views without duplicate ownership fields."""
        entries = self.__dict__.get("entries", {})
        if name in entries:
            return entries[name]["value"]
        raise AttributeError(name)

    def retain(self, name, value):
        """Retain an acquired object before the next fallible operation."""
        self.entries[name] = {"value": value, "closed": False}
        return value

    def prepare_observation(self, model, emit, publish_failure):
        """Retain observation custody before fallible start or model attachment."""
        observation = self.retain("observation", NotifyingObservation(emit, publish_failure))
        observation.start()
        observation.attach_model(model)
        return observation

    def patch(self, target, name, replacement):
        """Journal exact local state before mutation, including inherited absence."""
        namespace = vars(target)
        entry = [target, name, name in namespace, namespace.get(name), False]
        self.patches.append(entry)
        setattr(target, name, replacement)

    def _server(self, name, config):
        """Retain a socket before thread construction and startup."""
        server = self.retain(name, ServerThread(create_server(config)))
        self._install_lifecycle(name, server)
        server.thread = threading.Thread(target=server.server.serve_forever, daemon=True)
        self.register_worker(server.thread, "listener", None)
        self.start_worker(server.thread)
        return server

    def prepare(self, phase, install_observers):
        """Prepare under pre-existing custody; failure leaves all acquired entries."""
        if self.prepared:
            raise AssertionError("prepare is single-use")
        self.prepared = True
        delay = (1500.0,) * 18
        config = MockServerConfig(
            port=0, request_body_capacity=19, lifecycle_capacity=19,
            stream_response_chunks=tuple((f"STALE_{i}",) for i in range(18)),
            response_header_delays=delay if phase == "headers" else (0.0,) * 18,
            first_chunk_delays=delay if phase == "first_item" else (0.0,) * 18,
        )
        self.retain("environment", MonkeyPatch())
        primary = self._server("primary", config)
        values = {
            "OPENAI_API_BASE": primary.base_url, "OPENAI_BASE_URL": primary.base_url,
            "OPENAI_API_KEY": "u5-primary-key", "OPENAI_MODEL": "u5-exhaustion-model",
            "LLM_RESPONSE_STREAM": "1", "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "1.0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE": "1",
            "TOPSAILAI_INTERACTIVE_MODE": "0", "TOPSAILAI_EVENTS_ENABLED": "0",
            "TOPSAILAI_PRINT_TOOL_STAT": "0",
        }
        for key, value in values.items():
            self.environment.setenv(key, value)
        self.retain("pool", OpenAIClientPool())
        self.retain("registry", build_registry(self.pool))
        self.prepare_control()
        self.retain("model", LLMModel(provider_registry=self.registry))
        install_observers(self.model, self)
        return self

    def _install_lifecycle(self, domain, server):
        """Retain the exact delegated handle outside the outer Condition."""
        capture = server.server.lifecycle_capture
        original = capture.start

        def start(*args, **kwargs):
            """Return the same handle even if semantic observation fails."""
            handle = original(*args, **kwargs)
            self.state.safe(lambda: self.retain_handle(domain, args[0], handle))
            return handle

        self.patch(capture, "start", start)

    def retain_handle(self, domain, ordinal, handle):
        """Retain every accepted handle, including unexpected request nineteen."""
        with self.condition:
            key = (domain, ordinal)
            previous = self.handles.get(key)
            if previous is not None and previous["handle"] is not handle:
                raise AssertionError("conflicting handle")
            if previous is None:
                self.handles[key] = {"handle": handle, "released": None, "joined": None}
            armed = self.recovery_armed
            self.condition.notify_all()
        if armed:
            self.release_handle(domain, ordinal)
        return armed

    def release_handle(self, domain, ordinal):
        """Release once outside the Condition and retain the actual return time."""
        entry = self.handles[(domain, ordinal)]
        if entry["released"] is None:
            entry["handle"].release_delay()
            entry["released"] = time.monotonic()
        return entry["released"]

    def arm_recovery(self):
        """Atomically prevent new starts and enable late-handle release."""
        with self.condition:
            self.recovery_armed = True
            self.condition.notify_all()
            return [entry["handle"] for entry in self.handles.values()]

    def register_owner(self, owner):
        """Retain unknown owners too, before provenance observation."""
        self.retain(f"owner:{id(owner)}", owner)

    def note_spawn_scope(self, owner, role, token, phase):
        """Track actual entered/exited scheduling calls, not thread-list stability."""
        with self.condition:
            key = (id(owner), role, token)
            if phase == "ENTERED":
                self.scopes[key] = {"owner": owner, "role": role, "closed": False,
                                    "starter": threading.current_thread(), "token": token}
            else:
                self.scopes[key]["closed"] = True
            self.condition.notify_all()

    def register_worker(self, thread, role="worker", deadline=None, owner=None, starter=None):
        """Register before startup; repeated identical binding preserves evidence."""
        with self.condition:
            existing = self.workers.get(id(thread))
            if existing is not None:
                if existing["thread"] is not thread or existing["role"] != role or existing["owner"] is not owner:
                    raise AssertionError("conflicting worker binding")
                if deadline is not None and existing["deadline"] not in (None, deadline):
                    raise AssertionError("conflicting worker deadline")
                if existing["deadline"] is None:
                    existing["deadline"] = deadline
                return existing
            if role == "settler" and self.state.no_more_settlers:
                raise AssertionError("settler admission is sealed")
            entry = {"thread": thread, "role": role, "owner": owner, "deadline": deadline,
                     "starter": starter, "support_owned": starter is None,
                     "start": "REGISTERED", "joined": None}
            self.workers[id(thread)] = entry
            self.condition.notify_all()
            return entry

    def start_worker(self, thread):
        """Retain STARTING custody across an interrupted start call."""
        entry = self.workers[id(thread)]
        with self.condition:
            if self.recovery_armed or entry["start"] != "REGISTERED":
                raise AssertionError("worker cannot start")
            entry.update(start="STARTING", starter=threading.current_thread())
        try:
            thread.start()
        except BaseException as error:
            entry.update(start="START_RAISED", start_error=error)
            self.publish_failure(error)
            raise
        else:
            entry["start"] = "START_RETURNED"
        finally:
            with self.condition:
                self.condition.notify_all()

    def join_worker(self, thread, deadline, recovery=False, slice_only=False):
        """Return retained proof first; normal joins never renew a deadline."""
        entry = self.workers[id(thread)]
        if entry["joined"] is not None:
            return entry["joined"]
        if thread is threading.current_thread():
            raise AssertionError("self join is forbidden")
        effective = deadline if recovery else min(deadline, entry["deadline"] or deadline)
        while True:
            if not recovery:
                self.state.raise_failure()
            if time.monotonic() > effective:
                raise AssertionError(f"worker deadline exceeded: {entry['role']}")
            if thread.ident is None:
                if recovery and self.recovery_armed and entry["start"] == "REGISTERED" and (
                        entry["support_owned"] or self._producer_closed(entry)):
                    entry["joined"] = {"thread": thread, "never_started": True, "at": time.monotonic()}
                    return entry["joined"]
                if entry["start"] == "START_RAISED" and not thread.is_alive():
                    raise AssertionError("failed startup lacks positive no-start proof")
            else:
                thread.join(max(0.0, min(0.05, effective - time.monotonic())))
                now = time.monotonic()
                if not recovery:
                    self.state.raise_failure()
                if not thread.is_alive() and now <= effective:
                    entry["joined"] = {"thread": thread, "at": now, "never_started": False}
                    return entry["joined"]
            if slice_only:
                return None
            with self.condition:
                self.condition.wait(max(0.0, min(0.05, effective - time.monotonic())))

    def discover_owner_workers(self, owner, deadline):
        """Discover exact workers after their possible producers have progressed."""
        result = []
        for role in ("create", "fetch", "cleanup"):
            worker = getattr(owner, f"{role}_thread", None)
            if worker is not None:
                existing = self.workers.get(id(worker))
                retained = existing["deadline"] if existing is not None else deadline
                result.append(self.register_worker(worker, role, retained, owner, starter=(owner, role)))
        return result

    def _producer_closed(self, entry):
        """Prove external start authority ended, never infer it from missing identity."""
        owner = entry["owner"]
        if owner is None:
            return False
        scopes = [item for item in self.scopes.values() if item["owner"] is owner]
        if not scopes or not all(item["closed"] for item in scopes):
            return False
        rows = [row for row in self.state.records.values() if row.owner is owner]
        if rows and not rows[0].get("invocation_exited"):
            return False
        if entry["role"] == "cleanup":
            producers = [getattr(owner, name + "_thread", None) for name in ("create", "fetch")]
            if any(worker is not None and (id(worker) not in self.workers or
                   self.workers[id(worker)]["joined"] is None) for worker in producers):
                return False
        return True

    def attempt_quiescent(self, owner, deadline):
        """Close invocation/scheduling authority before final late-cleanup discovery."""
        row = self.state.row_for_owner(owner)
        self.state.wait_until(lambda: row.get("invocation_exited") is True, deadline)
        self.state.wait_until(lambda: all(item["closed"] for item in self.scopes.values()
                                         if item["owner"] is owner), deadline)
        entries = self.discover_owner_workers(owner, deadline)
        for entry in entries:
            if entry["role"] != "cleanup":
                self.join_worker(entry["thread"], deadline)
        entries = self.discover_owner_workers(owner, deadline)
        for entry in entries:
            self.join_worker(entry["thread"], deadline)
        scopes = [dict(item) for item in self.scopes.values() if item["owner"] is owner]
        if not scopes or not all(item["closed"] for item in scopes):
            raise AssertionError("unresolved owner scheduling authority")
        if not owner.close_finished_event.is_set():
            raise AssertionError("close producer is unresolved")
        return {"owner": owner, "workers": [entry["joined"] for entry in entries],
                "scopes": scopes, "invocation_exited": True, "at": time.monotonic()}

    def join_handler(self, handle, deadline, recovery=False):
        """Require actual handler exit and connection closure separately."""
        while not handle.wait_for_thread_exit(max(0.0, min(0.05, deadline - time.monotonic()))):
            if not recovery:
                self.state.raise_failure()
            if time.monotonic() >= deadline:
                raise AssertionError("handler deadline exceeded")
        if time.monotonic() > deadline or not handle.record["connection_closed"]:
            raise AssertionError("handler connection did not settle")
        proof = {"handle": handle, "thread_exited": True, "connection_closed": True, "at": time.monotonic()}
        for entry in self.handles.values():
            if entry["handle"] is handle:
                entry["joined"] = proof
        return proof

    def prepare_control(self):
        """Construct an unrelated lease in the same private pool without HTTP."""
        control = self._server("control", MockServerConfig(
            port=0, stream_response_chunks=(("CONTROL",),), first_chunk_delays=(1500.0,),
            request_body_capacity=2, lifecycle_capacity=2,
        ))
        config = OpenAIClientConfig(api_key="u5-control-key", base_url=control.base_url,
                                    model="u5-control-model", client_options=(("max_retries", 0),))
        self.retain("control_lease", self.pool.acquire(config))
        self.retain("control_data", {"content": [], "error": None, "stream": None, "held": None})
        self._prepare_control_worker()

    def _prepare_control_worker(self):
        """Register the unstarted control consumer during setup without HTTP."""
        data = self.control_data

        def consume():
            """Capture stream before iteration and retain the original consumer error."""
            try:
                stream = self.control_lease.client.chat.completions.create(
                    model="u5-control-model", messages=[{"role": "user", "content": "u5 control"}], stream=True)
                with self.condition:
                    data["stream"] = stream
                    self.condition.notify_all()
                for item in stream:
                    for choice in item.choices:
                        content = getattr(choice.delta, "content", None)
                        if content:
                            data["content"].append(content)
            except BaseException as error:
                data["error"] = error
                self.publish_failure(error)
            finally:
                with self.condition:
                    self.condition.notify_all()

        worker = self.retain("control_thread", threading.Thread(target=consume, daemon=True))
        self.register_worker(worker, "control", None)

    def start_control(self, deadline):
        """Hold preconstructed control before release eighteen under L18."""
        data = self.control_data
        data["start_before"] = time.monotonic()
        self.start_worker(self.control_thread)
        data["start_returned"] = time.monotonic()
        capture = self.control.server.lifecycle_capture
        self.wait_external(lambda seconds: capture.wait_for_request(1, seconds), deadline)
        handle = self.handles[("control", 1)]["handle"]
        self.wait_external(lambda seconds: handle.wait_for_phase("first_item", seconds), deadline)
        self.state.wait_until(lambda: data["stream"] is not None, deadline)
        primary_client = self.model.chat_model._client
        if self.control_lease.client is primary_client:
            raise AssertionError("control reused primary client")
        data["held"] = (handle, self.control_lease.client, data["stream"])
        return dict(self.assert_control_held(), start_before=data["start_before"],
                    start_returned=data["start_returned"], pool=self.pool,
                    primary_client=primary_client, primary_key=primary_client.api_key,
                    control_key=self.control_lease.client.api_key)

    def wait_external(self, operation, deadline):
        """Slice external waits without holding the state Condition."""
        while True:
            self.state.raise_failure()
            if time.monotonic() >= deadline:
                raise AssertionError("external wait exceeded deadline")
            ready = operation(max(0.0, min(0.05, deadline - time.monotonic())))
            self.state.raise_failure()
            if time.monotonic() > deadline:
                raise AssertionError("external wait returned late")
            if ready:
                return

    def assert_control_held(self):
        """Require the identical held stream and client to remain usable."""
        data = self.control_data
        handle, client, stream = data["held"]
        if self.handles[("control", 1)]["released"] is not None:
            raise AssertionError("control was released early")
        if client.is_closed() or not self.control_thread.is_alive() or data["error"] is not None:
            raise AssertionError("control did not survive")
        if stream is not data["stream"] or client is not self.control_lease.client:
            raise AssertionError("control identity changed")
        return {"handle": handle, "client": client, "stream": stream, "at": time.monotonic()}

    def close_primary(self, deadline):
        """Close only the primary model while keeping the control lease alive."""
        self.model.close()
        self.entries["model"]["closed"] = True
        if time.monotonic() > deadline:
            raise AssertionError("primary close exceeded deadline")
        return {"at": time.monotonic()}

    def finish_control(self, deadline, require_content=True):
        """Use one release-derived budget for stream, consumer, handler and lease."""
        released = self.release_handle("control", 1)
        effective = min(deadline, released + 30)
        joined = self.join_worker(self.control_thread, effective, recovery=not require_content)
        data = self.control_data
        if data["stream"] is not None:
            data["stream"].close()
        handler = self.join_handler(self.handles[("control", 1)]["handle"], effective, not require_content)
        if require_content and (data["error"] is not None or "".join(data["content"]) != "CONTROL"):
            raise AssertionError("control content is incomplete")
        self.pool.release(self.control_lease)
        self.entries["control_lease"]["closed"] = True
        if require_content:
            self.state.raise_failure()
        if time.monotonic() > effective:
            raise AssertionError("control lease release exceeded deadline")
        return {"released": released, "deadline": effective, "joined": joined, "handler": handler,
                "content": "".join(data["content"]), "lease_released": True}

    def global_quiescent(self, deadline):
        """Require final orchestration joins, separately from attempt quiescence."""
        for name, entry in list(self.entries.items()):
            if name.startswith("owner:"):
                owner = entry["value"]
                self.discover_owner_workers(owner, deadline)
                if not owner.close_finished_event.is_set():
                    raise AssertionError("owner close authority remains open")
        if not self.state.no_more_settlers:
            raise AssertionError("settler admission remains open")
        for entry in list(self.workers.values()):
            if entry["role"] != "listener" and entry["joined"] is None:
                raise AssertionError("global worker remains unsettled")
        if any(entry["joined"] is None for entry in self.handles.values()):
            raise AssertionError("global handler remains unsettled")
        if any(not row.get("invocation_exited") for row in self.state.records.values()):
            raise AssertionError("invocation spawning authority remains open")
        if self.state.retention_failed:
            raise AssertionError("diagnostic retention debt remains")
        if any(entry["start"] == "STARTING" for entry in self.workers.values()):
            raise AssertionError("support start remains in flight")
        if any(not item["closed"] for item in self.scopes.values()):
            raise AssertionError("global spawning authority remains open")
        if time.monotonic() > deadline:
            raise AssertionError("global quiescence exceeded deadline")
        return {"at": time.monotonic(), "workers": tuple(self.workers)}

    def _close_concrete(self, deadline):
        """Continue independent cleanup while retaining original diagnostics."""
        def cleanup_order(item):
            """Keep model/pool cleanup inside the observation and lifecycle patch lifetime."""
            name, entry = item
            if name.startswith("owner:"):
                return 0
            if name in {"model", "control_lease"}:
                return 1
            if name == "pool":
                return 2
            return 3

        for name, entry in sorted(self.entries.items(), key=cleanup_order):
            if entry["closed"] or name in {"environment", "observation", "registry", "control_data"}:
                continue
            try:
                value = entry["value"]
                if isinstance(value, ServerThread):
                    if value.thread is not None and value.thread.ident is not None:
                        value.server.shutdown()
                    value.server.server_close()
                    if value.thread is not None:
                        self.join_worker(value.thread, deadline, recovery=True)
                elif name == "pool":
                    value.close_all()
                elif name == "control_lease":
                    self.pool.release(value)
                elif name.startswith("owner:"):
                    value.dispose(background=True)
                    for worker in self.discover_owner_workers(value, deadline):
                        self.join_worker(worker["thread"], deadline, recovery=True)
                    if not value.close_finished_event.is_set():
                        raise AssertionError("owner close remains unresolved")
                elif name == "model":
                    value.close()
                entry["closed"] = True
            except BaseException as error:
                self.state.publish_failure(error, ("cleanup", name))
        unresolved = [name for name, entry in self.entries.items()
                      if not entry["closed"] and name not in {"environment", "observation", "registry", "control_data"}]
        if unresolved:
            raise AssertionError(f"concrete cleanup unresolved: {unresolved}")

    def _restoration_ready(self):
        """Gate restoration on all authority, concrete custody and diagnostic debt."""
        self.global_quiescent(self.cleanup_deadline)
        ignored = {"environment", "observation", "registry", "control_data"}
        if any(not entry["closed"] for name, entry in self.entries.items() if name not in ignored):
            raise AssertionError("concrete restoration debt remains")

    def stop(self):
        """Expose the stable recovery gate patch-owner protocol."""
        self._restore()

    def _restore(self):
        """Restore only after concrete cleanup; retain per-patch retry progress."""
        if "observation" in self.entries:
            self.observation.stop()
        for entry in reversed(self.patches):
            target, name, existed, original, restored = entry
            if restored:
                continue
            if existed:
                setattr(target, name, original)
            else:
                delattr(target, name)
            entry[4] = True
        if "environment" in self.entries:
            self.environment.undo()
        self.restoration_complete = True

    def close_normal(self, deadline):
        """Restore after verified normal quiescence and concrete cleanup."""
        self.cleanup_deadline = deadline
        proof = self.global_quiescent(deadline)
        self._close_concrete(deadline)
        self.state.raise_failure()
        self.recovery_gate.recover()
        return {"quiescence": proof, "restoration_complete": self.restoration_complete}

    def recover(self, deadline):
        """Release first, reconcile dynamic workers, and never restore unresolved custody."""
        self.cleanup_deadline = deadline
        self.arm_recovery()
        self.state.seal_settlers()
        for domain, ordinal in list(self.handles):
            try:
                self.release_handle(domain, ordinal)
            except BaseException as error:
                self.state.publish_failure(error)
        for name, entry in list(self.entries.items()):
            if not name.startswith("owner:"):
                continue
            try:
                owner = entry["value"]
                token = object()
                self.note_spawn_scope(owner, "recovery_dispose", token, "ENTERED")
                try:
                    owner.dispose(background=True)
                finally:
                    self.note_spawn_scope(owner, "recovery_dispose", token, "EXITED")
            except BaseException as error:
                self.state.publish_failure(error, ("recovery_dispose", name))
        if "control_data" in self.entries and self.control_data["stream"] is not None:
            try:
                self.control_data["stream"].close()
            except BaseException as error:
                self.state.publish_failure(error)
        while True:
            for name, entry in list(self.entries.items()):
                if name.startswith("owner:"):
                    self.discover_owner_workers(entry["value"], deadline)
            pending = [entry for entry in self.workers.values()
                       if entry["role"] != "listener" and entry["joined"] is None]
            if not pending:
                break
            for entry in pending:
                try:
                    self.join_worker(entry["thread"], deadline, recovery=True, slice_only=True)
                except BaseException as error:
                    self.state.publish_failure(error, ("recovery_join", entry["role"]))
            if time.monotonic() >= deadline:
                break
        for entry in list(self.handles.values()):
            if entry["joined"] is not None:
                continue
            try:
                self.join_handler(entry["handle"], deadline, recovery=True)
            except BaseException as error:
                self.state.publish_failure(error)
        try:
            self._close_concrete(deadline)
            unresolved = [entry for entry in self.workers.values() if entry["joined"] is None]
            if unresolved or any(entry["joined"] is None for entry in self.handles.values()):
                raise AssertionError("recovery retains unresolved workers/handlers")
            self.recovery_gate.recover()
        except BaseException as error:
            self.state.publish_failure(error)
        self.state.raise_failure()

    def settle(self, deadline):
        """Use the same recovery authority for the compatibility entry point."""
        return self.recover(deadline)


def build_registry(pool) -> LLMProviderRegistry:
    """Build a private provider registry while disabling SDK retries."""
    backend = default_provider_registry.resolve("openai")
    original_factory = backend.config_factory

    def config_factory(**kwargs):
        """Delegate production configuration and add only max_retries=0."""
        config = original_factory(**kwargs)
        options = dict(config.client_options)
        options["max_retries"] = 0
        return type(config)(
            api_key=config.api_key, base_url=config.base_url,
            organization=config.organization, project=config.project,
            client_type=config.client_type, client_options=tuple(options.items()),
            model=config.model,
        )

    registry = LLMProviderRegistry()
    registry.register(LLMProviderBackend(
        name="openai", config_factory=config_factory,
        acquire=pool.acquire, invalidate=pool.invalidate,
        get_chat_model=backend.get_chat_model,
        response_adapter=backend.response_adapter,
        model_name_resolver=backend.model_name_resolver,
        api_base_resolver=backend.api_base_resolver,
        api_key_resolver=backend.api_key_resolver,
    ))
    return registry
