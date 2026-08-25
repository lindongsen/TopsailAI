"""Unit tests for shared memory-home resolution."""

import sys
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(CLI_DIR))

import _memory_home as home


def test_default_uses_configured_memory_home(monkeypatch):
    """Keep the configured memory root when no option is supplied."""
    monkeypatch.setattr(home.story_memory_tool, "WORKSPACE", "/configured/memory")
    assert home.resolve_memory_home(None) == "/configured/memory"


def test_default_falls_back_to_folder_memory(monkeypatch):
    """Use the folder constant when the configured memory root is empty."""
    monkeypatch.setattr(home.story_memory_tool, "WORKSPACE", "")
    monkeypatch.setattr(home, "FOLDER_MEMORY", "/fallback/memory")
    assert home.resolve_memory_home(None) == "/fallback/memory"


def test_absolute_home_appends_memory(tmp_path):
    """Append memory when an absolute TOPSAILAI_HOME has no story folder."""
    assert home.resolve_memory_home(str(tmp_path)) == str(
        tmp_path / "memory"
    )


def test_existing_memory_root_is_preserved(tmp_path):
    """Keep a memory root that directly contains a story directory."""
    (tmp_path / "story").mkdir()
    assert home.resolve_memory_home(str(tmp_path)) == str(tmp_path)


def test_relative_home_uses_original_pwd(tmp_path, monkeypatch):
    """Resolve relative TOPSAILAI_HOMEs from the original process directory."""
    monkeypatch.setenv("TOPSAILAI_PWD", str(tmp_path))
    assert home.resolve_memory_home("project") == str(
        tmp_path / "project" / "memory"
    )


def test_relative_home_falls_back_to_cwd(tmp_path, monkeypatch):
    """Resolve relative TOPSAILAI_HOMEs from cwd without TOPSAILAI_PWD."""
    monkeypatch.delenv("TOPSAILAI_PWD", raising=False)
    monkeypatch.chdir(tmp_path)
    assert home.resolve_memory_home("project") == str(
        tmp_path / "project" / "memory"
    )
