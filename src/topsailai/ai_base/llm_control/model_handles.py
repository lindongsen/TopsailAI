"""Provider-neutral ownership tracking for opaque LLM model handles."""


class LLMModelHandleRegistry:
    """Track opaque model resources and their independently owned handles."""

    def __init__(self, records=None):
        """Initialize the registry with an optional existing record list."""
        self.records = records if records is not None else []

    def register(self, model, handle):
        """Register one model resource and its owned handle in acquisition order."""
        self.records.append((model, handle))

    def snapshot(self):
        """Return the exact handles currently owned by this registry."""
        return tuple(handle for _, handle in self.records)

    def release_handles(self, handles) -> int:
        """Release specified owned handles by identity without touching others."""
        released = 0
        for target_handle in handles:
            for index, (_, owned_handle) in enumerate(self.records):
                if owned_handle is not target_handle:
                    continue
                del self.records[index]
                owned_handle.release()
                released += 1
                break
        return released

    def handles_after(self, snapshot):
        """Return handles acquired after an ownership snapshot."""
        retained_handle_ids = {id(handle) for handle in snapshot}
        return tuple(
            handle
            for _, handle in self.records
            if id(handle) not in retained_handle_ids
        )

    def release_after(self, snapshot) -> int:
        """Release handles acquired after an ownership snapshot."""
        return self.release_handles(self.handles_after(snapshot))

    def find_handle(self, model):
        """Return the most recently registered handle for a model identity."""
        for owned_model, handle in reversed(self.records):
            if owned_model is model:
                return handle
        return None

    def release_model(self, model) -> bool:
        """Release the most recently registered handle for a model identity."""
        handle = self.find_handle(model)
        if handle is None:
            return False
        return self.release_handles((handle,)) == 1

    def release_all(self) -> int:
        """Release every handle currently owned by this registry."""
        return self.release_handles(self.snapshot())


class LLMModelHandleLifecycleMixin:
    """Provide optional provider-neutral lifecycle behavior for owned handles."""

    def _get_llm_model_handles(self):
        """Return lazily initialized ownership records for provider handles."""
        handles = getattr(self, "_llm_model_handles", None)
        if handles is None:
            handles = []
            self._llm_model_handles = handles
        return handles

    def _get_llm_model_handle_registry(self):
        """Return a registry over the authoritative compatibility record list."""
        handles = self._get_llm_model_handles()
        registry = getattr(self, "_llm_model_handle_registry", None)
        if registry is None or registry.records is not handles:
            registry = LLMModelHandleRegistry(handles)
            self._llm_model_handle_registry = registry
        return registry

    def _register_llm_model_handle(self, model, handle):
        """Register one provider-acquired model and its opaque owned handle."""
        self._get_llm_model_handle_registry().register(model, handle)

    def snapshot_llm_model_leases(self):
        """Return exact handles currently leased by this model instance."""
        return self._get_llm_model_handle_registry().snapshot()

    def release_llm_model_leases(self, handles) -> int:
        """Release specified owned handles without touching other leases."""
        return self._get_llm_model_handle_registry().release_handles(handles)

    def release_llm_model_leases_after(self, snapshot) -> int:
        """Release leases acquired after an ownership snapshot."""
        acquired_handles = self._get_llm_model_handle_registry().handles_after(
            snapshot
        )
        return self.release_llm_model_leases(acquired_handles)

    def release_llm_model(self, model) -> bool:
        """Release the newest owned handle associated with a model identity."""
        return self._get_llm_model_handle_registry().release_model(model)

    def release_all_llm_models(self) -> int:
        """Release every provider handle owned by this model instance."""
        return self.release_llm_model_leases(self.snapshot_llm_model_leases())

    def _find_llm_model_handle(self, model):
        """Return the newest owned handle associated with a model identity."""
        return self._get_llm_model_handle_registry().find_handle(model)
