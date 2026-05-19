#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Unit tests for file_write_code_block.overwrite_code_block
'''

import pytest

from topsailai.tools.file_tool_utils.file_write_code_block import (
    overwrite_code_block,
)


class TestOverwriteCodeBlock:
    """Test overwrite_code_block function."""

    def test_basic_replace_block_single_line(self, tmp_path):
        """Test replacing a block (single line) with new content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = overwrite_code_block(str(test_file), 3, 3, "new_line3")

        assert "new_line3" in result
        content = test_file.read_text()
        assert content == (
            "line1\n"
            "line2\n"
            "new_line3\n"
            "line4\n"
            "line5\n"
        )

    def test_replace_block_multiple_lines(self, tmp_path):
        """Test replacing a multi-line block (lines 2-4) with new content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = overwrite_code_block(str(test_file), 2, 4, "replacement_block")

        assert "replacement_block" in result
        content = test_file.read_text()
        assert content == (
            "line1\n"
            "replacement_block\n"
            "line5\n"
        )

    def test_replace_block_with_multiline_content(self, tmp_path):
        """Test replacing a block with multi-line content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = overwrite_code_block(
            str(test_file), 2, 3,
            "new_line2\nnew_line3\nnew_line4\n"
        )

        assert "new_line2" in result
        assert "new_line4" in result
        content = test_file.read_text()
        assert content == (
            "line1\n"
            "new_line2\n"
            "new_line3\n"
            "new_line4\n"
            "line4\n"
            "line5\n"
        )

    def test_replace_to_end_of_file(self, tmp_path):
        """Test replacing from a line to end of file (end_num=0)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = overwrite_code_block(str(test_file), 3, 0, "new_line3\nnew_end\n")

        assert "new_line3" in result
        assert "new_end" in result
        content = test_file.read_text()
        assert content == (
            "line1\n"
            "line2\n"
            "new_line3\n"
            "new_end\n"
        )

    def test_replace_first_line(self, tmp_path):
        """Test replacing the first line of the file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = overwrite_code_block(str(test_file), 1, 1, "new_first_line")
        content = test_file.read_text()
        assert content == "new_first_line\nline2\nline3\n"

    def test_replace_last_line(self, tmp_path):
        """Test replacing the last line of the file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = overwrite_code_block(str(test_file), 3, 3, "new_last_line")
        content = test_file.read_text()
        assert content == "line1\nline2\nnew_last_line\n"

    def test_replace_entire_file(self, tmp_path):
        """Test replacing the entire file content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = overwrite_code_block(
            str(test_file), 1, 0, "new_content_line1\nnew_content_line2\n"
        )

        content = test_file.read_text()
        assert content == "new_content_line1\nnew_content_line2\n"

    def test_empty_content_deletes_block(self, tmp_path):
        """Test passing empty string as content deletes the block."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = overwrite_code_block(str(test_file), 2, 4, "")

        content = test_file.read_text()
        assert content == "line1\nline5\n"

    def test_empty_content_with_single_line(self, tmp_path):
        """Test empty content on a single line deletion."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = overwrite_code_block(str(test_file), 2, 2, "")

        content = test_file.read_text()
        assert content == "line1\nline3\n"

    def test_file_not_found(self, tmp_path):
        """Test raising exception when file does not exist."""
        nonexistent = tmp_path / "nonexistent.txt"
        with pytest.raises(Exception, match="File not found:"):
            overwrite_code_block(str(nonexistent), 1, 10, "content")

    def test_invalid_start_num_negative(self, tmp_path):
        """Test raising exception when start_num < 1."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        with pytest.raises(Exception, match="Invalid start_num"):
            overwrite_code_block(str(test_file), 0, 3, "content")

    def test_start_num_exceeds_file_length(self, tmp_path):
        """Test raising exception when start_num > file length."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\n")

        with pytest.raises(Exception, match="exceeds file length"):
            overwrite_code_block(str(test_file), 10, 20, "content")

    def test_start_num_greater_than_end_num(self, tmp_path):
        """Test raising exception when start_num > end_num (and end_num != 0)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        with pytest.raises(Exception, match="Invalid range"):
            overwrite_code_block(str(test_file), 5, 3, "content")

    def test_start_num_as_string(self, tmp_path):
        """Test start_num passed as string is converted to int."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = overwrite_code_block(str(test_file), "2", "2", "modified")
        content = test_file.read_text()
        assert content == "line1\nmodified\nline3\n"

    def test_end_num_as_string_zero(self, tmp_path):
        """Test end_num=0 passed as string."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = overwrite_code_block(str(test_file), "2", "0", "new_line2\nnew_line3\n")
        content = test_file.read_text()
        assert content == "line1\nnew_line2\nnew_line3\n"

    def test_returns_diff_string(self, tmp_path):
        """Test that the function returns a string with diff content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = overwrite_code_block(str(test_file), 2, 2, "modified")
        assert isinstance(result, str)
        assert "modified" in result or "line2" in result

    def test_unicode_content(self, tmp_path):
        """Test replacing block with unicode characters."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "hello\n"
            "world\n"
            "foo\n"
            "bar\n"
        )

        result = overwrite_code_block(str(test_file), 2, 3, "🌍✨\n测试\n")
        content = test_file.read_text()
        assert content == "hello\n🌍✨\n测试\nbar\n"

    def test_single_line_file_replace(self, tmp_path):
        """Test replacing the block in a single-line file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("only_line\n")

        result = overwrite_code_block(str(test_file), 1, 1, "replaced")
        content = test_file.read_text()
        assert content == "replaced\n"

    def test_single_line_file_replace_to_end(self, tmp_path):
        """Test replace to end in a single-line file (end_num=0)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("only_line\n")

        result = overwrite_code_block(str(test_file), 1, 0, "replaced")
        content = test_file.read_text()
        assert content == "replaced\n"

    def test_empty_file(self, tmp_path):
        """Test replacing block in an empty file should raise."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        with pytest.raises(Exception, match="exceeds file length"):
            overwrite_code_block(str(test_file), 1, 1, "content")

    def test_file_without_trailing_newline(self, tmp_path):
        """Test file that doesn't end with a newline."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3")

        result = overwrite_code_block(str(test_file), 2, 2, "new_line2")
        content = test_file.read_text()
        assert content == "line1\nnew_line2\nline3"
        assert not content.endswith('\n')

    def test_file_without_trailing_newline_replace_end(self, tmp_path):
        """Test replace to end of file without trailing newline."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3")

        result = overwrite_code_block(str(test_file), 2, 0, "new_line2\nnew_line3\nnew_line4")
        content = test_file.read_text()
        assert content == "line1\nnew_line2\nnew_line3\nnew_line4"
        assert not content.endswith('\n')

    def test_file_without_trailing_newline_replace_last(self, tmp_path):
        """Test replacing last line of file without trailing newline."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3")

        result = overwrite_code_block(str(test_file), 3, 3, "new_last_line")
        content = test_file.read_text()
        assert content == "line1\nline2\nnew_last_line"
        assert not content.endswith('\n')

    def test_replace_block_preserves_indentation(self, tmp_path):
        """Test that replaced content with indentation is preserved."""
        test_file = tmp_path / "test.py"
        test_file.write_text(
            "def foo():\n"
            "    pass\n"
            "\n"
            "def bar():\n"
            "    return 42\n"
        )

        result = overwrite_code_block(
            str(test_file), 4, 5,
            "def bar():\n"
            "    return 43\n"
        )

        content = test_file.read_text()
        assert content == (
            "def foo():\n"
            "    pass\n"
            "\n"
            "def bar():\n"
            "    return 43\n"
        )

    def test_replace_with_blank_lines_in_content(self, tmp_path):
        """Test replacement content containing blank lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = overwrite_code_block(
            str(test_file), 2, 4,
            "aaa\n"
            "\n"
            "bbb\n"
            "\n"
            "\n"
            "ccc\n"
        )

        content = test_file.read_text()
        assert content == (
            "line1\n"
            "aaa\n"
            "\n"
            "bbb\n"
            "\n"
            "\n"
            "ccc\n"
            "line5\n"
        )

    def test_replace_with_content_no_trailing_newline(self, tmp_path):
        """Test replacement content that does not end with newline."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
        )

        result = overwrite_code_block(str(test_file), 2, 3, "new_a\nnew_b")

        content = test_file.read_text()
        assert content == (
            "line1\n"
            "new_a\n"
            "new_b\n"
            "line4\n"
        )

    def test_replace_large_block_middle(self, tmp_path):
        """Test replacing a large block (lines 5-20) in the middle of a 30-line file."""
        original_lines = [f"line_{i}" for i in range(1, 31)]
        test_file = tmp_path / "test.txt"
        test_file.write_text("\n".join(original_lines) + "\n")

        replacement = "\n".join([f"new_line_{i}" for i in range(5, 21)])
        result = overwrite_code_block(str(test_file), 5, 20, replacement + "\n")

        content = test_file.read_text()
        lines = content.strip().split('\n')

        # Verify unchanged lines (1-4)
        for i in range(1, 5):
            assert lines[i - 1] == f"line_{i}", f"Line {i} should be unchanged"
        # Verify replaced lines (5-20)
        for i in range(5, 21):
            assert lines[i - 1] == f"new_line_{i}", f"Line {i} should be replaced"
        # Verify unchanged lines (21-30)
        for i in range(21, 31):
            assert lines[i - 1] == f"line_{i}", f"Line {i} should be unchanged"

        assert len(lines) == 30

    def test_empty_file_replace(self, tmp_path):
        """Test replacing into an empty file should raise."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        with pytest.raises(Exception):
            overwrite_code_block(str(test_file), 1, 1, "should_fail")

    # ── Edge cases ──────────────────────────────────────────────

    def test_replace_first_n_lines(self, tmp_path):
        """Replace lines 1-3 (first portion) of a 6-line file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
            "line6\n"
        )
        result = overwrite_code_block(
            str(test_file), 1, 3, "new1\nnew2\nnew3\n"
        )
        content = test_file.read_text()
        assert content == (
            "new1\nnew2\nnew3\n"
            "line4\nline5\nline6\n"
        )

    def test_replace_last_n_lines(self, tmp_path):
        """Replace lines 4-6 (last portion) of a 6-line file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
            "line6\n"
        )
        result = overwrite_code_block(
            str(test_file), 4, 6, "end1\nend2\nend3\n"
        )
        content = test_file.read_text()
        assert content == (
            "line1\nline2\nline3\n"
            "end1\nend2\nend3\n"
        )

    def test_replace_exact_full_file(self, tmp_path):
        """Replace entire file by specifying exact start=1, end=last_line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("a\nb\nc\n")
        result = overwrite_code_block(str(test_file), 1, 3, "x\ny\nz\n")
        content = test_file.read_text()
        assert content == "x\ny\nz\n"

    def test_replace_same_content_noop(self, tmp_path):
        """Replacing a block with identical content should be a no-op."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )
        result = overwrite_code_block(str(test_file), 1, 3, "line1\nline2\nline3\n")
        content = test_file.read_text()
        assert content == "line1\nline2\nline3\n"
        # Diff should indicate no differences or empty
        assert isinstance(result, str)

    def test_content_with_only_newlines(self, tmp_path):
        """Content consisting of just newlines should insert blank lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "header\n"
            "body\n"
            "footer\n"
        )
        result = overwrite_code_block(str(test_file), 2, 2, "\n\n")
        content = test_file.read_text()
        assert content == (
            "header\n"
            "\n"
            "\n"
            "footer\n"
        )

    def test_content_with_tabs_preserved(self, tmp_path):
        """Tab characters in replacement content must be preserved."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "def foo():\n"
            "    pass\n"
        )
        result = overwrite_code_block(
            str(test_file), 2, 2, "\treturn 42\n"
        )
        content = test_file.read_text()
        assert content == "def foo():\n\treturn 42\n"

    def test_content_with_trailing_spaces(self, tmp_path):
        """Trailing spaces in replacement lines must be preserved."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("a\nb\nc\n")
        result = overwrite_code_block(str(test_file), 2, 2, "b   \n")
        content = test_file.read_text()
        assert content == "a\nb   \nc\n"

    def test_end_num_clamped_to_file_length(self, tmp_path):
        """end_num beyond file length should be clamped (no crash)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")
        result = overwrite_code_block(str(test_file), 2, 999, "replaced\n")
        content = test_file.read_text()
        assert content == "line1\nreplaced\n"

    def test_start_num_equal_file_length(self, tmp_path):
        """start_num exactly equal to the number of lines in file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )
        result = overwrite_code_block(str(test_file), 2, 3, "replaced_line2\nreplaced_line3\n")
        content = test_file.read_text()
        assert content == "line1\nreplaced_line2\nreplaced_line3\n"

    def test_content_with_carriage_return_newline(self, tmp_path):
        """Content with \\r\\n line endings should be properly preserved.

        Note: Python text mode universal newlines convert \\r\\n to \\n
        on read, so the \\r\\n in content becomes \\n after write/read cycle.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")
        result = overwrite_code_block(str(test_file), 1, 2, "a\r\nb\r\n")
        content = test_file.read_text()
        # Universal newlines convert \r\n to \n
        assert content == "a\nb\nline3\n"

    def test_json_string_content(self, tmp_path):
        """Content passed as a JSON string should be unescaped."""
        import json
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")
        # Pass content as a JSON-encoded string
        json_content = json.dumps("replaced_line")
        result = overwrite_code_block(str(test_file), 2, 2, json_content)
        content = test_file.read_text()
        assert content == "line1\nreplaced_line\nline3\n"

    def test_multiline_json_content(self, tmp_path):
        """Multiline content passed as a JSON string."""
        import json
        test_file = tmp_path / "test.txt"
        test_file.write_text("a\nb\nc\nd\n")
        json_content = json.dumps("x\ny\n")
        result = overwrite_code_block(str(test_file), 2, 3, json_content)
        content = test_file.read_text()
        assert content == "a\nx\ny\nd\n"

    def test_consecutive_replacements_line_number_stability(self, tmp_path):
        """After the first replace, line numbers shift. This verifies
        the behavior when called twice on the same file and the user
        must account for shifting line numbers."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
        )

        # First replacement: replace lines 2-3 with a single line
        # File becomes: line1\nsingle\nline4\n
        result1 = overwrite_code_block(str(test_file), 2, 3, "single\n")
        content1 = test_file.read_text()
        assert content1 == "line1\nsingle\nline4\n"

        # Second replacement with shifted line numbers:
        # The old line4 is now at line 3
        result2 = overwrite_code_block(str(test_file), 2, 2, "second\n")
        content2 = test_file.read_text()
        assert content2 == "line1\nsecond\nline4\n"

    def test_middle_block_with_expansion(self, tmp_path):
        """Replace a 2-line block with 5-line content (expansion)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "header\n"
            "keep1\n"
            "remove1\n"
            "remove2\n"
            "keep2\n"
            "footer\n"
        )
        result = overwrite_code_block(
            str(test_file), 3, 4,
            "new1\nnew2\nnew3\nnew4\nnew5\n"
        )
        content = test_file.read_text()
        assert content == (
            "header\n"
            "keep1\n"
            "new1\n"
            "new2\n"
            "new3\n"
            "new4\n"
            "new5\n"
            "keep2\n"
            "footer\n"
        )

    def test_middle_block_with_contraction(self, tmp_path):
        """Replace a 4-line block with 1 line (contraction)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "header\n"
            "keep1\n"
            "a\n"
            "b\n"
            "c\n"
            "d\n"
            "keep2\n"
        )
        result = overwrite_code_block(str(test_file), 3, 6, "single\n")
        content = test_file.read_text()
        assert content == (
            "header\n"
            "keep1\n"
            "single\n"
            "keep2\n"
        )

    def test_replacement_content_with_only_newline_ending(self, tmp_path):
        """Content that is just a newline should become a blank line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )
        result = overwrite_code_block(str(test_file), 2, 2, "\n")
        content = test_file.read_text()
        assert content == "line1\n\nline3\n"

    def test_empty_string_start_num_zero(self, tmp_path):
        """start_num = 0 should raise."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("a\nb\nc\n")
        with pytest.raises(Exception, match="Invalid start_num"):
            overwrite_code_block(str(test_file), 0, 1, "x\n")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
