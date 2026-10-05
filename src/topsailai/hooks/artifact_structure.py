"""Resource-free structural validation for immutable artifact capture."""

from __future__ import annotations

import math
import threading
from pathlib import Path

from topsailai.hooks.artifact_contracts import (
    ArtifactCapturePolicy,
    ArtifactCaptureRequest,
    ArtifactCaptureTrust,
    ArtifactClosureAssertion,
    ArtifactPythonRuntimeAuthority,
)
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy



def validate_capture_call(requests, policy, cancellation, deadline) -> str | None:
    """Validate bounded call values before lock wait or filesystem access."""
    if type(requests) is not tuple:
        return "invalid_artifact_request"
    policy_valid = _valid_policy(policy)
    request_limit = policy.max_entries + 1 if policy_valid else 129
    if not all(validate_request_structure(item) for item in requests[:request_limit]):
        return "invalid_artifact_request"
    if not policy_valid:
        return "invalid_artifact_policy"
    if cancellation is not None and not isinstance(cancellation, threading.Event):
        return "invalid_artifact_cancellation"
    if deadline is not None and (type(deadline) is not float or not math.isfinite(deadline)):
        return "invalid_artifact_deadline"
    return None


def _valid_policy(policy: object) -> bool:
    """Validate an exact bounded capture policy."""
    return type(policy) is ArtifactCapturePolicy and all(
        type(value) is int for value in (
            policy.timeout_ms, policy.max_entries, policy.max_file_bytes, policy.max_total_bytes
        )
    ) and (
        1 <= policy.timeout_ms <= 600_000
        and 1 <= policy.max_entries <= 128
        and 1 <= policy.max_file_bytes <= policy.max_total_bytes <= 67_108_864
    )


def validate_resource_free(requests, policy, trust) -> str | None:
    """Validate duplicate and authority subsets before filesystem admission."""
    if len(requests) > policy.max_entries:
        return "artifact_inventory_limit"
    paths = tuple(item.source_path for item in requests)
    keys = tuple((item.kind, item.logical_name) for item in requests)
    if len(set(paths)) != len(paths) or len(set(keys)) != len(keys):
        return "invalid_artifact_request"
    from topsailai.hooks.artifact_validation import (
        ArtifactValidationError, assertion_for_request,
    )
    for request in requests:
        try:
            assertion_for_request(trust, request)
        except ArtifactValidationError:
            return "unsupported_artifact_closure"
        if request.kind == "script":
            value = request.script_policy
            assert value is not None
            allowed = tuple(Path(item) for item in value.allowed_interpreters)
            if (
                value.platform != "posix"
                or value.native_suffixes
                or any(str(path) != raw for path, raw in zip(allowed, value.allowed_interpreters, strict=True))
                or len(set(allowed)) != len(allowed)
                or any(path not in trust.allowed_interpreters for path in allowed)
            ):
                return "trust_rejected"
    return None


def valid_root_spelling(value: object) -> bool:
    """Validate an explicit normalized absolute root string without I/O."""
    if type(value) is not str or not value or "\x00" in value:
        return False
    try:
        path = Path(value)
        encoded = value.encode("utf-8", errors="strict")
    except (UnicodeEncodeError, ValueError):
        return False
    return (
        path.is_absolute()
        and ".." not in path.parts
        and str(path) == value
        and len(encoded) <= 4096
    )

def validate_capture_trust_structure(trust: object) -> bool:
    """Validate detached host authority without filesystem access."""
    if type(trust) is not ArtifactCaptureTrust:
        return False
    if type(trust.source_roots) is not tuple or not 1 <= len(trust.source_roots) <= 32:
        return False
    if type(trust.allowed_interpreters) is not tuple or len(trust.allowed_interpreters) > 32:
        return False
    if type(trust.allow_native_scripts) is not bool:
        return False
    if type(trust.closure_assertions) is not tuple or len(trust.closure_assertions) > 4096:
        return False
    if trust.python_runtime is not None and type(trust.python_runtime) is not ArtifactPythonRuntimeAuthority:
        return False
    paths = trust.source_roots + trust.allowed_interpreters
    if not all(_valid_path(path) for path in paths) or len(set(paths)) != len(paths):
        return False
    if not all(_valid_assertion(item) for item in trust.closure_assertions):
        return False
    keys = tuple((item.source_path, item.kind, item.logical_name) for item in trust.closure_assertions)
    if len(set(keys)) != len(keys):
        return False
    runtime = trust.python_runtime
    if runtime is not None and (
        not _valid_path(runtime.executable)
        or not _valid_digest(runtime.content_sha256)
        or type(runtime.bootstrap) is not str
        or runtime.bootstrap != "cpython-executable-v1"
    ):
        return False
    return True


def validate_request_structure(request: object) -> bool:
    """Validate one request without dependent operations or filesystem access."""
    if type(request) is not ArtifactCaptureRequest:
        return False
    if (
        not _valid_path(request.source_path)
        or type(request.kind) is not str
        or request.kind not in {"python_source", "python_extension", "script"}
        or type(request.logical_name) is not str
    ):
        return False
    try:
        encoded = request.logical_name.encode("utf-8", errors="strict")
        path_size = len(str(request.source_path).encode("utf-8", errors="strict"))
    except (UnicodeEncodeError, ValueError):
        return False
    if not encoded or len(encoded) > 255 or path_size > 4096:
        return False
    if request.kind == "script":
        policy = request.script_policy
        if type(policy) is not ExecutablePlatformPolicy:
            return False
        if (
            type(policy.platform) is not str
            or type(policy.allowed_interpreters) is not tuple
            or type(policy.native_suffixes) is not tuple
            or any(type(value) is not str for value in policy.allowed_interpreters)
            or any(type(value) is not str for value in policy.native_suffixes)
        ):
            return False
        return request.logical_name == request.source_path.name
    return (
        request.script_policy is None
        and request.logical_name != "__init__"
        and request.logical_name.isidentifier()
    )


def _valid_assertion(value: object) -> bool:
    """Validate one closure assertion structurally."""
    if type(value) is not ArtifactClosureAssertion or not _valid_path(value.source_path):
        return False
    if type(value.kind) is not str or value.kind not in {
        "python_source", "python_extension", "script"
    } or type(value.logical_name) is not str:
        return False
    try:
        logical_name = value.logical_name.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    valid_name = (
        value.logical_name == value.source_path.name
        if value.kind == "script"
        else value.logical_name != "__init__" and value.logical_name.isidentifier()
    )
    return (
        bool(logical_name)
        and len(logical_name) <= 255
        and valid_name
        and _valid_digest(value.content_sha256)
        and _valid_digest(value.runtime_sha256)
        and _valid_digest(value.deployment_sha256)
        and type(value.closure) is str
        and value.closure == "single-file-trusted-runtime-v1"
    )


def _valid_path(value: object) -> bool:
    """Validate one lexical concrete absolute path."""
    if not isinstance(value, Path) or not value.is_absolute() or ".." in value.parts:
        return False
    try:
        encoded = str(value).encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return False
    return b"\x00" not in encoded and len(encoded) <= 4096


def _valid_digest(value: object) -> bool:
    """Validate one lowercase SHA-256 hexadecimal value."""
    return type(value) is str and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )
