"""Real-loopback orchestration for first-byte retry exhaustion acceptance."""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from topsailai.ai_base.exception import LLMRetryExhaustedError
from topsailai.ai_base.llm_control.exception import LLMProviderTimeoutError
from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy
from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources
from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

ATTEMPTS = 18
FIRST_BYTE_TIMEOUT = 1.0
RELEASE_LIMIT = 3.0
RAW_LIMIT = 4.0
SETTLEMENT_LIMIT = 30.0
ADMISSION_LIMIT = 1150.0


class ExhaustionScenario:
    """Coordinate admission, timely settlement and held-control isolation."""

    def __init__(self, phase, monkeypatch=None):
        """Allocate only resource-free state before the fixture finalizer exists."""
        if phase not in {"headers", "first_item"}:
            raise ValueError(phase)
        self.phase = phase
        self.state = RunState()
        self.resources = ScenarioResources(self.state, {
            "release": RELEASE_LIMIT, "raw": RAW_LIMIT, "settlement": SETTLEMENT_LIMIT,
        })
        self.result = None
        self.prompt_calls = []

    def prepare(self):
        """Acquire concrete resources only after external cleanup custody is installed."""
        self.resources.prepare(self.phase, self.state.install)

    @property
    def records(self):
        """Expose the same authoritative attempt rows."""
        return self.state.records

    @property
    def settlements(self):
        """Expose only supervisor-completed settlements."""
        return self.state.settlements

    @property
    def primary(self):
        """Expose the support-owned primary listener."""
        return self.resources.primary

    @property
    def chat_error(self):
        """Expose terminal evidence without a second mutable error field."""
        return self.state.terminal_error

    @property
    def releases(self):
        """Derive release evidence rather than maintaining a duplicate log."""
        return [{"ordinal": row.ordinal, "adapter_entry": row.adapter_entry,
                 "released_at": row.release_returned}
                for row in self.records.values() if row.release_returned is not None]

    def _wait_prerequisites(self, ordinal, deadline):
        """Require actual adapter entry, held acceptance, timeout and abandonment."""
        self.state.wait_until(lambda: ordinal in self.records and self.records[ordinal].adapter_entry is not None, deadline)
        row = self.records[ordinal]
        limit = row["release_deadline"]
        self.state.wait_until(lambda: ("primary", ordinal) in self.resources.handles, limit)
        handle = self.resources.handles[("primary", ordinal)]["handle"]
        row["handle"] = handle
        self.resources.wait_external(lambda seconds: handle.wait_for_phase(self.phase, seconds), limit)
        self.state.wait_until(lambda: row.get("timeout") is True and row.get("abandoned") is True
                              and row.owner is not None and row.invocation.owner is row.owner, limit)
        if not isinstance(row.get("error"), LLMProviderTimeoutError):
            raise AssertionError("release lacks exact timeout")
        if not row.get("configs") or row.get("ticket") is not row.invocation.expected_ticket:
            raise AssertionError("release lacks config/start provenance")
        if row.get("budget") is None:
            raise AssertionError("release lacks shared budget")
        row.transitions.append("release_ready")
        return row

    def _release_once(self, row):
        """Release only after abandonment, preserving Li and one release-derived Si."""
        if row.release_returned is not None:
            raise AssertionError("attempt released twice")
        if row.get("abandoned") is not True:
            raise AssertionError("release before abandonment")
        released = self.resources.release_handle("primary", row.ordinal)
        row.release_returned = released
        row.settlement_deadline = min(self.state.deadline, released + SETTLEMENT_LIMIT)
        if released > row["release_deadline"]:
            raise AssertionError("attempt released late")
        with self.state.condition:
            row.transitions.append("release")
            self.state.condition.notify_all()
        return released

    def _settle(self, ordinal, row, released):
        """Collect a candidate under Si; only the independent supervisor may complete it."""
        try:
            self.state.wait_raw(ordinal, min(row["raw_deadline"], row.settlement_deadline))
            quiescence = self.resources.attempt_quiescent(row.owner, row.settlement_deadline)
            handler = self.resources.join_handler(row["handle"], row.settlement_deadline)
            snapshots = self.state.snapshot_attempt(ordinal)
            row.update(phase=self.phase, terminal_at=self.state.terminal_at)
            snapshots.update(quiescence=quiescence, handler=handler)
            candidate = validate_settlement(row, snapshots, now=time.monotonic())
            self.state.publish_candidate(ordinal, candidate)
        except BaseException as error:
            self.state.publish_failure(error)
        finally:
            with self.state.condition:
                row["settler_target_done"] = True
                self.state.condition.notify_all()

    def _finalize_settler(self, ordinal, joined):
        """Publish COMPLETED only after exact settler exit/join before its original Si."""
        return self.state.complete_settlement(ordinal, joined, now=time.monotonic())

    def _service_settlers(self):
        """Continuously service candidates during real backoff with acyclic termination."""
        try:
            while True:
                self.state.raise_failure()
                with self.state.condition:
                    pending = [row for row in self.records.values()
                               if row.get("settlement_worker") is not None and row.completed_bundle is None]
                    sealed = self.state.no_more_settlers
                if sealed and not pending:
                    return
                pending.sort(key=lambda row: row.settlement_deadline)
                actionable = False
                for row in pending:
                    self.state.raise_failure()
                    if time.monotonic() > row.settlement_deadline:
                        raise AssertionError(f"settler {row.ordinal} exceeded Si")
                    if row.get("candidate") is None and not row.get("settler_target_done"):
                        continue
                    actionable = True
                    joined = self.resources.join_worker(row["settlement_worker"], row.settlement_deadline, slice_only=True)
                    if joined is not None:
                        self._finalize_settler(row.ordinal, joined)
                if actionable:
                    continue
                with self.state.condition:
                    # Recheck under the notification lock to avoid a lost candidate wakeup.
                    ready = any(row.get("candidate") is not None or row.get("settler_target_done") for row in pending)
                    if not ready and not (self.state.no_more_settlers and not pending) and not any(
                            row.get("settlement_worker") is not None and row.completed_bundle is None
                            and row not in pending for row in self.records.values()
                        ):
                        nearest = min([row.settlement_deadline for row in pending] + [self.state.deadline])
                        self.state.condition.wait(max(0.0, nearest - time.monotonic()))
        except BaseException as error:
            self.state.publish_failure(error)
        finally:
            with self.state.condition:
                self.state.settlement_supervisor_done = True
                self.state.condition.notify_all()

    def _coordinate(self):
        """Hold control before release eighteen, then prove survival and no request nineteen."""
        try:
            for ordinal in range(1, ATTEMPTS + 1):
                row = self._wait_prerequisites(ordinal, self.state.deadline)
                if ordinal == ATTEMPTS:
                    self.state.wait_until(lambda: self.state.terminal_at is not None
                                          and all(i in self.settlements for i in range(1, ATTEMPTS)),
                                          row["release_deadline"])
                    error = self.chat_error
                    if not isinstance(error, LLMRetryExhaustedError) or error.last_error is not row.get("error"):
                        raise AssertionError("terminal exhaustion identity mismatch")
                    row["control_before_release"] = self.resources.start_control(row["release_deadline"])
                released = self._release_once(row)
                worker = threading.Thread(target=self._settle, args=(ordinal, row, released), daemon=True)
                self.resources.register_worker(worker, "settler", row.settlement_deadline, row.owner)
                with self.state.condition:
                    row["settlement_worker"] = worker
                    self.state.condition.notify_all()
                self.resources.start_worker(worker)
            self.state.seal_settlers()
            self.state.wait_until(lambda: ATTEMPTS in self.settlements, row.settlement_deadline)
            row["primary_close"] = self.resources.close_primary(min(self.state.deadline, row.settlement_deadline))
            row["control_survival"] = self.resources.assert_control_held()
            row["control_settlement"] = self.resources.finish_control(self.state.deadline)
            if self.state.deadline - time.monotonic() < 5:
                raise AssertionError("insufficient full no19 observation budget")
            started = time.monotonic()
            while time.monotonic() < started + 5:
                self.state.raise_failure()
                now = time.monotonic()
                if now >= started + 5 and now <= self.state.deadline:
                    break
                remaining = min(started + 5, self.state.deadline) - now
                if remaining <= 0:
                    raise AssertionError("no19 observation exceeded deadline")
                if self.primary.server.lifecycle_capture.wait_for_request(ATTEMPTS + 1, timeout=min(0.05, remaining)):
                    raise AssertionError("nineteenth request observed")
                self.state.raise_failure()
                if time.monotonic() > self.state.deadline:
                    raise AssertionError("no19 observation returned late")
            row["no19"] = {"start": started, "end": time.monotonic()}
            self.state.raise_failure()
        except BaseException as error:
            self.state.publish_failure(error)
        finally:
            self.state.seal_settlers()
            with self.state.condition:
                self.state.coordinator_done = True
                self.state.condition.notify_all()

    def _chat_worker(self, messages):
        """Keep genuine retry exhaustion separate from orchestration failures."""
        def reject_prompt(prompt):
            """Observe and reject any unexpected noninteractive retry prompt."""
            self.prompt_calls.append(prompt)
            raise AssertionError("unexpected retry prompt")
        try:
            result = self.resources.model.chat(messages, for_stream=True,
                retry_interaction_policy=LLMRetryInteractionPolicy(
                    interactive_enabled=False, input_func=reject_prompt))
            self.state.publish_failure(AssertionError(f"unexpected chat return: {result!r}"))
        except LLMRetryExhaustedError as error:
            self.state.publish_terminal(error)
        except BaseException as error:
            self.state.publish_failure(error)

    def run(self):
        """Join orchestration in the caller before normal cleanup and result publication."""
        self.state.deadline = time.monotonic() + ADMISSION_LIMIT
        messages = [{"role": "user", "content": "u5 exhaustion"}]
        supervisor = threading.Thread(target=self._service_settlers, daemon=True)
        chat = threading.Thread(target=self._chat_worker, args=(messages,), daemon=True)
        coordinator = threading.Thread(target=self._coordinate, daemon=True)
        for worker, role in ((supervisor, "supervisor"), (chat, "chat"), (coordinator, "coordinator")):
            self.resources.register_worker(worker, role, self.state.deadline)
            self.resources.start_worker(worker)
        self.state.wait_until(lambda: self.state.coordinator_done, self.state.deadline)
        for worker in (coordinator, chat, supervisor):
            self.resources.join_worker(worker, self.state.deadline)
        error = self.chat_error
        assert isinstance(error, LLMRetryExhaustedError)
        assert error.attempts == ATTEMPTS
        assert error.manual_cycle_count == 0
        assert error.retry_reason == "timeout"
        assert isinstance(error.last_error, LLMProviderTimeoutError)
        assert error.__cause__ is error.last_error
        assert set(self.records) == set(range(1, 19))
        assert set(self.settlements) == set(range(1, 19))
        captured = self.primary.server.request_body_capture.state()
        bodies = [item["body"] for item in captured["request_bodies"]]
        assert len(bodies) == ATTEMPTS
        assert len(self.releases) == ATTEMPTS
        model = self.resources.model
        expected_body = {
            "model": "u5-exhaustion-model", "messages": [{"role": "system", "content": ""}] + messages,
            "stream": True, "max_tokens": model.max_tokens, "temperature": model.temperature,
            "top_p": model.top_p, "frequency_penalty": model.frequency_penalty,
            "n": 1, "stop": None,
            "stream_options": {"include_usage": True},
        }
        assert all(body == expected_body for body in bodies)
        assert captured["dropped_request_body_count"] == 0
        assert self.primary.server.lifecycle_capture.state()["dropped_lifecycle_count"] == 0
        budgets = [row["budget"] for row in self.records.values()]
        gaps = [self.records[i + 1]["entered_at"] - self.records[i]["error_at"] for i in range(1, ATTEMPTS)]
        if len({id(budget) for budget in budgets}) != ATTEMPTS or any(
                gap < 5 * index for index, gap in enumerate(gaps, 1)):
            raise AssertionError("shared budgets or shortened real backoff")
        assert not self.prompt_calls
        for field in ("invocation", "owner", "ticket"):
            assert len({id(row[field]) for row in self.records.values()}) == ATTEMPTS
        cleanup = self.resources.close_normal(self.state.deadline)
        return {"bodies": bodies, "state": captured, "releases": self.releases,
                "error": error, "settlements": self.settlements, "cleanup": cleanup,
                "expected_body": expected_body, "final": self.records[18],
                "backoff_gaps": gaps, "budgets": budgets, "prompt_calls": tuple(self.prompt_calls),
                "rows": tuple(self.records.values()), "terminal_at": self.state.terminal_at}

    def close(self):
        """Retain unresolved custody for finalizer retry; do not restore on failure."""
        if self.resources.restoration_complete:
            return
        deadline = min(self.state.deadline or float("inf"), time.monotonic() + SETTLEMENT_LIMIT)
        self.resources.recover(deadline)


