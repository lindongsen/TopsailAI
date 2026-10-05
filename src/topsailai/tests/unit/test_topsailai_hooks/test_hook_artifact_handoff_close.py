"""Focused regressions for U07 creation handoff and descriptor close authority."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from topsailai.hooks.artifact_cleanup import DescriptorLedger
from topsailai.hooks.artifact_store import ArtifactCapturePolicy, get_artifact_recovery_owner

from .test_hook_artifact_ownership import _fixture


def test_capture_directory_return_handoff_remains_cleanup_owned(
    monkeypatch, tmp_path: Path
) -> None:
    """Clean a directory when interruption occurs after helper return."""
    owner, request, artifact_root = _fixture(tmp_path)
    create_directory = owner._create_capture_directory
    interruption = KeyboardInterrupt("directory helper return interrupted")

    def create_then_interrupt(slot, checkpoint) -> None:
        create_directory(slot, checkpoint)
        assert slot.directory is not None and not slot.uncertain_creation
        raise interruption

    monkeypatch.setattr(owner, "_create_capture_directory", create_then_interrupt)
    try:
        owner.capture((request,))
    except KeyboardInterrupt as exc:
        assert exc is interruption
        assert get_artifact_recovery_owner(exc) is None
    else:
        raise AssertionError("creation handoff interruption was swallowed")
    assert owner.cleanup_debts() == ()
    assert not list(artifact_root.iterdir())
    assert owner.close().accepted


def test_reservation_publication_interruption_releases_empty_slot(
    monkeypatch, tmp_path: Path
) -> None:
    """Release a published reservation interrupted before admission I/O."""
    import topsailai.hooks.artifact_store as store

    owner, request, artifact_root = _fixture(tmp_path)
    policy = ArtifactCapturePolicy(max_file_bytes=1024, max_total_bytes=1024)
    prior = owner.capture((request,), policy=policy)
    assert prior.accepted and prior.artifact is not None
    prior_artifact = prior.artifact
    prior_identity = prior_artifact.identity
    prior_entries = prior_artifact.entries
    prior_directory = prior_artifact.directory
    prior_children = tuple(
        sorted(path.relative_to(prior_directory) for path in prior_directory.rglob("*"))
    )
    baseline_slots = tuple(owner._slots)
    interruption = KeyboardInterrupt("reservation publication interrupted")
    admission_opens = 0
    real_open = store.os.open

    class InterruptAfterPublication(dict):
        """Raise once after recording a newly published reservation."""

        armed = True

        def __setitem__(self, key, value) -> None:
            super().__setitem__(key, value)
            if self.armed and key not in baseline_slots:
                self.armed = False
                raise interruption

    def forbidden_open(*args, **kwargs):
        nonlocal admission_opens
        admission_opens += 1
        raise AssertionError("reservation interruption reached admission I/O")

    owner._slots = InterruptAfterPublication(owner._slots)
    monkeypatch.setattr(store.os, "open", forbidden_open)
    try:
        owner.capture((request,), policy=policy)
    except KeyboardInterrupt as exc:
        assert exc is interruption
        assert get_artifact_recovery_owner(exc) is None
    else:
        raise AssertionError("reservation publication interruption was swallowed")
    finally:
        monkeypatch.setattr(store.os, "open", real_open)

    assert admission_opens == 0
    assert tuple(owner._slots) == baseline_slots
    assert owner.cleanup_debts() == ()
    assert not prior_artifact.disposed
    assert prior_artifact.identity == prior_identity
    assert prior_artifact.entries == prior_entries
    assert prior_directory.is_dir()
    assert tuple(
        sorted(path.relative_to(prior_directory) for path in prior_directory.rglob("*"))
    ) == prior_children
    assert len(list(artifact_root.iterdir())) == 1
    subsequent = owner.capture((request,), policy=policy)
    assert subsequent.accepted and subsequent.artifact is not None
    assert len(owner._slots) == len(baseline_slots) + 1
    assert owner.close().accepted
    assert not list(artifact_root.iterdir())


@pytest.mark.parametrize(
    "boundary", ("publication_before", "publication_after", "pre_open")
)
def test_descriptor_reservation_handoff_releases_empty_record(
    monkeypatch, tmp_path: Path, boundary: str
) -> None:
    """Release an exact empty reservation without starting acquisition I/O."""
    import inspect
    import sys
    import topsailai.hooks.artifact_cleanup as cleanup

    source = tmp_path / "reservation-source"
    unrelated = tmp_path / "reservation-unrelated"
    source.write_bytes(b"owned")
    unrelated.write_bytes(b"unrelated")
    unrelated_fd = os.open(unrelated, os.O_RDONLY)
    ledger = DescriptorLedger()
    interruption = KeyboardInterrupt(boundary)
    real_open = cleanup.os.open
    acquisition_calls = 0
    armed = True

    class InterruptReservation(dict):
        """Interrupt immediately before or after empty-record publication."""

        def __setitem__(self, key, value) -> None:
            nonlocal armed
            if armed and boundary == "publication_before":
                armed = False
                raise interruption
            super().__setitem__(key, value)
            if armed and boundary == "publication_after":
                armed = False
                raise interruption

    def observed_open(*args, **kwargs):
        nonlocal acquisition_calls
        acquisition_calls += 1
        return real_open(*args, **kwargs)

    ledger._records = InterruptReservation()
    previous_trace = sys.gettrace()
    if boundary == "pre_open":
        source_lines, first_line = inspect.getsourcelines(DescriptorLedger.open)
        handoff_line = first_line + next(
            index
            for index, line in enumerate(source_lines)
            if "acquisition_started = True" in line
        )

        def interrupt_before_acquisition(frame, event, argument):
            if (
                frame.f_code is DescriptorLedger.open.__code__
                and event == "line"
                and frame.f_lineno == handoff_line
            ):
                sys.settrace(previous_trace)
                raise interruption
            return interrupt_before_acquisition

        sys.settrace(interrupt_before_acquisition)
    monkeypatch.setattr(cleanup.os, "open", observed_open)
    try:
        ledger.open(source, os.O_RDONLY)
    except KeyboardInterrupt as exc:
        assert exc is interruption
    else:
        raise AssertionError("empty reservation interruption was swallowed")
    finally:
        sys.settrace(previous_trace)
    assert acquisition_calls == 0
    assert ledger.count == 0 and ledger.close_all() == ()
    assert os.read(unrelated_fd, 9) == b"unrelated"
    monkeypatch.setattr(cleanup.os, "open", real_open)
    subsequent = ledger.open(source, os.O_RDONLY)
    ledger.close(subsequent)
    assert ledger.count == 0
    os.close(unrelated_fd)


@pytest.mark.parametrize("boundary", ("publication_after", "pre_open"))
def test_capture_composition_releases_interrupted_descriptor_reservation(
    monkeypatch, tmp_path: Path, boundary: str
) -> None:
    """Restore public capture capacity after an empty-record interruption."""
    import inspect
    import sys
    import topsailai.hooks.artifact_cleanup as cleanup

    owner, request, artifact_root = _fixture(tmp_path)
    interruption = KeyboardInterrupt(boundary)
    real_open = cleanup.os.open
    acquisition_calls = 0
    armed = True

    class InterruptReservation(dict):
        """Interrupt once after publishing the first empty record."""

        def __setitem__(self, key, value) -> None:
            nonlocal armed
            super().__setitem__(key, value)
            if armed and boundary == "publication_after":
                armed = False
                raise interruption

    original_init = DescriptorLedger.__init__

    def init_with_interrupting_records(self) -> None:
        original_init(self)
        self._records = InterruptReservation()

    def observed_open(*args, **kwargs):
        nonlocal acquisition_calls
        acquisition_calls += 1
        return real_open(*args, **kwargs)

    monkeypatch.setattr(DescriptorLedger, "__init__", init_with_interrupting_records)
    monkeypatch.setattr(cleanup.os, "open", observed_open)
    previous_trace = sys.gettrace()
    if boundary == "pre_open":
        source_lines, first_line = inspect.getsourcelines(DescriptorLedger.open)
        handoff_line = first_line + next(
            index
            for index, line in enumerate(source_lines)
            if "acquisition_started = True" in line
        )

        def interrupt_before_acquisition(frame, event, argument):
            if (
                frame.f_code is DescriptorLedger.open.__code__
                and event == "line"
                and frame.f_lineno == handoff_line
            ):
                sys.settrace(previous_trace)
                raise interruption
            return interrupt_before_acquisition

        sys.settrace(interrupt_before_acquisition)
    try:
        owner.capture((request,))
    except KeyboardInterrupt as exc:
        assert exc is interruption
    else:
        raise AssertionError("public empty reservation interruption was swallowed")
    finally:
        sys.settrace(previous_trace)
    assert acquisition_calls == 0
    assert owner.cleanup_debts() == ()
    assert not list(artifact_root.iterdir())
    armed = False
    monkeypatch.setattr(cleanup.os, "open", real_open)
    subsequent = owner.capture((request,))
    assert subsequent.accepted and subsequent.artifact is not None
    assert owner.close().accepted
    assert not list(artifact_root.iterdir())


def test_descriptor_acquisition_interruption_settles_exact_authority(
    tmp_path: Path,
) -> None:
    """Settle exact authority when descriptor-map publication interrupts."""
    source = tmp_path / "descriptor-source"
    source.write_bytes(b"owned")
    ledger = DescriptorLedger()
    interruption = KeyboardInterrupt("descriptor publication interrupted")
    acquired: list[int] = []

    class InterruptAfterDescriptorPublication(dict):
        """Raise after publishing descriptor-to-obligation ownership."""

        def __setitem__(self, key, value) -> None:
            super().__setitem__(key, value)
            acquired.append(key)
            raise interruption

    ledger._by_descriptor = InterruptAfterDescriptorPublication()
    try:
        ledger.open(source, os.O_RDONLY)
    except KeyboardInterrupt as exc:
        assert exc is interruption
    else:
        raise AssertionError("descriptor publication interruption was swallowed")

    assert len(acquired) == 1
    descriptor = acquired[0]
    assert ledger.count == 0
    assert ledger.close_all() == ()
    try:
        os.fstat(descriptor)
    except OSError:
        pass
    else:
        raise AssertionError("interrupted publication left descriptor open")


@pytest.mark.parametrize("boundary", ("record", "map"))
def test_descriptor_publication_boundaries_settle_exact_authority(
    monkeypatch, tmp_path: Path, boundary: str
) -> None:
    """Settle exact authority at both descriptor publication operations."""
    import topsailai.hooks.artifact_cleanup as cleanup

    source = tmp_path / "descriptor-boundary-source"
    unrelated = tmp_path / "descriptor-boundary-unrelated"
    source.write_bytes(b"owned")
    unrelated.write_bytes(b"unrelated")
    unrelated_fd = os.open(unrelated, os.O_RDONLY)
    ledger = DescriptorLedger()
    interruption = KeyboardInterrupt(boundary)
    open_descriptors: list[int] = []
    closed_descriptors: list[int] = []
    real_open = cleanup.os.open
    real_close = cleanup.os.close
    armed = True

    def observed_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        open_descriptors.append(descriptor)
        return descriptor

    def observed_close(descriptor: int) -> None:
        closed_descriptors.append(descriptor)
        real_close(descriptor)

    if boundary == "record":
        obligation_type = type(next(iter(ledger._records.values()), None))
        if obligation_type is type(None):
            obligation_type = cleanup._DescriptorObligation
        real_setattr = obligation_type.__setattr__

        def interrupt_record_publication(self, name, value) -> None:
            nonlocal armed
            if armed and name == "descriptor" and value is not None:
                armed = False
                raise interruption
            real_setattr(self, name, value)

        monkeypatch.setattr(obligation_type, "__setattr__", interrupt_record_publication)
    else:
        class InterruptBeforeMapPublication(dict):
            """Raise once before descriptor-map publication."""

            def __setitem__(self, key, value) -> None:
                nonlocal armed
                if armed:
                    armed = False
                    raise interruption
                super().__setitem__(key, value)

        ledger._by_descriptor = InterruptBeforeMapPublication()

    monkeypatch.setattr(cleanup.os, "open", observed_open)
    monkeypatch.setattr(cleanup.os, "close", observed_close)
    try:
        ledger.open(source, os.O_RDONLY)
    except KeyboardInterrupt as exc:
        assert exc is interruption
    else:
        raise AssertionError("descriptor publication interruption was swallowed")
    assert len(open_descriptors) == 1
    assert closed_descriptors == open_descriptors
    assert ledger.count == 0 and ledger.close_all() == ()
    assert os.read(unrelated_fd, 9) == b"unrelated"
    subsequent = ledger.open(source, os.O_RDONLY)
    ledger.close(subsequent)
    assert ledger.count == 0
    real_close(unrelated_fd)


@pytest.mark.parametrize("boundary", ("record", "map"))
def test_capture_composition_settles_interrupted_descriptor_publication(
    monkeypatch, tmp_path: Path, boundary: str
) -> None:
    """Stop capture I/O and restore capacity after publication interruption."""
    import topsailai.hooks.artifact_cleanup as cleanup

    owner, request, artifact_root = _fixture(tmp_path)
    interruption = KeyboardInterrupt(boundary)
    interrupted = False
    later_opens = 0
    armed = True
    real_open = cleanup.os.open

    def observed_open(*args, **kwargs):
        nonlocal later_opens
        if interrupted:
            later_opens += 1
            raise AssertionError("capture continued admission I/O after interruption")
        return real_open(*args, **kwargs)

    if boundary == "record":
        obligation_type = cleanup._DescriptorObligation
        real_setattr = obligation_type.__setattr__

        def interrupt_record_publication(self, name, value) -> None:
            nonlocal armed, interrupted
            if armed and name == "descriptor" and value is not None:
                armed = False
                interrupted = True
                raise interruption
            real_setattr(self, name, value)

        monkeypatch.setattr(obligation_type, "__setattr__", interrupt_record_publication)
    else:
        class InterruptBeforeMapPublication(dict):
            """Raise once before descriptor-map publication."""

            def __setitem__(self, key, value) -> None:
                nonlocal armed, interrupted
                if armed:
                    armed = False
                    interrupted = True
                    raise interruption
                super().__setitem__(key, value)

        original_init = DescriptorLedger.__init__

        def init_with_interrupting_map(self) -> None:
            original_init(self)
            self._by_descriptor = InterruptBeforeMapPublication()

        monkeypatch.setattr(DescriptorLedger, "__init__", init_with_interrupting_map)

    monkeypatch.setattr(cleanup.os, "open", observed_open)
    try:
        owner.capture((request,))
    except KeyboardInterrupt as exc:
        assert exc is interruption
    else:
        raise AssertionError("capture publication interruption was swallowed")
    assert later_opens == 0
    assert owner.cleanup_debts() == ()
    assert not list(artifact_root.iterdir())
    interrupted = False
    subsequent = owner.capture((request,))
    assert subsequent.accepted and subsequent.artifact is not None
    assert owner.close().accepted
    assert not list(artifact_root.iterdir())


@pytest.mark.parametrize("secondary_type", (OSError, KeyboardInterrupt))
def test_interrupted_publication_close_failure_retains_nonretryable_debt(
    monkeypatch, tmp_path: Path, secondary_type
) -> None:
    """Keep the host primary and never retry an ambiguous settlement close."""
    import topsailai.hooks.artifact_cleanup as cleanup

    owned = tmp_path / "settlement-owned"
    external = tmp_path / "settlement-external"
    owned.write_bytes(b"owned")
    external.write_bytes(b"external")
    ledger = DescriptorLedger()
    primary = KeyboardInterrupt("publication primary")
    real_close = cleanup.os.close
    external_fd: int | None = None

    class InterruptMap(dict):
        """Interrupt before descriptor-map publication."""

        def __setitem__(self, key, value) -> None:
            raise primary

    def close_reuse_then_fail(descriptor: int) -> None:
        nonlocal external_fd
        real_close(descriptor)
        external_fd = os.open(external, os.O_RDONLY)
        assert external_fd == descriptor
        raise secondary_type("settlement close secondary")

    ledger._by_descriptor = InterruptMap()
    monkeypatch.setattr(cleanup.os, "close", close_reuse_then_fail)
    try:
        ledger.open(owned, os.O_RDONLY)
    except KeyboardInterrupt as exc:
        assert exc is primary
    else:
        raise AssertionError("publication primary was swallowed")
    assert ledger.count == 1 and ledger.has_outstanding()
    record = next(iter(ledger._records.values()))
    assert record.descriptor is None and record.uncertain_close
    assert ledger.close_all() == () and ledger.count == 1
    assert os.read(external_fd, 8) == b"external"
    real_close(external_fd)


def test_caller_first_statement_interruption_keeps_owner_cleanup_authority(
    tmp_path: Path,
) -> None:
    """Preserve prior global/local tracing while owning the caller frame."""
    import inspect
    import sys

    owner, request, artifact_root = _fixture(tmp_path)
    interruption = KeyboardInterrupt("caller first statement interrupted")
    sentinel_events: list[tuple[str, str]] = []

    def unrelated_frame() -> None:
        sentinel_events.append(("unrelated", "body"))

    def untraced_frame() -> None:
        sentinel_events.append(("untraced", "body"))

    def sentinel_local(frame, event, argument):
        sentinel_events.append((frame.f_code.co_name, event))
        return sentinel_local

    def sentinel_global(frame, event, argument):
        sentinel_events.append((frame.f_code.co_name, event))
        return sentinel_local if frame.f_code is unrelated_frame.__code__ else None

    def combine_locals(first, second):
        if first is None:
            return second
        if second is None:
            return first

        def combined(frame, event, argument):
            return combine_locals(
                first(frame, event, argument), second(frame, event, argument)
            )

        return combined

    original_trace = sys.gettrace()

    def previous_global(frame, event, argument):
        original_local = (
            original_trace(frame, event, argument)
            if original_trace is not None
            else None
        )
        return combine_locals(original_local, sentinel_global(frame, event, argument))

    def call_capture():
        unrelated_frame()
        untraced_frame()
        result = owner.capture((request,))
        marker = result
        return marker

    source, first_line = inspect.getsourcelines(call_capture)
    marker_line = first_line + next(
        index for index, line in enumerate(source) if "marker = result" in line
    )
    delegated_traces: dict[int, object] = {}
    declined_frames: set[int] = set()

    def interrupt_before_marker(frame, event, argument):
        if frame.f_code is call_capture.__code__:
            if event == "line" and frame.f_lineno == marker_line:
                sys.settrace(original_trace)
                raise interruption
            return interrupt_before_marker
        frame_id = id(frame)
        if event == "call":
            delegate = previous_global(frame, event, argument)
            if delegate is None:
                declined_frames.add(frame_id)
            else:
                delegated_traces[frame_id] = delegate
        elif frame_id in delegated_traces:
            delegate = delegated_traces[frame_id]
            next_delegate = delegate(frame, event, argument)
            if next_delegate is None:
                delegated_traces.pop(frame_id, None)
            else:
                delegated_traces[frame_id] = next_delegate
        if event == "return":
            delegated_traces.pop(frame_id, None)
        return interrupt_before_marker

    sys.settrace(interrupt_before_marker)
    try:
        call_capture()
    except KeyboardInterrupt as exc:
        assert exc is interruption
        assert get_artifact_recovery_owner(exc) is None
    else:
        raise AssertionError("caller-line interruption was swallowed")
    finally:
        sys.settrace(original_trace)
    assert sys.gettrace() is original_trace
    assert ("unrelated_frame", "call") in sentinel_events
    assert ("unrelated_frame", "line") in sentinel_events
    assert ("unrelated_frame", "return") in sentinel_events
    assert ("untraced_frame", "call") in sentinel_events
    assert ("untraced_frame", "line") not in sentinel_events
    assert ("untraced_frame", "return") not in sentinel_events
    assert declined_frames
    assert owner.cleanup_debts() == ()
    assert len(list(artifact_root.iterdir())) == 1
    assert owner.close().accepted
    assert not list(artifact_root.iterdir())


def test_interruption_after_close_return_never_retries_reused_descriptor(
    monkeypatch, tmp_path: Path
) -> None:
    """Revoke close authority before the real post-return line boundary."""
    import inspect
    import sys

    owned_path = tmp_path / "owned"
    external_path = tmp_path / "external"
    owned_path.write_bytes(b"owned")
    external_path.write_bytes(b"external")
    ledger = DescriptorLedger()
    descriptor = ledger.open(owned_path, os.O_RDONLY)
    source, first_line = inspect.getsourcelines(DescriptorLedger.close)
    settle_line = first_line + next(
        index for index, line in enumerate(source) if "self._records.pop" in line
    )
    external_descriptor: int | None = None
    interruption = KeyboardInterrupt("interrupted after close returned")
    previous_trace = sys.gettrace()
    delegated_traces = {}

    def interrupt_at_settlement(frame, event, argument):
        nonlocal external_descriptor
        if frame.f_code is DescriptorLedger.close.__code__:
            if frame.f_lineno == settle_line:
                sys.settrace(previous_trace)
                external_descriptor = os.open(external_path, os.O_RDONLY)
                assert external_descriptor == descriptor
                raise interruption
            return interrupt_at_settlement
        frame_id = id(frame)
        delegate = previous_trace if event == "call" else delegated_traces.get(
            frame_id, previous_trace
        )
        if delegate is not None:
            next_delegate = delegate(frame, event, argument)
            if event == "return" or next_delegate is None:
                delegated_traces.pop(frame_id, None)
            else:
                delegated_traces[frame_id] = next_delegate
        return interrupt_at_settlement

    sys.settrace(interrupt_at_settlement)
    try:
        ledger.close(descriptor)
    except KeyboardInterrupt as exc:
        assert exc is interruption
    else:
        raise AssertionError("close settlement interruption was swallowed")
    finally:
        sys.settrace(previous_trace)
    assert sys.gettrace() is previous_trace
    assert external_descriptor == descriptor
    assert ledger.count == 1 and ledger.has_outstanding()
    assert ledger.close_all() == () and ledger.count == 1
    assert os.read(external_descriptor, 8) == b"external"
    os.close(external_descriptor)


def test_ordinary_close_error_never_retries_reused_descriptor(
    monkeypatch, tmp_path: Path
) -> None:
    """Treat an ordinary close error as uncertain after descriptor reuse."""
    import topsailai.hooks.artifact_cleanup as cleanup

    owned_path = tmp_path / "owned-error"
    external_path = tmp_path / "external-error"
    owned_path.write_bytes(b"owned")
    external_path.write_bytes(b"external")
    ledger = DescriptorLedger()
    descriptor = ledger.open(owned_path, os.O_RDONLY)
    real_close = cleanup.os.close
    external_descriptor: int | None = None

    def close_reuse_then_error(value: int) -> None:
        nonlocal external_descriptor
        real_close(value)
        external_descriptor = os.open(external_path, os.O_RDONLY)
        assert external_descriptor == value
        raise OSError("close outcome reported as failure")

    monkeypatch.setattr(cleanup.os, "close", close_reuse_then_error)
    try:
        ledger.close(descriptor)
    except OSError as exc:
        assert str(exc) == "close outcome reported as failure"
    else:
        raise AssertionError("ordinary close error was swallowed")
    assert external_descriptor == descriptor
    assert ledger.count == 1 and ledger.has_outstanding()

    monkeypatch.setattr(cleanup.os, "close", real_close)
    assert ledger.close_all() == () and ledger.count == 1
    assert os.read(external_descriptor, 8) == b"external"
    real_close(external_descriptor)
