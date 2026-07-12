"""
Unit tests for topsailai.events.config.
"""

from topsailai.events.config import EventConfig, get_event_config


def test_default_config():
    config = EventConfig()
    assert config.enabled is True
    assert config.buffer_size == 1000
    assert config.flush_interval_ms == 100
    assert config.backend == "file"
    assert config.file_path is None


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("TOPSAILAI_EVENTS_ENABLED", "0")
    monkeypatch.setenv("TOPSAILAI_EVENTS_BUFFER_SIZE", "500")
    monkeypatch.setenv("TOPSAILAI_EVENTS_FLUSH_INTERVAL_MS", "250")
    monkeypatch.setenv("TOPSAILAI_EVENTS_BACKEND", "webhook")
    monkeypatch.setenv("TOPSAILAI_EVENTS_FILE_PATH", "/tmp/events.jsonl")

    config = get_event_config()
    assert config.enabled is False
    assert config.buffer_size == 500
    assert config.flush_interval_ms == 250
    assert config.backend == "webhook"
    assert config.file_path == "/tmp/events.jsonl"


def test_config_bool_parsing(monkeypatch):
    for value in ("1", "true", "True", "yes", "on", "enabled"):
        monkeypatch.setenv("TOPSAILAI_EVENTS_ENABLED", value)
        assert get_event_config().enabled is True

    for value in ("0", "false", "", "no"):
        monkeypatch.setenv("TOPSAILAI_EVENTS_ENABLED", value)
        assert get_event_config().enabled is False
