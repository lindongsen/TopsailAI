"""Settlement handoff assertions for artifact descriptor tests."""

from __future__ import annotations

import inspect
import os
from pathlib import Path

from topsailai.hooks.artifact_cleanup import DescriptorLedger
from topsailai.hooks.artifact_store import get_artifact_recovery_owner

from .artifact_trace_helpers import composed_line_interruption


class _InterruptMap(dict):
    """Interrupt descriptor-map publication with one exact host primary."""

    def __init__(self, primary: BaseException) -> None:
        super().__init__()
        self._primary = primary

    def __setitem__(self, key, value) -> None:
        raise self._primary


class _PublishThenInterruptMap(dict):
    """Publish descriptor authority before raising one exact host primary."""

    def __init__(self, primary: BaseException) -> None:
        super().__init__()
        self._primary = primary

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        raise self._primary


def _settlement_line(ledger: DescriptorLedger, text: str) -> int:
    """Return one exact executable line in interrupted publication settlement."""
    source, first_line = inspect.getsourcelines(ledger._settle_interrupted_publication)
    return first_line + next(
        index for index, line in enumerate(source) if text in line
    )


def assert_settlement_post_return_is_nonretryable(monkeypatch, tmp_path: Path) -> None:
    """Prove post-close-return interruption retains bounded nonretryable debt."""
    import topsailai.hooks.artifact_cleanup as cleanup

    owned, external = tmp_path / "settle-owned", tmp_path / "settle-external"
    owned.write_bytes(b"owned")
    external.write_bytes(b"external")
    ledger = DescriptorLedger()
    primary = KeyboardInterrupt("publication primary")
    interruption = KeyboardInterrupt("post-close settlement interruption")
    real_open, real_close = cleanup.os.open, cleanup.os.close
    owned_fd: int | None = None
    external_fd: int | None = None
    close_entry_states: list[tuple[bool, int | None, bool]] = []

    def observed_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal owned_fd
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path) == owned:
            owned_fd = descriptor
        return descriptor

    def observed_close(descriptor: int) -> None:
        record = next(iter(ledger._records.values()))
        close_entry_states.append(
            (record.uncertain_close, record.descriptor, descriptor in ledger._by_descriptor)
        )
        real_close(descriptor)

    def reuse_descriptor() -> None:
        nonlocal external_fd
        external_fd = real_open(external, os.O_RDONLY)

    monkeypatch.setattr(cleanup.os, "open", observed_open)
    monkeypatch.setattr(cleanup.os, "close", observed_close)
    ledger._by_descriptor = _InterruptMap(primary)
    try:
        with composed_line_interruption(
            ledger._settle_interrupted_publication.__func__.__code__,
            _settlement_line(ledger, "self._records.pop"),
            interruption,
            before_interrupt=reuse_descriptor,
        ):
            ledger.open(owned, os.O_RDONLY)
    except KeyboardInterrupt as exc:
        assert exc is primary
    else:
        raise AssertionError("publication primary was swallowed")
    record = next(iter(ledger._records.values()))
    assert owned_fd is not None and external_fd == owned_fd
    assert close_entry_states == [(True, None, False)]
    assert record.descriptor is None and record.uncertain_close
    assert ledger._by_descriptor == {}
    assert os.read(external_fd, 8) == b"external"
    assert ledger.close_all() == () and ledger.count == 1
    assert os.read(external_fd, 8) == b""
    real_close(external_fd)