def validate_settlement(row, snapshots, *, now):
    """Validate physical close, provenance and exact identity before candidate publication."""
    _validate_transport_budget(row, snapshots)
    _validate_final_timing(row, snapshots, now=now)
    if now > row.settlement_deadline:
        raise AssertionError("candidate exceeded settlement deadline")
    raw_event = row.validate_raw(row["raw_deadline"])
    raw = raw_event["raw"]
    events = snapshots["events"]
    before = [item for item in events if item["kind"] == "stream_close_before"]
    after = [item for item in events if item["kind"] == "stream_close_after"]
    if len(before) != 1 or len(after) != 1:
        raise AssertionError("missing or duplicate close pair")
    for item in before + after:
        if item.get("raw") is not raw or item.get("stream") is not raw_event["response"]:
            raise AssertionError("close identity conflict")
    if before[0]["at"] > after[0]["at"]:
        raise AssertionError("close order conflict")
    if snapshots["close_finished"] is not True or snapshots["close_state"] != "SUCCEEDED":
        raise AssertionError("close did not complete successfully")
    if snapshots["disposal_error"] is not None:
        raise AssertionError("close retained a disposal error")
    if snapshots["close_error"] is not None and not (row.get("abandoned") is True and any(
            item["kind"] == "error" and item.get("error") is snapshots["close_error"] for item in events)):
        raise AssertionError("unattributed late error")
    physical = getattr(raw, "response", raw)
    if physical.is_closed is not True or snapshots["owner"] is not row.owner or snapshots["invocation"] is not row.invocation:
        raise AssertionError("raw/provenance identity conflict")
    if snapshots["primary_error"] is not row.get("error"):
        raise AssertionError("primary error identity conflict")
    mode = row.get("phase")
    if mode not in {"headers", "first_item"} or row.get("publication") is not (mode == "first_item"):
        raise AssertionError("missing actual publication result")
    if any(item["kind"] == "stream_close_uninstrumented" for item in events):
        raise AssertionError("uninstrumented close")
    if not row.get("configs") or any(value != (1.0, True) for value in row["configs"]):
        raise AssertionError("wrong actual timeout configuration")
    if row.get("ticket") is not row.invocation.expected_ticket or row.get("budget") is None:
        raise AssertionError("missing actual start/budget")
    transport = row.get("transport")
    if transport is None or transport["timeout"] != (5, 300) or transport["max_retries"] != 0:
        raise AssertionError("actual transport contract mismatch")
    if transport["body"] != row["params"]:
        raise AssertionError("SDK request parameters changed")
    if mode == "first_item" and row.get("first_item_budget") is not row["budget"]:
        raise AssertionError("first-item guard used a different absolute budget")
    callbacks = snapshots["callbacks"]
    expected = ["start", "finish", "finish"] if mode == "headers" else ["start", "pause", "resume", "pause", "finish"]
    if [item.get("operation") for item in callbacks] != expected or any(
            item.get("error") is not None or item.get("completed") is not True
            or item.get("initiator") is not row.owner or item.get("invocation") is not row.invocation
            or item.get("ticket") is not row.get("ticket")
            or item.get("source") not in {"owner", "invocation"} for item in callbacks):
        raise AssertionError("missing or failed callbacks")
    handler = snapshots["handler"]
    if handler["handle"] is not row.get("handle") or handler["thread_exited"] is not True or handler["connection_closed"] is not True:
        raise AssertionError("handler proof conflict")
    proof = snapshots["quiescence"]
    workers = [getattr(row.owner, role + "_thread", None) for role in ("create", "fetch", "cleanup")]
    if proof["owner"] is not row.owner or proof.get("invocation_exited") is not True or not proof.get("scopes") or any(
            not item["closed"] for item in proof["scopes"]) or any(
            worker is not None and not any(join.get("thread") is worker and join.get("at", float("inf")) <= row.settlement_deadline
                                           for join in proof["workers"]) for worker in workers):
        raise AssertionError("wrong scoped quiescence")
    if not row.get("abandoned_at") <= row.release_returned <= row["release_deadline"]:
        raise AssertionError("release preceded abandonment or exceeded deadline")
    if not row.adapter_entry <= raw_event["at"] <= before[0]["at"] <= after[0]["at"] <= now:
        raise AssertionError("raw/close timeline conflict")
    if row.ordinal == 18 and mode == "headers" and raw_event["at"] < row.get("terminal_at", float("inf")):
        raise AssertionError("final headers raw preceded terminal")
    if any(str(item.get("content", "")).startswith("STALE_") for item in events):
        raise AssertionError("stale primary content")
    return dict(snapshots, ordinal=row.ordinal, candidate_at=now, raw=raw)



def _validate_transport_budget(row, snapshots):
    """Reject unobserved transport phases, renewed budgets and unattributed starts."""
    transport = row["transport_normalized"]
    assert transport["units"] == "seconds"
    assert all((transport[key] is None and key in {"write", "pool"}) or (
        type(transport[key]) in (int, float) and math.isfinite(transport[key]) and transport[key] > 0)
        for key in ("connect", "read", "write", "pool"))
    assert row["http_request"].extensions["timeout"] == {
        key: transport[key] for key in ("connect", "read", "write", "pool")}
    phases = row["http_phases"]
    phase = "receive_response_headers" if row["phase"] == "headers" else "receive_response_body"
    anchors = [item for item in phases if item["name"].endswith(phase + ".started")]
    assert len(anchors) == 1
    anchor = anchors[0]["at"]
    assert row.adapter_entry <= anchor <= row.release_returned
    # Read timeout is a per-I/O bound, not an invented whole-request deadline.
    assert row.release_returned - anchor < transport["read"]
    assert row.raw_event["at"] - anchor < transport["read"]
    assert all(item["thread"] is row["http_thread"] for item in phases
               if "receive_response_headers" in item["name"])
    create = row["create_budget_facts"]
    assert create["timeout_seconds"] == 1.0 and create["raise_on_timeout"] is True
    facts = [create]
    if row["phase"] == "first_item":
        facts.append(row["first_item_budget_facts"])
    for fact in facts:
        assert fact["budget"] is row["budget"]
        assert fact["timeout"] == 1.0 and fact["deadline"] == create["deadline"]
        assert fact["before"] <= fact["after"]
        assert max(0.0, fact["deadline"] - fact["after"]) <= fact["remaining"]
        assert fact["remaining"] <= max(0.0, fact["deadline"] - fact["before"])
    start = row["start_boundary"]
    assert start["owner"] is row.owner and start["invocation"] is row.invocation
    assert start["ticket"] is row["ticket"]
    assert start["before"] <= start["after"] <= row.adapter_entry
    assert row.get("config_boundaries"), "missing configuration evidence"
    for config in row["config_boundaries"]:
        assert config["value"] == (1.0, True) and config["invocation"] is row.invocation
        assert config["thread"] is row.get("invocation_thread", start["thread"])
        assert start["thread"] is row["http_thread"]
        assert config["before"] <= config["after"]


