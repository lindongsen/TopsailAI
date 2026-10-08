"""Single adapter from configured host trust to U07 capture authority."""

from __future__ import annotations

from topsailai.hooks.artifact_contracts import ArtifactCaptureTrust
from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy


def artifact_capture_trust(policy: ConfiguredTrustPolicy) -> ArtifactCaptureTrust:
    """Map validated Runtime-owned policy to the existing capture authority."""
    if type(policy) is not ConfiguredTrustPolicy:
        raise ValueError("invalid configured trust policy")
    return ArtifactCaptureTrust(
        source_roots=tuple(policy.source_roots),
        allowed_interpreters=tuple(policy.allowed_interpreters),
        allow_native_scripts=policy.allow_native_scripts,
        closure_assertions=tuple(policy.closure_assertions),
        python_runtime=policy.python_runtime,
    )