def assert_intermediate_revocation_is_nonretryable(
    monkeypatch, tmp_path: Path, *, published_map: bool
) -> None:
    """Prove settlement cleanup revokes empty or published map state safely."""
    import topsailai.hooks.artifact_cleanup as cleanup

    suffix = "published" if published_map else "empty"
    owned = tmp_path / f"intermediate-{suffix}-owned"
    external = tmp_path / f"intermediate-{suffix}-external"
    owned.write_bytes(b"owned")
    external.write_bytes(b"external")
    ledger = DescriptorLedger()
    primary = KeyboardInterrupt("publication primary")
    interruption = KeyboardInterrupt("intermediate revocation interruption")
    real_close = cleanup.os.close
    close_calls: list[int] = []
    map_type = _PublishThenInterruptMap if published_map else _InterruptMap
    ledger._by_descriptor = map_type(primary)
    try:
        with composed_line_interruption(
            ledger._settle_interrupted_publication.__func__.__code__,
            _settlement_line(ledger, "record.descriptor = None"),
            interruption,
        ):
            ledger.open(owned, os.O_RDONLY)
    except KeyboardInterrupt as exc:
        assert exc is primary
    else:
        raise AssertionError("publication primary was swallowed")
    record = next(iter(ledger._records.values()))
    descriptor = record.descriptor
    assert descriptor is not None and record.uncertain_close
    if published_map:
        assert ledger._by_descriptor == {descriptor: record.obligation_id}
    else:
        assert ledger._by_descriptor == {}
    real_close(descriptor)
    external_fd = os.open(external, os.O_RDONLY)
    assert external_fd == descriptor

    def forbidden_close(value: int) -> None:
        close_calls.append(value)
        raise AssertionError("cleanup retried a historical descriptor")

    monkeypatch.setattr(cleanup.os, "close", forbidden_close)
    assert ledger.close_all() == () and ledger.count == 1
    assert ledger._by_descriptor == {}
    assert record.descriptor is None and record.uncertain_close
    assert close_calls == []
    assert os.read(external_fd, 8) == b"external"
    real_close(external_fd)


def assert_ordinary_close_intermediate_is_nonretryable(
    monkeypatch, tmp_path: Path, boundary: str
) -> None:
    """Prove ordinary close intermediates retain bounded nonretryable debt."""
    import topsailai.hooks.artifact_cleanup as cleanup

    owned = tmp_path / f"ordinary-{boundary}-owned"
    external = tmp_path / f"ordinary-{boundary}-external"
    owned.write_bytes(b"owned")
    external.write_bytes(b"external")
    ledger = DescriptorLedger()
    descriptor = ledger.open(owned, os.O_RDONLY)
    record = next(iter(ledger._records.values()))
    interruption = KeyboardInterrupt(f"ordinary close {boundary}")
    source, first_line = inspect.getsourcelines(DescriptorLedger.close)
    text = "self._by_descriptor.pop" if boundary == "armed" else "record.descriptor = None"
    target_line = first_line + next(
        index for index, line in enumerate(source) if text in line
    )
    try:
        with composed_line_interruption(
            DescriptorLedger.close.__code__, target_line, interruption
        ):
            ledger.close(descriptor)
    except KeyboardInterrupt as exc:
        assert exc is interruption
    else:
        raise AssertionError("ordinary close interruption was swallowed")
    assert record.uncertain_close and record.descriptor == descriptor
    if boundary == "armed":
        assert ledger._by_descriptor == {descriptor: record.obligation_id}
    else:
        assert ledger._by_descriptor == {}
    cleanup.os.close(descriptor)
    external_fd = os.open(external, os.O_RDONLY)
    assert external_fd == descriptor
    close_calls: list[int] = []
    real_close = cleanup.os.close

    def forbidden_close(value: int) -> None:
        close_calls.append(value)
        raise AssertionError("cleanup retried a historical descriptor")

    monkeypatch.setattr(cleanup.os, "close", forbidden_close)
    assert ledger.close_all() == () and ledger.count == 1
    assert ledger._by_descriptor == {}
    assert record.descriptor is None and record.uncertain_close
    assert close_calls == []
    assert os.read(external_fd, 8) == b"external"
    real_close(external_fd)

