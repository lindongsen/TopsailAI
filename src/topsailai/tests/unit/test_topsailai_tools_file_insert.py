#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Unit tests for file_tool insert_content_to_file operations
'''

import pytest
import sys
import os
import tempfile
import shutil

workspace_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if (workspace_root + "/src") not in sys.path:
    sys.path.insert(0, workspace_root)
    sys.path.insert(0, workspace_root + "/src")
from topsailai.tools.file_tool import insert_content_to_file


class TestFileToolInsertDataToFile:
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def test_file(self, temp_dir):
        """Create a test file path in the temporary directory"""
        return os.path.join(temp_dir, "test.txt")

    def test_insert_content_to_file_after_line(self, test_file):
        """Test inserting data after a specific line"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "Inserted Line", line_num=2, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nInserted Line\nLine 3\n"

    def test_insert_content_to_file_before_line(self, test_file):
        """Test inserting data before a specific line"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "Inserted Line", line_num=3, before_or_after="before")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nInserted Line\nLine 3\n"

    def test_insert_content_to_file_first_line_after(self, test_file):
        """Test inserting data after the first line"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "New Line", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nNew Line\nLine 2\nLine 3\n"

    def test_insert_content_to_file_last_line_after(self, test_file):
        """Test inserting data after the last line"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "New Line", line_num=3, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nLine 3\nNew Line\n"

    def test_insert_content_to_file_empty_file(self, test_file):
        """Test inserting data into an empty file still reports the diff"""
        with open(test_file, 'w') as f:
            f.write("")
        result = insert_content_to_file(test_file, "New Line", line_num=0, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        assert "New Line" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "New Line\n"

    def test_insert_content_to_file_data_without_newline(self, test_file):
        """Test inserting data without trailing newline"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "Inserted", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nInserted\nLine 2\n"

    def test_insert_content_to_file_data_with_newline(self, test_file):
        """Test inserting data that already ends with newline"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "Inserted Line\n", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nInserted Line\nLine 2\n"

    def test_insert_content_to_file_invalid_before_or_after(self, test_file):
        """Test error handling with invalid before_or_after value"""
        with open(test_file, 'w') as f:
            f.write("Line 1\n")
        with pytest.raises(ValueError) as exc_info:
            insert_content_to_file(test_file, "New Line", line_num=1, before_or_after="invalid")
        assert "before_or_after must be 'before' or 'after'" in str(exc_info.value)

    def test_insert_content_to_file_out_of_bounds_line(self, test_file):
        """Test inserting after a line number beyond file length"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "New Line", line_num=100, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nNew Line\n"

    def test_insert_content_to_file_zero_line_number(self, test_file):
        """Test inserting at line 0"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "New Line", line_num=0, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "New Line\nLine 1\nLine 2\n"

    def test_insert_content_to_file_unicode_content(self, test_file):
        """Test inserting Unicode content"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(initial_content)
        unicode_content = "你好世界 🌍"
        result = insert_content_to_file(test_file, unicode_content, line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        expected_content = f"Line 1\n{unicode_content}\nLine 2\n"
        assert content == expected_content

    def test_insert_content_to_file_empty_data(self, test_file):
        """Test inserting empty data"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        # Empty data produces no diff changes
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == initial_content
    def test_insert_content_to_file_large_line_number_before(self, test_file):
        """Test inserting before a line number larger than file"""
        initial_content = "Line 1\nLine 2\nLine 3\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "New Line", line_num=100, before_or_after="before")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Line 1\nLine 2\nLine 3\nNew Line\n"

    def test_insert_content_to_file_single_line_file(self, test_file):
        """Test inserting into a file with a single line"""
        initial_content = "Only Line\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        result = insert_content_to_file(test_file, "New Line", line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        assert content == "Only Line\nNew Line\n"

    def test_insert_content_to_file_special_characters(self, test_file):
        """Test inserting content with special characters"""
        initial_content = "Line 1\nLine 2\n"
        with open(test_file, 'w') as f:
            f.write(initial_content)
        special_content = "Tab:\tNewline:\nBackslash:\\"
        result = insert_content_to_file(test_file, special_content, line_num=1, before_or_after="after")
        assert isinstance(result, str)
        assert "---" in result
        assert "+" in result
        with open(test_file, 'r') as f:
            content = f.read()
        expected_content = f"Line 1\n{special_content}\nLine 2\n"
        assert content == expected_content


class TestInsertPreservesLineEndings:
    """Insert must not rewrite the endings of lines it did not touch.

    Every assertion here reads the file back as raw bytes. Reading with the
    default ``open(..., 'r')`` translates ``\\r\\n`` and ``\\r`` to ``\\n``, so a
    text-mode assertion passes whether or not the tool preserved the endings.
    That is exactly how the original defect stayed invisible.
    """

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def test_file(self, temp_dir):
        """Create a test file path in the temporary directory."""
        return os.path.join(temp_dir, "test.txt")

    def _write_bytes(self, path, data):
        """Write raw bytes so the fixture itself cannot translate endings."""
        with open(path, 'wb') as handle:
            handle.write(data)

    def _read_bytes(self, path):
        """Read raw bytes so the assertion cannot translate endings."""
        with open(path, 'rb') as handle:
            return handle.read()

    def test_crlf_file_keeps_crlf(self, test_file):
        """A CRLF file stays CRLF after an insert."""
        self._write_bytes(test_file, b"a\r\nb\r\nc\r\n")

        insert_content_to_file(test_file, "NEW", line_num=2, before_or_after="after")

        assert self._read_bytes(test_file) == b"a\r\nb\r\nNEW\r\nc\r\n"

    def test_cr_only_file_keeps_cr(self, test_file):
        """A CR-only file stays CR-only after an insert."""
        self._write_bytes(test_file, b"a\rb\rc\r")

        insert_content_to_file(test_file, "NEW", line_num=2, before_or_after="after")

        assert self._read_bytes(test_file) == b"a\rb\rNEW\rc\r"

    def test_lf_file_stays_lf(self, test_file):
        """An LF file is not converted to another ending."""
        self._write_bytes(test_file, b"a\nb\nc\n")

        insert_content_to_file(test_file, "NEW", line_num=2, before_or_after="after")

        assert self._read_bytes(test_file) == b"a\nb\nNEW\nc\n"

    def test_inserted_line_adopts_crlf(self, test_file):
        """The inserted line uses the file's ending, not a hardcoded LF."""
        self._write_bytes(test_file, b"a\r\nb\r\n")

        insert_content_to_file(test_file, "NEW", line_num=1, before_or_after="after")

        assert self._read_bytes(test_file) == b"a\r\nNEW\r\nb\r\n"

    def test_inserted_line_adopts_cr(self, test_file):
        """The inserted line uses CR when the file uses CR."""
        self._write_bytes(test_file, b"a\rb\r")

        insert_content_to_file(test_file, "NEW", line_num=1, before_or_after="after")

        assert self._read_bytes(test_file) == b"a\rNEW\rb\r"

    def test_data_ending_with_crlf_is_not_double_terminated(self, test_file):
        """Content already ending with CRLF must not gain a second ending."""
        self._write_bytes(test_file, b"a\r\nb\r\nc\r\n")

        insert_content_to_file(test_file, "NEW\r\n", line_num=2, before_or_after="after")

        assert self._read_bytes(test_file) == b"a\r\nb\r\nNEW\r\nc\r\n"

    def test_data_ending_with_cr_is_not_double_terminated(self, test_file):
        """Content already ending with CR must not gain a second ending."""
        self._write_bytes(test_file, b"a\rb\rc\r")

        insert_content_to_file(test_file, "NEW\r", line_num=2, before_or_after="after")

        assert self._read_bytes(test_file) == b"a\rb\rNEW\rc\r"

    def test_insert_after_unterminated_last_line_does_not_glue(self, test_file):
        """Inserting after a last line without an ending must not fuse the lines."""
        self._write_bytes(test_file, b"a\nb")

        insert_content_to_file(test_file, "NEW", line_num=2, before_or_after="after")

        assert self._read_bytes(test_file) == b"a\nb\nNEW\n"

    def test_insert_before_first_line_of_unterminated_file(self, test_file):
        """Inserting before line 1 keeps the original first line intact."""
        self._write_bytes(test_file, b"only")

        insert_content_to_file(test_file, "NEW", line_num=1, before_or_after="before")

        assert self._read_bytes(test_file) == b"NEW\nonly"

    def test_cjk_content_is_written_as_utf8(self, test_file):
        """Non-ASCII content survives the read-modify-write cycle."""
        self._write_bytes(test_file, "中文\n".encode("utf-8"))

        insert_content_to_file(test_file, "插入", line_num=1, before_or_after="after")

        assert self._read_bytes(test_file) == "中文\n插入\n".encode("utf-8")

    def test_cjk_file_reads_under_non_utf8_locale(self, test_file, monkeypatch):
        """A UTF-8 file must not depend on the process locale to be readable.

        The original code called ``open(file_path, 'r')`` with no encoding, so
        under ``LC_ALL=C`` the preferred encoding is ASCII and reading a CJK file
        raised ``UnicodeDecodeError``.
        """
        self._write_bytes(test_file, "中文\n".encode("utf-8"))
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("LANG", "C")

        insert_content_to_file(test_file, "x", line_num=1, before_or_after="after")

        assert self._read_bytes(test_file) == "中文\nx\n".encode("utf-8")

    def test_diff_baseline_keeps_crlf(self, test_file):
        """The returned diff must not report untouched CRLF lines as changed."""
        self._write_bytes(test_file, b"a\r\nb\r\nc\r\n")

        result = insert_content_to_file(
            test_file, "NEW", line_num=2, before_or_after="after"
        )

        # Only the inserted line may appear as an addition; the untouched lines
        # must not show up as removed-and-readded pairs.
        assert "+NEW" in result
        assert "-a" not in result
        assert "-c" not in result
