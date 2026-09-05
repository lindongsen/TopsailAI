"""Lifecycle tests for process-global LLM SDK client sharing."""

from unittest.mock import MagicMock, patch

import pytest

from topsailai.ai_base.llm_control.base_class import LLMModelBase


class LeaseTrackingModel(LLMModelBase):
    """Minimal provider model that records exact lease ownership operations."""

    def __init__(self):
        """Initialize lifecycle state without starting unrelated workers."""
        self._leases = []
        self.released = []
        self.invalidated = []
        self.acquire_count = 0
        self.fail_at_acquire = None
        self.model = self.get_llm_model()
        self.model_config = {"api_key": "", "api_base": ""}
        self.models = []
        self.state_visualizer = MagicMock()
        self.tokenStat = MagicMock(flag_running=True)

    def get_model_name(self, default=""):
        """Return a stable model name for the abstract provider contract."""
        return "test-model"

    def get_llm_model(self, api_key=None, api_base=None):
        """Acquire one distinguishable resource and provider lease."""
        self.acquire_count += 1
        if self.acquire_count == self.fail_at_acquire:
            raise RuntimeError("client construction failed")
        resource = object()
        lease = object()
        self._leases.append((resource, lease))
        return resource

    def snapshot_llm_model_leases(self):
        """Return the exact currently owned leases."""
        return tuple(lease for _, lease in self._leases)

    def release_llm_model_leases(self, handles):
        """Release only exact lease identities requested by the base lifecycle."""
        released = 0
        for target in handles:
            for index, (_, lease) in enumerate(self._leases):
                if lease is not target:
                    continue
                self._leases.pop(index)
                self.released.append(lease)
                released += 1
                break
        return released

    def release_llm_model_leases_after(self, snapshot):
        """Release leases acquired after the supplied snapshot."""
        retained = {id(lease) for lease in snapshot}
        acquired = [
            lease for _, lease in self._leases if id(lease) not in retained
        ]
        return self.release_llm_model_leases(acquired)

    def release_all_llm_models(self):
        """Release every lease owned by this model instance."""
        return self.release_llm_model_leases(self.snapshot_llm_model_leases())

    def invalidate_llm_model(self, chat_model):
        """Record one targeted client-generation invalidation."""
        self.invalidated.append(chat_model)
        return True

    def get_response_message(self, response):
        """Satisfy the provider response contract for this lifecycle test double."""
        return response

    def chat(self, *args, **kwargs):
        """Satisfy the abstract chat contract for this lifecycle test double."""
        return None


def test_close_releases_only_owned_leases_and_is_idempotent():
    """Closing a model releases its leases without a global-pool shutdown."""
    model = LeaseTrackingModel()
    model.get_llm_model("failover-key", "https://failover.test/v1")
    owned_leases = model.snapshot_llm_model_leases()

    model.close()
    model.close()

    assert model.released == list(owned_leases)
    assert model.snapshot_llm_model_leases() == ()
    assert model.state_visualizer.stop.call_count == 2
    assert model.tokenStat.flag_running is False


@patch("topsailai.ai_base.llm_control.base_class.parse_model_settings")
def test_normal_rebuild_reuses_pool_without_invalidation(mock_settings):
    """Ordinary rebuilds replace routes without retiring a shared client."""
    mock_settings.return_value = [
        {"api_key": "route-key", "api_base": "https://route.test/v1"}
    ]
    model = LeaseTrackingModel()
    old_model = model.model
    old_leases = model.snapshot_llm_model_leases()

    result = model.rebuild_llm_models()

    assert model.invalidated == []
    assert model.model is not old_model
    assert result is model.models
    assert len(model.models) == 1
    assert model.released == list(old_leases)
    assert len(model.snapshot_llm_model_leases()) == 2


@patch("topsailai.ai_base.llm_control.base_class.parse_model_settings")
def test_forced_rebuild_invalidates_only_explicit_failed_model(mock_settings):
    """Forced refresh targets the failed resource before acquiring replacements."""
    mock_settings.return_value = []
    model = LeaseTrackingModel()
    failed_model = object()

    model.rebuild_llm_models(force_refresh=True, failed_model=failed_model)

    assert model.invalidated == [failed_model]


@patch("topsailai.ai_base.llm_control.base_class.parse_model_settings")
def test_rebuild_failure_preserves_state_and_releases_temporary_leases(mock_settings):
    """A partial replacement failure leaves the complete old state usable."""
    mock_settings.return_value = [
        {"api_key": "route-key", "api_base": "https://route.test/v1"}
    ]
    model = LeaseTrackingModel()
    old_model = model.model
    old_models = model.models
    old_config = model.model_config
    old_leases = model.snapshot_llm_model_leases()
    model.fail_at_acquire = model.acquire_count + 2

    with pytest.raises(RuntimeError, match="client construction failed"):
        model.rebuild_llm_models()

    assert model.model is old_model
    assert model.models is old_models
    assert model.model_config is old_config
    assert model.snapshot_llm_model_leases() == old_leases
    assert len(model.released) == 1
    assert model.released[0] not in old_leases