def assert_public_settlement_debt_is_owner_bound(
    monkeypatch, tmp_path: Path, owner, request, artifact_root: Path
) -> None:
    """Retain public recovery authority and capacity for settlement handoff debt."""
    import topsailai.hooks.artifact_cleanup as cleanup

    external = tmp_path / "public-settle-external"
    external.write_bytes(b"external")
    primary = KeyboardInterrupt("public publication primary")
    interruption = KeyboardInterrupt("public settlement handoff interruption")
    real_init = DescriptorLedger.__init__
    real_open, real_close = cleanup.os.open, cleanup.os.close
    opened_fd: int | None = None
    external_fd: int | None = None
    ledger: DescriptorLedger | None = None

    def interrupting_init(self) -> None:
        nonlocal ledger
        real_init(self)
        self._by_descriptor = _InterruptMap(primary)
        ledger = self

    def observed_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal opened_fd
        descriptor = real_open(path, flags, mode, dir_fd=dir_fd)
        if opened_fd is None:
            opened_fd = descriptor
        return descriptor

    def reuse_descriptor() -> None:
        nonlocal external_fd
        external_fd = real_open(external, os.O_RDONLY)

    monkeypatch.setattr(DescriptorLedger, "__init__", interrupting_init)
    monkeypatch.setattr(cleanup.os, "open", observed_open)
    probe = DescriptorLedger()
    try:
        with composed_line_interruption(
            DescriptorLedger._settle_interrupted_publication.__code__,
            _settlement_line(probe, "self._records.pop"),
            interruption,
            before_interrupt=reuse_descriptor,
        ):
            owner.capture((request,))
    except KeyboardInterrupt as exc:
        assert exc is primary
        assert get_artifact_recovery_owner(exc) is owner
    else:
        raise AssertionError("public publication primary was swallowed")
    assert ledger is not None
    record = next(iter(ledger._records.values()))
    assert opened_fd is not None and external_fd == opened_fd
    assert record.descriptor is None and record.uncertain_close
    assert ledger.close_all() == () and ledger.count == 1
    assert os.read(external_fd, 8) == b"external"
    debts = owner.cleanup_debts()
    assert len(debts) == 1 and not owner.retry_cleanup(debts[0].debt_id)
    assert not list(artifact_root.iterdir())

    monkeypatch.setattr(DescriptorLedger, "__init__", real_init)
    monkeypatch.setattr(cleanup.os, "open", real_open)
    assert all(owner.capture(()).accepted for _ in range(15))
    assert owner.capture(()).errors == ("artifact_capacity_exceeded",)
    assert owner.close().cleanup_pending
    assert owner.cleanup_debts() == debts
    assert os.read(external_fd, 8) == b""
    real_close(external_fd)


def assert_successful_capture_handoff_is_cleanup_owned(
    monkeypatch, tmp_path: Path, boundary: str, owner, request, artifact_root: Path
) -> None:
    """Interrupt immediately after one successful admission or finalization operation."""
    import topsailai.hooks.artifact_store as store
    import topsailai.hooks.artifact_validation as validation

    primary = KeyboardInterrupt(f"{boundary} successful handoff")
    issued = 0
    boundary_returns = 0
    target_descriptor: int | None = None
    real_issue = store.ArtifactCaptureOwner._issue

    def interrupt_after_success(value=None):
        nonlocal boundary_returns
        boundary_returns += 1
        raise primary

    def observed_issue(*args, **kwargs):
        nonlocal issued
        issued += 1
        return real_issue(*args, **kwargs)

    monkeypatch.setattr(store.ArtifactCaptureOwner, "_issue", observed_issue)
    if boundary == "identity":
        real_operation = validation.file_identity

        def observed_identity(*args, **kwargs):
            return interrupt_after_success(real_operation(*args, **kwargs))

        monkeypatch.setattr(validation, "file_identity", observed_identity)
    elif boundary == "write":
        real_operation = store.os.write

        def observed_write(*args, **kwargs):
            return interrupt_after_success(real_operation(*args, **kwargs))

        monkeypatch.setattr(store.os, "write", observed_write)
    elif boundary == "fsync":
        real_write = store.os.write
        real_operation = store.os.fsync

        def remember_target_write(descriptor, data):
            nonlocal target_descriptor
            result = real_write(descriptor, data)
            target_descriptor = descriptor
            return result

        def observed_fsync(descriptor):
            result = real_operation(descriptor)
            if descriptor == target_descriptor:
                return interrupt_after_success(result)
            return result

        monkeypatch.setattr(store.os, "write", remember_target_write)
        monkeypatch.setattr(store.os, "fsync", observed_fsync)
    elif boundary == "revalidation":
        real_operation = store.revalidate_source

        def observed_revalidation(*args, **kwargs):
            return interrupt_after_success(real_operation(*args, **kwargs))

        monkeypatch.setattr(store, "revalidate_source", observed_revalidation)
    else:
        real_operation = store.validate_sealed_artifact

        def observed_sealing(*args, **kwargs):
            return interrupt_after_success(real_operation(*args, **kwargs))

        monkeypatch.setattr(store, "validate_sealed_artifact", observed_sealing)

    try:
        owner.capture((request,))
    except KeyboardInterrupt as exc:
        assert exc is primary
        assert get_artifact_recovery_owner(exc) is None
    else:
        raise AssertionError("successful-operation handoff interruption was swallowed")
    assert boundary_returns == 1 and issued == 0
    assert owner.cleanup_debts() == ()
    assert not list(artifact_root.iterdir())
    assert owner.close().accepted
