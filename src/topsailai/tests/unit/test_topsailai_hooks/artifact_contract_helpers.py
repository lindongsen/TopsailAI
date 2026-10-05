"""Exact public-contract assertions for U07 artifact capture tests."""

from __future__ import annotations

import dataclasses
import inspect

import topsailai.hooks as public
from topsailai.hooks import ArtifactCaptureOwner, ArtifactCapturePolicy, CapturedArtifact
from topsailai.hooks import artifact_contracts as contracts
from topsailai.hooks import artifact_store as store


_EXPECTED_FIELDS = {
    "ArtifactPythonRuntimeAuthority": ("executable", "content_sha256", "bootstrap"),
    "ArtifactClosureAssertion": ("source_path", "kind", "logical_name", "content_sha256", "runtime_sha256", "deployment_sha256", "closure"),
    "ArtifactCaptureTrust": ("source_roots", "allowed_interpreters", "allow_native_scripts", "closure_assertions", "python_runtime"),
    "ArtifactCaptureRequest": ("source_path", "kind", "logical_name", "script_policy"),
    "ArtifactCapturePolicy": ("timeout_ms", "max_entries", "max_file_bytes", "max_total_bytes"),
    "ArtifactFileIdentity": ("device", "inode", "size", "mtime_ns", "ctime_ns", "mode", "uid", "gid", "links"),
    "ArtifactInterpreterEvidence": ("path", "identity", "content_sha256"),
    "ArtifactValidationEvidence": ("source_root", "source_path", "identity", "interpreter", "runtime_sha256", "deployment_sha256", "checked_uid", "acl_capability_absent"),
    "ArtifactInventoryEntry": ("index", "kind", "logical_name", "relative_path", "size_bytes", "content_sha256", "mode", "validation"),
    "ArtifactCaptureResult": ("accepted", "artifact", "errors", "recovery_owner"),
    "ArtifactDisposeResult": ("accepted", "already_disposed", "cleanup_pending", "errors"),
    "ArtifactCleanupDebt": ("debt_id", "category"),
}
_EXPECTED_DEFAULTS = {
    "ArtifactPythonRuntimeAuthority": {"bootstrap": "cpython-executable-v1"},
    "ArtifactClosureAssertion": {"closure": "single-file-trusted-runtime-v1"},
    "ArtifactCaptureTrust": {
        "allowed_interpreters": (), "allow_native_scripts": False,
        "closure_assertions": (), "python_runtime": None,
    },
    "ArtifactCaptureRequest": {"script_policy": None},
    "ArtifactCapturePolicy": {
        "timeout_ms": 10_000, "max_entries": 128,
        "max_file_bytes": 16_777_216, "max_total_bytes": 67_108_864,
    },
    "ArtifactCaptureResult": {"artifact": None, "errors": (), "recovery_owner": None},
    "ArtifactDisposeResult": {
        "already_disposed": False, "cleanup_pending": False, "errors": (),
    },
}
_EXPECTED_SIGNATURES = {
    "capture": "(self, requests: 'tuple[ArtifactCaptureRequest, ...]', *, policy: 'ArtifactCapturePolicy' = ArtifactCapturePolicy(timeout_ms=10000, max_entries=128, max_file_bytes=16777216, max_total_bytes=67108864), cancellation: 'threading.Event | None' = None, deadline: 'float | None' = None) -> 'ArtifactCaptureResult'",
    "dispose": "(self, artifact: 'CapturedArtifact') -> 'ArtifactDisposeResult'",
    "cleanup_debts": "(self) -> 'tuple[ArtifactCleanupDebt, ...]'",
    "retry_cleanup": "(self, debt_id: 'str') -> 'bool'",
    "close": "(self) -> 'ArtifactDisposeResult'",
    "__enter__": "(self) -> 'ArtifactCaptureOwner'",
    "__exit__": "(self, exc_type: 'type[BaseException] | None', exc: 'BaseException | None', traceback: 'TracebackType | None') -> 'bool'",
}


def assert_artifact_public_contract() -> None:
    """Assert exact artifact records, defaults, signatures, and package exports."""
    for name, fields in _EXPECTED_FIELDS.items():
        record = getattr(contracts, name)
        record_fields = dataclasses.fields(record)
        assert tuple(item.name for item in record_fields) == fields
        assert record.__slots__ == fields and record.__dataclass_params__.frozen
        assert getattr(public, name) is record and name in public.__all__
        defaults = _EXPECTED_DEFAULTS.get(name, {})
        for item in record_fields:
            expected = defaults.get(item.name, dataclasses.MISSING)
            assert item.default is expected or item.default == expected
    assert str(inspect.signature(ArtifactCaptureOwner)) == "(*, artifact_root: 'str', trust: 'ArtifactCaptureTrust') -> 'None'"
    for name, expected in _EXPECTED_SIGNATURES.items():
        assert str(inspect.signature(getattr(ArtifactCaptureOwner, name))) == expected
    assert str(inspect.signature(CapturedArtifact)) == "(issuer: 'object', identity: 'str', entries: 'tuple[ArtifactInventoryEntry, ...]', total_bytes: 'int', directory: 'Path | None') -> 'None'"
    assert str(inspect.signature(store.get_artifact_recovery_owner)) == "(error: 'BaseException') -> 'ArtifactCaptureOwner | None'"
    for name in ("ArtifactCaptureOwner", "CapturedArtifact", "get_artifact_recovery_owner"):
        assert getattr(public, name) is getattr(store, name)
        assert name in public.__all__