def _validate_final_timing(row, snapshots, *, now):
    """Validate real callback brackets and terminal/control/late-close ordering."""
    boundaries = row["callback_boundaries"]
    callbacks = snapshots["callbacks"][1:]
    assert len(boundaries) == len(callbacks)
    for boundary, callback in zip(boundaries, callbacks):
        assert boundary["operation"] == callback["operation"]
        assert boundary["ticket"] is row["ticket"] and boundary["initiator"] is row.owner
        assert boundary["invocation"] is row.invocation
        assert boundary["before"] <= boundary["after"] <= now
    if row.ordinal != ATTEMPTS:
        return
    control = row["control_before_release"]
    assert row["terminal_at"] <= control["start_before"] <= control["start_returned"]
    assert control["start_returned"] <= control["at"] <= row.release_returned
    finish = boundaries[-1]
    assert finish["operation"] == "finish"
    closes = [item for item in snapshots["events"] if item["kind"] == "stream_close_before"]
    assert len(closes) == 1
    if row["phase"] == "headers":
        assert row.release_returned <= finish["before"] <= finish["after"]
        assert row.release_returned <= closes[0]["at"]
    else:
        # Invocation timing ends on timeout; physical settlement is proven separately.
        assert finish["after"] <= row.release_returned



def assert_completed_result(scenario) -> None:
    """Accept only the complete identity-linked result, independently for either consumer."""
    assert scenario is not None, "missing scenario"
    result = getattr(scenario, "result", None)
    required = {"bodies", "expected_body", "cleanup", "prompt_calls", "state", "rows",
                "backoff_gaps", "budgets", "terminal_at", "settlements", "releases", "final", "error"}
    assert isinstance(result, dict) and required <= result.keys(), "missing completed result/key"
    assert isinstance(scenario.records, dict) and isinstance(scenario.settlements, dict)
    assert set(scenario.records) == set(scenario.settlements) == set(range(1, 19))
    assert result["settlements"] is scenario.settlements
    assert result["final"] is scenario.records[18] and result["error"] is scenario.chat_error
    assert len(result["releases"]) == len(result["budgets"]) == 18
    assert result["releases"] == scenario.releases
    for ordinal, row in scenario.records.items():
        assert row.ordinal == ordinal
        completed = row.completed_bundle
        assert isinstance(completed, dict), "missing completed authority"
        assert completed is scenario.settlements[ordinal]
        assert {"success", "settler_join", "validated_at", "candidate_at", "ordinal", "raw",
                "handler", "callbacks", "quiescence", "events", "owner", "invocation",
                "close_finished", "close_state", "close_error", "disposal_error", "primary_error"} <= completed.keys()
        assert completed["ordinal"] == ordinal
        phase = "receive_response_headers" if scenario.phase == "headers" else "receive_response_body"
        worker = row["http_thread"] if scenario.phase == "headers" else row.owner.fetch_thread
        assert all(item["thread"] is worker for item in row["http_phases"] if phase in item["name"])
        assert result["budgets"][ordinal - 1] is row["budget"]
        assert completed["candidate_at"] <= completed["validated_at"] <= row.settlement_deadline
    result = scenario.result
    assert len(result["bodies"]) == 18
    assert all(body == result["expected_body"] for body in result["bodies"])
    assert result["cleanup"]["restoration_complete"] is True
    assert set(scenario.records) == set(range(1, 19))
    assert len(scenario.records) == 18
    assert len(scenario.releases) == 18
    assert scenario.chat_error is not None
    assert result["prompt_calls"] == ()
    assert result["state"]["dropped_request_body_count"] == 0
    assert len(result["rows"]) == 18
    assert all(row is scenario.records[index] for index, row in enumerate(result["rows"], 1))
    for field in ("invocation", "owner", "ticket", "budget"):
        assert len({id(row[field]) for row in result["rows"]}) == 18
    assert all(item.get("success") for item in scenario.settlements.values())
    assert len(scenario.settlements) == 18
    for ordinal, row in scenario.records.items():
        completed = row.completed_bundle
        assert completed is scenario.settlements[ordinal]
        assert completed["settler_join"]["thread"] is row["settlement_worker"]
        assert completed["validated_at"] <= row.settlement_deadline
        assert row["abandoned_at"] <= row.release_returned <= row["release_deadline"]
        assert completed["raw"] is row.raw_event["raw"]
        assert completed["handler"]["connection_closed"] is True
        assert completed["callbacks"]
        assert completed["settler_join"]["never_started"] is False
        assert completed["settler_join"]["at"] <= row.settlement_deadline
        validate_settlement(row, completed, now=completed["candidate_at"])
    final = scenario.records[18]
    control = final["control_before_release"]
    assert scenario.result["terminal_at"] <= control["start_before"] <= control["start_returned"]
    assert control["start_returned"] <= control["at"]
    assert control["pool"] is scenario.resources.pool
    assert control["client"] is not control["primary_client"]
    assert control["control_key"] != control["primary_key"]
    assert final["control_survival"]["client"] is control["client"]
    assert final["control_survival"]["stream"] is control["stream"]
    assert final["control_before_release"]["at"] <= final.release_returned
    assert final.completed_bundle["validated_at"] <= final["primary_close"]["at"]
    assert final["primary_close"]["at"] <= final["control_survival"]["at"]
    assert final["control_survival"]["at"] <= final["control_settlement"]["released"]
    assert final["control_settlement"]["content"] == "CONTROL"
    assert final["control_settlement"]["lease_released"] is True
    assert final["no19"]["end"] - final["no19"]["start"] >= 5
    assert scenario.primary.server.lifecycle_capture.state()["dropped_lifecycle_count"] == 0

    result = scenario.result
    assert len(result["backoff_gaps"]) == 17
    assert all(gap >= 5 * index for index, gap in enumerate(result["backoff_gaps"], 1))
    assert sum(result["backoff_gaps"]) >= 765
    assert len({id(budget) for budget in result["budgets"]}) == 18
    for ordinal, row in scenario.records.items():
        bundle = scenario.settlements[ordinal]
        assert row["publication"] is (scenario.phase == "first_item")
        assert bundle["quiescence"]["invocation_exited"] is True
        assert bundle["callbacks"][0]["operation"] == "start"
        assert bundle["callbacks"][-1]["operation"] == "finish"
        if scenario.phase == "first_item":
            assert row["first_item_budget"] is row["budget"]
