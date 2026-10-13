"""Resource-free immutable cleanup profile selection. Author: DawsonLin."""

from topsailai.hooks.process_state import WorkerResult


class CleanupBackendProfileMixin:
    """Select once without granting operational custodian cleanup authority."""

    def _initialize_cleanup_profile(self, profile: str) -> None:
        """Reject reinitialization before any existing backend state can be reset."""
        if "_cleanup_profile" in self.__dict__:
            raise RuntimeError("cleanup_profile_already_initialized")
        if type(profile) is not str or profile not in ("legacy", "custodian_v1"):
            raise ValueError("invalid cleanup_profile")
        object.__setattr__(self, "_cleanup_profile", profile)

    @property
    def cleanup_profile(self) -> str:
        """Expose the selected mode without an uninitialized legacy fallback."""
        try:
            return object.__getattribute__(self, "_cleanup_profile")
        except AttributeError:
            raise RuntimeError("cleanup_profile_not_ready") from None

    def __setattr__(self, name, value) -> None:
        """Protect selection while preserving ordinary mutable backend state."""
        if name in ("cleanup_profile", "_cleanup_profile"):
            raise AttributeError("cleanup_profile is read-only")
        super().__setattr__(name, value)

    def __delattr__(self, name) -> None:
        """Prevent removing selection and subsequently initializing a new mode."""
        if name in ("cleanup_profile", "_cleanup_profile"):
            raise AttributeError("cleanup_profile is read-only")
        super().__delattr__(name)

    def _profile_rejection(self) -> WorkerResult | None:
        """Reject only this preacquisition invocation, never attest to record settlement."""
        if self.cleanup_profile == "legacy":
            return None
        return WorkerResult("unsupported_backend", error_category="cleanup_profile_not_ready")

    def _require_legacy_cleanup_profile(self) -> None:
        """Reject unsupported storage and legacy debt authority before observation."""
        if self.cleanup_profile != "legacy":
            raise RuntimeError("cleanup_profile_not_ready")
