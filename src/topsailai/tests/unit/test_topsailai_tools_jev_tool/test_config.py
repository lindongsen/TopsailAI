"""Tests for JEV environment configuration."""

import pytest

from topsailai.tools.jev_tool_utils.config import JevConfigError, load_config


@pytest.fixture(autouse=True)
def clear_jev_env(monkeypatch):
    """Clear JEV variables before every test."""
    for name in (
        "TOPSAILAI_JEV_BASE_URL", "TOPSAILAI_JEV_API_KEY", "TOPSAILAI_JEV_MODEL",
        "TOPSAILAI_JEV_TIMEOUT_SECONDS", "TOPSAILAI_JEV_MAX_RETRIES",
        "TOPSAILAI_JEV_MAX_CONTEXT_MESSAGES", "TOPSAILAI_JEV_MAX_CONTEXT_CHARS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_loads_http_and_defaults(monkeypatch):
    """HTTP origins remain HTTP and defaults are applied."""
    monkeypatch.setenv("TOPSAILAI_JEV_BASE_URL", "http://example.test:8080")
    monkeypatch.setenv("TOPSAILAI_JEV_API_KEY", "secret")
    config = load_config()
    assert config.endpoint == "http://example.test:8080/v1/systemone"
    assert config.model == "jev-latest"
    assert config.timeout_seconds == 10
    assert config.max_retries == 1


def test_loads_https_path_without_duplicate_endpoint(monkeypatch):
    """HTTPS and an existing endpoint path are preserved."""
    monkeypatch.setenv("TOPSAILAI_JEV_BASE_URL", "https://example.test/v1/systemone")
    monkeypatch.setenv("TOPSAILAI_JEV_API_KEY", "secret")
    assert load_config().endpoint == "https://example.test/v1/systemone"

@pytest.mark.parametrize("url", ["ftp://example.test", "example.test", "http://u:p@example.test", "http://example.test?q=1"])
def test_rejects_invalid_origins(monkeypatch, url):
    """Only credential-free HTTP(S) origins are accepted."""
    monkeypatch.setenv("TOPSAILAI_JEV_BASE_URL", url)
    monkeypatch.setenv("TOPSAILAI_JEV_API_KEY", "secret")
    with pytest.raises(JevConfigError):
        load_config()

@pytest.mark.parametrize("name,value", [
    ("TOPSAILAI_JEV_TIMEOUT_SECONDS", "nan"),
    ("TOPSAILAI_JEV_TIMEOUT_SECONDS", "0"),
    ("TOPSAILAI_JEV_MAX_RETRIES", "-1"),
    ("TOPSAILAI_JEV_MAX_CONTEXT_MESSAGES", "0"),
    ("TOPSAILAI_JEV_MAX_CONTEXT_CHARS", "bad"),
])
def test_rejects_invalid_numeric_configuration(monkeypatch, name, value):
    """Invalid bounds fail closed."""
    monkeypatch.setenv("TOPSAILAI_JEV_BASE_URL", "https://example.test")
    monkeypatch.setenv("TOPSAILAI_JEV_API_KEY", "secret")
    monkeypatch.setenv(name, value)
    with pytest.raises(JevConfigError):
        load_config()


def test_requires_url_and_key(monkeypatch):
    """Missing trusted endpoint or credential fails closed."""
    with pytest.raises(JevConfigError) as error:
        load_config()
    assert error.value.reason == "missing_topsailai_jev_base_url"
    monkeypatch.setenv("TOPSAILAI_JEV_BASE_URL", "https://example.test")
    with pytest.raises(JevConfigError) as error:
        load_config()
    assert error.value.reason == "missing_topsailai_jev_api_key"


def test_loads_ipv6_custom_model_and_numeric_values(monkeypatch):
    """IPv6 origins and valid explicit numeric settings are normalized."""
    monkeypatch.setenv("TOPSAILAI_JEV_BASE_URL", "https://[::1]:8443/api/")
    monkeypatch.setenv("TOPSAILAI_JEV_API_KEY", "secret")
    monkeypatch.setenv("TOPSAILAI_JEV_MODEL", "custom")
    monkeypatch.setenv("TOPSAILAI_JEV_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("TOPSAILAI_JEV_MAX_RETRIES", "0")
    monkeypatch.setenv("TOPSAILAI_JEV_MAX_CONTEXT_MESSAGES", "2")
    monkeypatch.setenv("TOPSAILAI_JEV_MAX_CONTEXT_CHARS", "128")
    loaded = load_config()
    assert loaded.endpoint == "https://[::1]:8443/api/v1/systemone"
    assert loaded.model == "custom"
    assert loaded.timeout_seconds == 2.5
    assert loaded.max_retries == 0
    assert loaded.max_context_messages == 2
    assert loaded.max_context_chars == 128


@pytest.mark.parametrize("url", ["http://example.test#fragment", "http://[::1", "http://example.test:bad"])
def test_rejects_malformed_url_components(monkeypatch, url):
    """Malformed fragments, brackets, and ports fail closed."""
    monkeypatch.setenv("TOPSAILAI_JEV_BASE_URL", url)
    monkeypatch.setenv("TOPSAILAI_JEV_API_KEY", "secret")
    with pytest.raises(JevConfigError):
        load_config()


def test_rejects_empty_model(monkeypatch):
    """An explicitly empty model is invalid configuration."""
    monkeypatch.setenv("TOPSAILAI_JEV_BASE_URL", "https://example.test")
    monkeypatch.setenv("TOPSAILAI_JEV_API_KEY", "secret")
    monkeypatch.setenv("TOPSAILAI_JEV_MODEL", "   ")
    with pytest.raises(JevConfigError) as error:
        load_config()
    assert error.value.reason == "invalid_topsailai_jev_model"
