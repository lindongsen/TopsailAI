"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Purpose: Unit tests for per-model cumulative statistics storage

  Features:
  - Filesystem-safe model slug with collision resistance
  - Cumulative merge of framed deltas into one document per model
  - Advisory-lock serialization across processes
  - Retention by age without touching the active document
  - Best-effort failure isolation and malformed input rejection
"""

import json
import os
import time
from pathlib import Path

import pytest

from topsailai.workspace import model_stats_writer as storage
from topsailai.workspace.model_stats_writer import (
    DOCUMENT_SUFFIX,
    ModelStatsWriter,
    model_slug,
    model_stats_path,
    sweep,
)

FIELDS = {
    "turn_count": 1,
    "tool_call_count": 3,
    "tool_error_count": 1,
    "llm_request_count": 4,
    "llm_request_failure_count": 0,
    "tool_duration_ms_sum": 150,
    "llm_request_duration_ms_sum": 800,
    "prompt_tokens": 100,
    "completion_tokens": 20,
    "cached_tokens": 50,
    "first_byte_sum_ms": 900,
    "first_byte_count": 2,
}


def _line(**overrides):
    """Build one framed delta payload with optional field overrides."""
    payload = dict(FIELDS)
    payload.update(overrides)
    return (json.dumps(payload) + "\n").encode("utf-8")


@pytest.fixture(name="diagnostics")
def fixture_diagnostics():
    """Collect emitted diagnostic categories for assertions."""
    return []


@pytest.fixture(name="writer")
def fixture_writer(tmp_path, diagnostics):
    """Provide a writer bound to an isolated absolute directory."""
    return ModelStatsWriter(
        "Kimi-K2.5",
        diagnostic=lambda category, name: diagnostics.append(category) or True,
        directory=tmp_path,
    )


def test_slug_is_filesystem_safe_and_readable():
    """Keep readable characters while replacing unsafe ones."""
    assert model_slug("Kimi-K2.5").startswith("Kimi-K2.5.")
    assert model_slug("org/model:beta").startswith("org_model_beta.")
    assert "/" not in model_slug("org/model:beta")
    assert ":" not in model_slug("org/model:beta")


def test_slug_handles_empty_and_unicode():
    """Fall back to a stable placeholder for unusable names."""
    assert model_slug("") == "unknown"
    assert model_slug(None) == "unknown"
    assert model_slug("   ") == "unknown"
    slug = model_slug("模型A")
    assert "/" not in slug and slug.endswith(slug[-8:])


def test_slug_distinguishes_names_that_clean_identically():
    """Append a digest so sanitization cannot merge two distinct models."""
    assert model_slug("a/b") != model_slug("a:b")
    assert model_slug("a/b").split(".")[0] == model_slug("a:b").split(".")[0]


def test_slug_is_bounded():
    """Bound the readable prefix so the filename stays short."""
    slug = model_slug("x" * 200)
    assert len(slug.split(".")[0]) <= storage.SLUG_MAX


def test_path_requires_absolute_directory(tmp_path):
    """Reject a relative directory instead of resolving it implicitly."""
    assert model_stats_path("m", directory=tmp_path).name.endswith(DOCUMENT_SUFFIX)
    with pytest.raises(ValueError):
        model_stats_path("m", directory="relative")


def test_path_has_no_process_segment(tmp_path):
    """One model owns exactly one document regardless of process."""
    name = model_stats_path("Kimi-K2.5", directory=tmp_path).name
    assert str(os.getpid()) not in name


def test_append_creates_cumulative_document(writer):
    """Create the document with the first delta's totals."""
    assert writer.append(_line()).ok is True
    document = json.loads(writer.path.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    assert document["model_name"] == "Kimi-K2.5"
    for name, value in FIELDS.items():
        assert document[name] == value


def test_append_accumulates_across_calls(writer):
    """Add each delta to the existing totals instead of appending a record."""
    writer.append(_line())
    writer.append(_line())
    writer.append(_line())
    document = json.loads(writer.path.read_text(encoding="utf-8"))
    assert document["turn_count"] == 3
    assert document["prompt_tokens"] == 300
    assert document["first_byte_count"] == 6


def test_document_is_single_line_json(writer):
    """Store one document, not a growing line-per-attempt log."""
    writer.append(_line())
    writer.append(_line())
    text = writer.path.read_text(encoding="utf-8")
    assert text.count("\n") == 1
    assert text.endswith("\n")


def test_first_seen_is_preserved_and_last_updated_advances(writer):
    """Keep the original first_seen while refreshing last_updated."""
    writer.append(_line())
    first = json.loads(writer.path.read_text(encoding="utf-8"))
    time.sleep(0.01)
    writer.append(_line())
    second = json.loads(writer.path.read_text(encoding="utf-8"))
    assert second["first_seen"] == first["first_seen"]
    assert second["last_updated"] >= first["last_updated"]


def test_negative_and_non_integer_values_contribute_zero(writer):
    """Reject invalid totals rather than corrupting the accumulator."""
    writer.append(_line(prompt_tokens=-5, completion_tokens="9", cached_tokens=None))
    document = json.loads(writer.path.read_text(encoding="utf-8"))
    assert document["prompt_tokens"] == 0
    assert document["completion_tokens"] == 0
    assert document["cached_tokens"] == 0


def test_missing_fields_contribute_zero(writer):
    """Treat an absent field as no contribution."""
    writer.append((json.dumps({"turn_count": 1}) + "\n").encode("utf-8"))
    document = json.loads(writer.path.read_text(encoding="utf-8"))
    assert document["turn_count"] == 1
    assert document["prompt_tokens"] == 0


def test_malformed_input_is_rejected_without_mutation(writer):
    """Reject unframed input before any filesystem mutation."""
    assert writer.append(b"not json\n").ok is False
    assert writer.append(b"no newline").ok is False
    assert writer.append(b"a\nb\n").ok is False
    assert writer.append(b"") .ok is False
    assert not writer.path.exists()


def test_non_object_json_is_rejected(writer, diagnostics):
    """Reject a JSON array because the document must be an object."""
    assert writer.append(b"[1,2]\n").ok is False
    assert "storage_failure" in diagnostics
    assert not writer.path.exists()


def test_corrupt_document_is_replaced_by_valid_totals(writer, diagnostics):
    """Recover from an unreadable document instead of failing forever."""
    writer.path.parent.mkdir(parents=True, exist_ok=True)
    writer.path.write_text("{broken", encoding="utf-8")
    assert writer.append(_line()).ok is True
    document = json.loads(writer.path.read_text(encoding="utf-8"))
    assert document["turn_count"] == 1
    assert "invalid_document" in diagnostics


def test_foreign_process_is_rejected(writer):
    """Refuse to write from a process that does not own the writer."""
    writer.pid = os.getpid() + 1
    assert writer.append(_line()).ok is False


def test_lock_file_is_retained_for_stable_flock(writer):
    """Keep the lock inode so contenders always lock the same file."""
    writer.append(_line())
    assert writer.lock_path.exists()


def test_no_temporary_residue_after_write(writer):
    """Leave no partial temporary file behind."""
    writer.append(_line())
    assert not list(writer.path.parent.glob("*.tmp"))


def test_distinct_models_use_distinct_documents(tmp_path, diagnostics):
    """Isolate totals per model name."""
    diagnostic = lambda category, name: diagnostics.append(category) or True
    first = ModelStatsWriter("model-a", diagnostic=diagnostic, directory=tmp_path)
    second = ModelStatsWriter("model-b", diagnostic=diagnostic, directory=tmp_path)
    first.append(_line())
    second.append(_line(prompt_tokens=7))
    assert first.path != second.path
    assert json.loads(first.path.read_text())["prompt_tokens"] == 100
    assert json.loads(second.path.read_text())["prompt_tokens"] == 7


def test_sweep_deletes_expired_documents(tmp_path, diagnostics):
    """Remove documents older than the retention window."""
    diagnostic = lambda category, name: diagnostics.append(category) or True
    old = tmp_path / f"old{DOCUMENT_SUFFIX}"
    old.write_text("{}", encoding="utf-8")
    stale = time.time() - 40 * 86400
    os.utime(old, (stale, stale))
    assert sweep(tmp_path, 30, diagnostic) == 1
    assert not old.exists()
    assert "delete_attempt" in diagnostics and "deleted" in diagnostics


def test_sweep_keeps_recent_documents(tmp_path, diagnostics):
    """Retain documents inside the retention window."""
    diagnostic = lambda category, name: diagnostics.append(category) or True
    fresh = tmp_path / f"fresh{DOCUMENT_SUFFIX}"
    fresh.write_text("{}", encoding="utf-8")
    assert sweep(tmp_path, 30, diagnostic) == 0
    assert fresh.exists()


def test_sweep_never_deletes_the_active_document(tmp_path, diagnostics):
    """Protect the document currently being written even when it looks old."""
    diagnostic = lambda category, name: diagnostics.append(category) or True
    active = tmp_path / f"active{DOCUMENT_SUFFIX}"
    active.write_text("{}", encoding="utf-8")
    stale = time.time() - 40 * 86400
    os.utime(active, (stale, stale))
    assert sweep(tmp_path, 30, diagnostic, active) == 0
    assert active.exists()


def test_sweep_ignores_unrelated_files(tmp_path, diagnostics):
    """Delete only model documents, never neighbouring files."""
    diagnostic = lambda category, name: diagnostics.append(category) or True
    other = tmp_path / "keep.jsonl"
    other.write_text("{}", encoding="utf-8")
    stale = time.time() - 40 * 86400
    os.utime(other, (stale, stale))
    assert sweep(tmp_path, 30, diagnostic) == 0
    assert other.exists()


def test_sweep_disabled_by_zero_retention(tmp_path, diagnostics):
    """Disable age-based deletion when retention is zero."""
    diagnostic = lambda category, name: diagnostics.append(category) or True
    old = tmp_path / f"old{DOCUMENT_SUFFIX}"
    old.write_text("{}", encoding="utf-8")
    stale = time.time() - 400 * 86400
    os.utime(old, (stale, stale))
    assert sweep(tmp_path, 0, diagnostic) == 0
    assert old.exists()


def test_sweep_runs_once_per_process(writer, monkeypatch):
    """Bound retention work to one attempt per process."""
    calls = []
    monkeypatch.setattr(storage, "_swept", False)
    monkeypatch.setattr(
        storage, "sweep", lambda *a, **k: calls.append(1) or 0,
    )
    writer.append(_line())
    writer.append(_line())
    assert len(calls) == 1


def test_sweep_failure_does_not_fail_the_write(writer, monkeypatch):
    """Keep the write successful when retention raises."""
    monkeypatch.setattr(storage, "_swept", False)

    def explode(*args, **kwargs):
        raise OSError("sweep failed")

    monkeypatch.setattr(storage, "sweep", explode)
    assert writer.append(_line()).ok is True
    assert json.loads(writer.path.read_text())["turn_count"] == 1


def test_merge_preserves_unknown_existing_fields(writer):
    """Keep forward-compatible fields written by a newer version."""
    writer.path.parent.mkdir(parents=True, exist_ok=True)
    writer.path.write_text(
        json.dumps({"schema_version": 1, "future_field": "keep", "turn_count": 5}),
        encoding="utf-8",
    )
    writer.append(_line())
    document = json.loads(writer.path.read_text(encoding="utf-8"))
    assert document["future_field"] == "keep"
    assert document["turn_count"] == 6
