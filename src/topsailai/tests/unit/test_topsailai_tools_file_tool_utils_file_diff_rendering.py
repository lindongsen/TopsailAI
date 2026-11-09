"""Tests for unified diff line rendering.

The diff returned by the file tools is the only feedback an LLM receives after an
edit. If the header lines are fused together, the diff cannot be read and a wrong
edit goes unnoticed. These tests pin the line structure of that output.
"""

import pytest

from topsailai.tools.file_tool_utils.file_diff import get_unified_diff
from topsailai.tools.file_tool_utils.file_write_code_block import overwrite_code_block


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def _lines(result):
    return result.splitlines()


def _find(lines, prefix):
    return [line for line in lines if line.startswith(prefix)]


class TestUnifiedDiffLineStructure:
    """Header and content lines must each occupy their own line."""

    def test_d1_header_lines_are_separate(self, tmp_path):
        """D1: ---, +++ and @@ each occupy their own line."""
        f1 = _write(tmp_path / "a.txt", "a\nb\nc\nd\n")
        f2 = _write(tmp_path / "b.txt", "a\nB\nc\nd\n")

        lines = _lines(get_unified_diff(f1, f2))

        assert len(_find(lines, "--- ")) == 1
        assert len(_find(lines, "+++ ")) == 1
        assert len(_find(lines, "@@ ")) == 1

    def test_d2_no_fused_header_line(self, tmp_path):
        """D2: no single line contains both the --- and +++ markers."""
        f1 = _write(tmp_path / "a.txt", "a\nb\nc\nd\n")
        f2 = _write(tmp_path / "b.txt", "a\nB\nc\nd\n")

        lines = _lines(get_unified_diff(f1, f2))

        fused = [line for line in lines if "--- " in line and "+++ " in line]
        assert fused == []

    def test_d3_content_lines_are_separate(self, tmp_path):
        """D3: removed, added and context lines each occupy their own line."""
        f1 = _write(tmp_path / "a.txt", "a\nb\nc\nd\n")
        f2 = _write(tmp_path / "b.txt", "a\nB\nc\nd\n")

        lines = _lines(get_unified_diff(f1, f2))

        assert "-b" in lines
        assert "+B" in lines
        assert " a" in lines
        assert " c" in lines
        assert " d" in lines

    def test_d4_line_count_matches_standard_layout(self, tmp_path):
        """D4: a one-line change in a 4-line file yields 8 diff lines."""
        f1 = _write(tmp_path / "a.txt", "a\nb\nc\nd\n")
        f2 = _write(tmp_path / "b.txt", "a\nB\nc\nd\n")

        lines = _lines(get_unified_diff(f1, f2))

        assert len(lines) == 8

    def test_d5_multi_hunk_stays_readable(self, tmp_path):
        """D5: two separated changes keep every header and change line separate."""
        f1 = _write(tmp_path / "a.txt", "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n")
        f2 = _write(tmp_path / "b.txt", "1\nX\n3\n4\n5\n6\n7\n8\nY\n10\n")

        lines = _lines(get_unified_diff(f1, f2))

        assert "-2" in lines
        assert "+X" in lines
        assert "-9" in lines
        assert "+Y" in lines
        assert len(_find(lines, "@@ ")) == 1
        assert _find(lines, "@@ ")[0].endswith("@@")

    def test_d6_empty_to_content(self, tmp_path):
        """D6: creating content from an empty file keeps headers separate."""
        f1 = _write(tmp_path / "a.txt", "")
        f2 = _write(tmp_path / "b.txt", "line1\nline2\n")

        lines = _lines(get_unified_diff(f1, f2))

        assert len(_find(lines, "@@ ")) == 1
        assert "+line1" in lines
        assert "+line2" in lines

    def test_d7_unicode_content(self, tmp_path):
        """D7: CJK content survives and headers stay separate."""
        f1 = _write(tmp_path / "a.txt", "hello\n\u4e16\u754c\n")
        f2 = _write(tmp_path / "b.txt", "hello\nuniverse\n")

        lines = _lines(get_unified_diff(f1, f2))

        assert "-\u4e16\u754c" in lines
        assert "+universe" in lines
        assert len(_find(lines, "--- ")) == 1
        assert len(_find(lines, "+++ ")) == 1
        assert len(_find(lines, "@@ ")) == 1

    def test_d8_crlf_input_files(self, tmp_path):
        """D8: CRLF input must not leak carriage returns into the diff."""
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_bytes(b"a\r\nb\r\nc\r\n")
        f2.write_bytes(b"a\r\nB\r\nc\r\n")

        result = get_unified_diff(str(f1), str(f2))

        assert "\r" not in result
        assert len(_find(_lines(result), "--- ")) == 1

    def test_d9_identical_files_return_empty(self, tmp_path):
        """D9: identical files still produce an empty diff."""
        f1 = _write(tmp_path / "a.txt", "a\nb\nc\n")
        f2 = _write(tmp_path / "b.txt", "a\nb\nc\n")

        assert get_unified_diff(f1, f2) == ""

    def test_d10_no_trailing_newline(self, tmp_path):
        """D10: a file without a trailing newline must not break the layout."""
        f1 = _write(tmp_path / "a.txt", "a\nb\nc")
        f2 = _write(tmp_path / "b.txt", "a\nB\nc")

        lines = _lines(get_unified_diff(f1, f2))

        assert len(_find(lines, "--- ")) == 1
        assert "-b" in lines
        assert "+B" in lines


class TestDiffThroughTools:
    """The string an LLM actually receives must be readable."""

    def test_d11_overwrite_code_block_returns_readable_diff(self, tmp_path):
        """D11: overwrite_code_block returns a line-separated diff."""
        target = _write(
            tmp_path / "target.py",
            "def a():\n    pass\n\ndef b():\n    pass\n\ndef c():\n    pass\n",
        )

        result = overwrite_code_block(target, 4, 5, "def b():\n    return 1\n")
        lines = _lines(result)

        assert len(_find(lines, "--- ")) == 1
        assert len(_find(lines, "+++ ")) == 1
        assert len(_find(lines, "@@ ")) == 1
        assert "-    pass" in lines
        assert "+    return 1" in lines

    def test_d12_insert_content_to_file_returns_readable_diff(self, tmp_path):
        """D12: insert_content_to_file returns a line-separated diff."""
        from topsailai.tools.file_tool import insert_content_to_file

        target = _write(tmp_path / "target.py", "a = 1\nb = 2\n")

        result = insert_content_to_file(target, "c = 3\n", 2, "after")
        lines = _lines(result)

        assert len(_find(lines, "--- ")) == 1
        assert len(_find(lines, "@@ ")) == 1
        assert "+c = 3" in lines


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
