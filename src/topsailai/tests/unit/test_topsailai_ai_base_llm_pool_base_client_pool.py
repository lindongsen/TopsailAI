"""Unit tests for the provider-neutral reusable client pool."""

from dataclasses import dataclass

import pytest

from topsailai.ai_base.llm_pool.base_client_pool import (
    BaseClientPool,
    ClientPoolHandle,
)
from topsailai.ai_base.llm_pool.openai_client_pool import OpenAIClientPool


@dataclass(frozen=True)
class ExampleClientConfig:
    """Describe one non-OpenAI provider client for pool tests."""

    endpoint: str
    credential: str

    def to_key(self):
        """Return a stable test key without exposing the credential."""
        return self.endpoint, len(self.credential)

    def constructor_kwargs(self):
        """Return constructor arguments owned by the example provider."""
        return {"endpoint": self.endpoint, "credential": self.credential}


class ExampleClient:
    """Record lifecycle operations for a non-OpenAI provider client."""

    def __init__(self, endpoint, credential):
        """Capture provider-owned constructor arguments."""
        self.endpoint = endpoint
        self.credential = credential
        self.close_count = 0

    def close(self):
        """Record one provider client close operation."""
        self.close_count += 1


class ExampleClientPool(BaseClientPool):
    """Use the common lifecycle for an unrelated example provider."""

    pool_name = "example client"



def test_base_pool_reuses_provider_config_and_retires_generations():
    """A provider subclass reuses, invalidates, and closes clients generically."""
    created = []

    def create_client(**kwargs):
        """Construct and retain one example provider client."""
        client = ExampleClient(**kwargs)
        created.append(client)
        return client

    pool = ExampleClientPool(client_factory=create_client)
    config = ExampleClientConfig("https://example.invalid", "credential")

    first = pool.acquire(config)
    second = pool.get_or_create(config)

    assert isinstance(first, ClientPoolHandle)
    assert first.client is second.client
    assert len(created) == 1
    assert pool.invalidate(config) is True

    replacement = pool.acquire(config)
    assert replacement.client is not first.client
    assert replacement.generation == first.generation + 1
    assert first.client.close_count == 0

    first.release()
    second.release()
    assert first.client.close_count == 1

    replacement.release()
    assert pool.close_all() == 1
    assert replacement.client.close_count == 1



def test_base_pool_requires_factory_and_positive_capacity():
    """Invalid provider pool construction fails before any mutable state exists."""
    with pytest.raises(ValueError, match="client_factory is required"):
        BaseClientPool()
    with pytest.raises(ValueError, match="capacity must be at least 1"):
        BaseClientPool(capacity=0, client_factory=ExampleClient)



def test_openai_pool_uses_provider_neutral_parent():
    """The OpenAI implementation delegates lifecycle management to the base pool."""
    assert issubclass(OpenAIClientPool, BaseClientPool)
