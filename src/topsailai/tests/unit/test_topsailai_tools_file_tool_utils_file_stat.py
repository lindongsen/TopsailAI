"""Unit tests for documented file-stat tool functions."""

import pytest

from topsailai.tools.file_tool_utils.file_stat import get_file_size


def test_get_file_size_returns_exact_byte_count(tmp_path):
    """get_file_size reports bytes rather than decoded character count."""
    target = tmp_path / "payload.bin"
    target.write_bytes(b"\x00\xffabc")

    assert get_file_size(str(target)) == 5


def test_get_file_size_propagates_missing_file_error(tmp_path):
    """get_file_size preserves the operating-system missing-file exception."""
    with pytest.raises(FileNotFoundError):
        get_file_size(str(tmp_path / "missing.bin"))
