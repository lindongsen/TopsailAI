"""Scoped, transparent observations for U4 warning acceptance tests."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

from topsailai.ai_base.llm_control.first_byte_deadline import FirstBytePhase
from topsailai.ai_base.llm_control.llm_call_mixin import LLMCallMixin
from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner, current_response_owner
from topsailai.ai_base.llm_pool.openai_client_pool import OpenAIResponseAdapter


class WarningObservation:
    """Record scoped phase, response, extraction, close, and error evidence."""

    def __init__(self):
        """Initialize isolated observation state."""
        self._lock = threading.RLock()
        self.events = []
        self._patches = []
        self._stream_close_patches = {}
        self._started = False
        self._phase_counts = {}
        self._model_patches = []
        self._restoration_complete = False

    def _append(self, kind, **values):
        """Append one timestamped event under the observation lock."""
        with self._lock:
            self.events.append({"kind": kind, "at": time.monotonic(), **values})

    def start(self):
        """Install transparent class delegates before response custody is published."""
        if self._started:
            return self
        self._restoration_complete = False
        self._started = True
        original_publish = FirstBytePhase.publish
        original_response = AttemptResponseOwner.publish_response
        original_eof = AttemptResponseOwner.publish_eof
        original_error = AttemptResponseOwner.publish_error
        original_extract = LLMCallMixin._extract_stream_content
        original_translate = OpenAIResponseAdapter.translate_error

        def publish(phase, *args, **kwargs):
            """Delegate phase publication and record its scoped owner evidence."""
            owner = current_response_owner()
            result = original_publish(phase, *args, **kwargs)
            label = self._phase_label(owner)
            self._append("phase", phase=phase, owner=owner,
                         label=label,
                         budget=phase.budget, budget_id=id(phase.budget),
                         deadline=phase.budget.deadline, timeout=phase.budget.timeout,
                         result=result, completed_at=phase.completed_at,
                         published_at=phase.published_at,
                         abandoned_before=bool(getattr(owner, "_abandoned", False)))
            return result

        def response(owner, value):
            """Install a recorder on the raw SDK response before custody publication."""
            raw = getattr(value, "_response", None)
            self._append("response_before", owner=owner, response=value, raw=raw)
            raw_key = id(raw)
            if raw is not None and hasattr(raw, "close") and raw_key not in self._stream_close_patches:
                original_raw_close = raw.close

                def raw_close(*args, **kwargs):
                    """Record and delegate the raw SDK response close exactly."""
                    self._append("stream_close_before", owner=owner, stream=value, raw=raw)
                    try:
                        return original_raw_close(*args, **kwargs)
                    finally:
                        self._append("stream_close_after", owner=owner, stream=value, raw=raw)

                try:
                    raw.close = raw_close
                    self._stream_close_patches[raw_key] = (raw, original_raw_close)
                except (AttributeError, TypeError):
                    self._append("stream_close_uninstrumented", owner=owner, stream=value, raw=raw)
            result = original_response(owner, value)
            self._append("response", owner=owner, response=value, raw=raw, result=result)
            return result
        def eof(owner, *args, **kwargs):
            """Delegate EOF publication without changing its result."""
            result = original_eof(owner, *args, **kwargs)
            self._append("eof", owner=owner, result=result)
            return result

        def error(owner, value, *args, **kwargs):
            """Delegate exact error publication and retain exception identity."""
            try:
                return original_error(owner, value, *args, **kwargs)
            finally:
                self._append("error", owner=owner, error=value)

        def extract(model, stream_part):
            """Delegate decoded content extraction and record the result."""
            result = original_extract(model, stream_part)
            self._append("extract", content=result, model=model)
            return result

        def translate(error):
            """Delegate provider translation and record both exception identities."""
            translated = original_translate(error)
            self._append("translate", original=error, translated=translated)
            return translated

        self._patches = [
            patch.object(FirstBytePhase, "publish", publish),
            patch.object(AttemptResponseOwner, "publish_response", response),
            patch.object(AttemptResponseOwner, "publish_eof", eof),
            patch.object(AttemptResponseOwner, "publish_error", error),
            patch.object(OpenAIResponseAdapter, "translate_error", staticmethod(translate)),
        ]
        for item in self._patches:
            item.start()
        return self

    @staticmethod
    def _phase_label(owner):
        """Identify the phase from the owner's explicitly staged outcome."""
        outcomes = getattr(owner, "_outcomes", {})
        for label in ("create", "first_item"):
            outcome = outcomes.get(label)
            if outcome is not None and getattr(outcome, "kind", "NOT_READY") != "NOT_READY":
                return label
        return "unknown"

    def attach_model(self, model):
        """Observe the concrete model extractor without changing its identity."""
        original = model._extract_stream_content

        def extract(stream_part):
            """Delegate extraction on the concrete model instance."""
            result = original(stream_part)
            self._append("extract", content=result, model=model)
            return result

        patcher = patch.object(model, "_extract_stream_content", extract)
        patcher.start()
        self._model_patches.append(patcher)
        return model

    def stop(self):
        """Restore raw instance methods and all class delegates."""
        errors = []
        host_interrupts = []
        for stream, original in list(self._stream_close_patches.values()):
            try:
                stream.close = original
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupts.append(error)
            except BaseException as error:
                errors.append(error)
        if not errors and not host_interrupts:
            self._stream_close_patches.clear()
        for item in reversed(self._model_patches):
            try:
                item.stop()
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupts.append(error)
            except BaseException as error:
                errors.append(error)
        if not errors and not host_interrupts:
            self._model_patches.clear()
        for item in reversed(self._patches):
            try:
                item.stop()
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupts.append(error)
            except BaseException as error:
                errors.append(error)
        if not errors and not host_interrupts:
            self._patches.clear()
        self._restoration_complete = not errors and not host_interrupts
        self._started = not self._restoration_complete
        primary = host_interrupts[0] if host_interrupts else (errors[0] if errors else None)
        if primary is not None:
            for diagnostic in host_interrupts[1:] + errors[1 if not host_interrupts else 0:]:
                try:
                    primary.add_note(f"observer cleanup failed: {diagnostic!r}")
                except BaseException:
                    pass
            raise primary


    @property
    def restoration_complete(self):
        """Return whether every installed delegate has been restored."""
        return self._restoration_complete

    def phase_events(self):
        """Return a stable snapshot of phase publication records."""
        with self._lock:
            return [event.copy() for event in self.events if event["kind"] == "phase"]

    def events_for(self, kind):
        """Return a stable snapshot for one event kind."""
        with self._lock:
            return [event.copy() for event in self.events if event["kind"] == kind]

    def assert_settled(self, owners):
        """Join every exact owner worker before observation is removed."""
        failures = []
        host_interrupts = []
        for owner in owners:
            for name in ("create_thread", "fetch_thread", "cleanup_thread"):
                worker = getattr(owner, name, None)
                if worker is None:
                    continue
                try:
                    worker.join(5)
                except (KeyboardInterrupt, SystemExit) as error:
                    host_interrupts.append(error)
                except BaseException as error:
                    failures.append(f"{name} join failed for owner {id(owner)}: {error!r}")
                try:
                    if worker.is_alive():
                        failures.append(f"{name} remained alive for owner {id(owner)}")
                except (KeyboardInterrupt, SystemExit) as error:
                    host_interrupts.append(error)
                except BaseException as error:
                    failures.append(f"{name} liveness check failed for owner {id(owner)}: {error!r}")
            try:
                settled = owner.close_finished_event.wait(5)
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupts.append(error)
                settled = False
            except BaseException as error:
                failures.append(f"close wait failed for owner {id(owner)}: {error!r}")
                settled = False
            if not settled:
                failures.append(f"close did not finish for owner {id(owner)}")
            try:
                close_state = getattr(getattr(owner, "_close_state", None), "name", None)
                if close_state == "FAILED":
                    failures.append(f"close failed for owner {id(owner)}")
                if getattr(owner, "disposal_error", None) is not None:
                    failures.append(f"disposal failed for owner {id(owner)}")
            except (KeyboardInterrupt, SystemExit) as error:
                host_interrupts.append(error)
            except BaseException as error:
                failures.append(f"close state inspection failed for owner {id(owner)}: {error!r}")
        primary = host_interrupts[0] if host_interrupts else None
        if primary is not None:
            for diagnostic in host_interrupts[1:] + [*failures]:
                try:
                    primary.add_note(f"owner settlement diagnostic: {diagnostic!r}")
                except BaseException:
                    pass
            raise primary
        if failures:
            raise AssertionError("; ".join(failures))


def assert_transparent_call(delegate, expected, *args, **kwargs):
    """Verify a delegate returns the exact result object."""
    assert delegate(*args, **kwargs) is expected
