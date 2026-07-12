import json
import time

from topsailai.events.collector import EventCollector
from topsailai.events.config import EventConfig


def test_collector_records_and_flushes(file_config):
    collector = EventCollector(config=file_config)
    collector.record("tool_call.start", {"tool": "x"})
    collector.flush()

    with open(file_config.file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "tool_call.start"
    collector.close()


def test_collector_periodic_flush(file_config):
    collector = EventCollector(config=file_config)
    collector.start()
    collector.record("a", {})
    time.sleep(file_config.flush_interval_ms / 1000.0 * 3)

    with open(file_config.file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1
    collector.close()


def test_collector_disabled_no_file(disabled_config, tmp_path):
    config = disabled_config
    config.file_path = str(tmp_path / "should-not-exist.events")
    collector = EventCollector(config=config)
    collector.record("x", {})
    collector.flush()
    collector.close()

    assert not tmp_path.joinpath("should-not-exist.events").exists()


def test_collector_backend_failure_keeps_events(file_config, monkeypatch):
    collector = EventCollector(config=file_config)
    collector.record("a", {})
    # Force backend to fail
    original_write = collector._backend.write
    collector._backend.write = lambda events: False
    collector.flush()
    assert len(collector._buffer) == 1

    # Restore and flush again
    collector._backend.write = original_write
    collector.flush()
    assert len(collector._buffer) == 0
    collector.close()


def test_collector_close_stops_flusher(file_config):
    collector = EventCollector(config=file_config)
    collector.start()
    collector.close()
    assert collector._flusher._stop_event.is_set()


def test_collector_unknown_backend_falls_back_to_file(monkeypatch, tmp_path):
    path = str(tmp_path / "fallback.events")
    config = EventConfig(
        enabled=True,
        buffer_size=10,
        flush_interval_ms=50,
        backend="unknown_backend",
        file_path=path,
    )
    collector = EventCollector(config=config)
    collector.record("a", {})
    collector.flush()
    collector.close()

    with open(path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "a"


def test_collector_record_resolves_session_id_from_env(file_config, monkeypatch):
    """When session_id is not provided, it is resolved from environment variables."""
    monkeypatch.setenv("TOPSAILAI_SESSION_ID", "session-from-env")
    collector = EventCollector(config=file_config)
    collector.record("a", {})
    collector.flush()
    collector.close()

    with open(file_config.file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["session_id"] == "session-from-env"


def test_collector_record_preserves_explicit_session_id(file_config):
    """Explicitly provided session_id values are preserved, including empty string."""
    collector = EventCollector(config=file_config)
    collector.record("a", {}, session_id="explicit-session")
    collector.record("b", {}, session_id="")
    collector.flush()
    collector.close()

    with open(file_config.file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["session_id"] == "explicit-session"
    assert json.loads(lines[1])["session_id"] == ""


def test_collector_record_session_id_follows_env_changes(file_config, monkeypatch):
    """Session ID resolution reflects the current environment at record time."""
    monkeypatch.setenv("SESSION_ID", "first-session")
    collector = EventCollector(config=file_config)
    collector.record("a", {})

    monkeypatch.setenv("SESSION_ID", "second-session")
    collector.record("b", {})

    collector.flush()
    collector.close()

    with open(file_config.file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 2
    assert json.loads(lines[0])["session_id"] == "first-session"
    assert json.loads(lines[1])["session_id"] == "second-session"


def test_collector_record_session_id_none_when_env_unset(file_config, monkeypatch):
    """When no session env var is set and none is provided, session_id is null."""
    monkeypatch.delenv("TOPSAILAI_SESSION_ID", raising=False)
    monkeypatch.delenv("SESSION_ID", raising=False)
    collector = EventCollector(config=file_config)
    collector.record("a", {})
    collector.flush()
    collector.close()

    with open(file_config.file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["session_id"] is None
