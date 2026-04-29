"""Tests for ctxm_backup_file in topsailai/utils/file_tool.py."""

import os
import pytest
from topsailai.utils.file_tool import ctxm_backup_file


def test_source_not_exist_yields_none():
    """When source file does not exist, yield None and create no backups."""
    nonexistent = "/tmp/nonexistent_file_for_backup_test.xyz"
    assert not os.path.exists(nonexistent)
    with ctxm_backup_file(nonexistent) as bak:
        assert bak is None
    assert not os.path.exists(nonexistent)


def test_single_backup_created(temp_file):
    """First backup: .bak0 is created, source is unchanged."""
    _assert_no_backups(temp_file)
    with ctxm_backup_file(temp_file) as bak:
        assert bak == f"{temp_file}.bak0"
        assert os.path.exists(bak)
        with open(bak, encoding="utf-8") as f:
            assert f.read() == "original content"
    assert os.path.exists(temp_file)
    with open(temp_file, encoding="utf-8") as f:
        assert f.read() == "original content"


def test_backup_chain_rotation(temp_file):
    """Multiple backups shift through .bak0..bak9; oldest .bak9 is dropped."""
    for i in range(11):
        with ctxm_backup_file(temp_file) as bak:
            assert bak == f"{temp_file}.bak0"
            # Write i into the source so each backup is unique.
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(str(i))

    for i in range(10):
        path = f"{temp_file}.bak{i}"
        assert os.path.exists(path), f"missing {path}"
        with open(path, encoding="utf-8") as f:
            content = f.read()
            # bak0 holds latest backup (9), bak9 holds oldest remaining (0).
            assert content == str(9 - i), f"{path} expected {9 - i}, got {content}"

    assert not os.path.exists(f"{temp_file}.bak10")


def test_backup_limit_of_ten(temp_file):
    """After 10 backups, no .bak10 or higher should exist."""
    for _ in range(15):
        with ctxm_backup_file(temp_file) as bak:
            with open(temp_file, "a", encoding="utf-8") as f:
                f.write("x")
    for i in range(10):
        assert os.path.exists(f"{temp_file}.bak{i}")
    assert not os.path.exists(f"{temp_file}.bak10")


def test_source_preserved_during_backup(temp_file):
    """Source file content and mtime must not be altered by the backup."""
    original_stat = os.stat(temp_file)
    original_mtime = original_stat.st_mtime
    with ctxm_backup_file(temp_file):
        pass
    new_stat = os.stat(temp_file)
    with open(temp_file, encoding="utf-8") as f:
        assert f.read() == "original content"
    assert new_stat.st_mtime == original_mtime


def test_file_with_dot_in_name(tmp_path):
    """Backup works for files whose names contain dots."""
    f = tmp_path / "archive.tar.gz"
    f.write_text("compressed stuff")
    fp = str(f)
    with ctxm_backup_file(fp) as bak:
        assert bak == f"{fp}.bak0"
        with open(bak, encoding="utf-8") as bf:
            assert bf.read() == "compressed stuff"


@pytest.fixture
def temp_file(tmp_path):
    """Yield a temporary file path and clean up afterward."""
    f = tmp_path / "test_file.txt"
    f.write_text("original content")
    yield str(f)
    # pytest tmp_path cleanup handles the directory


def _backup_paths(file_path):
    """Return list of .bakN paths for file_path, N = 0..9."""
    return [f"{file_path}.bak{i}" for i in range(10)]


def _assert_no_backups(file_path):
    """Assert that none of the .bak0..bak9 files exist."""
    for p in _backup_paths(file_path):
        assert not os.path.exists(p), f"unexpected backup exists: {p}"
