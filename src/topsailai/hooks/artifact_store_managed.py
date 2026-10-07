"""Private construction support for standalone and managed artifact owners."""

from __future__ import annotations

import threading
from pathlib import Path

from topsailai.hooks.artifact_structure import (
    valid_root_spelling,
    validate_capture_trust_structure,
)


class ArtifactCaptureOwnerConstruction:
    """Initialize immutable recovery routing before any capture allocation."""

    def __init__(self, *, artifact_root: str, trust) -> None:
        """Construct the compatible standalone owner mode."""
        self._initialize(artifact_root, trust, None)

    @classmethod
    def _new_managed(cls, *, artifact_root: str, trust, recovery: object):
        """Construct one owner whose physical recovery authority stays private."""
        owner = cls.__new__(cls)
        owner._initialize(artifact_root, trust, recovery)
        return owner

    def _initialize(self, artifact_root: str, trust, recovery: object | None) -> None:
        """Initialize all owner state with an immutable recovery destination."""
        if not valid_root_spelling(artifact_root) or not validate_capture_trust_structure(trust):
            raise ValueError("invalid artifact capture owner")
        self._artifact_root = Path(artifact_root)
        self._trust = trust
        self._lock = threading.RLock()
        self._slots = {}
        self._issued = {}
        self._closed = False
        self._bound_uid = None
        self._root_identity = None
        self._python_fingerprint = None
        self._managed_recovery = recovery
