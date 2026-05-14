#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Unit tests for file_write_line.replace_lines_in_file
'''

import json
import pytest

from topsailai.tools.file_tool_utils.file_write_line import (
    replace_lines_in_file,
)


class TestReplaceLinesInFile:
    """Test replace_lines_in_file function."""

    def test_basic_replace_single_line(self, tmp_path):
        """Test replacing a single line with new content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [(2, "modified_line2")])

        assert "modified_line2" in result
        content = test_file.read_text()
        assert content == "line1\nmodified_line2\nline3\n"

    def test_replace_multiple_lines(self, tmp_path):
        """Test replacing multiple lines at once."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = replace_lines_in_file(str(test_file), [(2, "new_line2"), (4, "new_line4")])

        assert "new_line2" in result
        assert "new_line4" in result
        content = test_file.read_text()
        assert content == "line1\nnew_line2\nline3\nnew_line4\nline5\n"

    def test_replace_with_dict_format(self, tmp_path):
        """Test replacing lines using dict format for line items."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        lines = [
            {"line_number": 1, "content": "updated_line1"},
            {"line_number": 3, "content": "updated_line3"},
        ]
        result = replace_lines_in_file(str(test_file), lines)

        assert "updated_line1" in result
        assert "updated_line3" in result
        content = test_file.read_text()
        assert content == "updated_line1\nline2\nupdated_line3\n"

    def test_delete_line_empty_string(self, tmp_path):
        """Test deleting a line by passing empty string as content.

        When content is empty string, the line content is replaced with "".
        Since ''.join(lines_content) uses "" as filler, the deleted line
        effectively disappears from the joined output.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [(2, "")])

        content = test_file.read_text()
        # The deleted line becomes empty, so line3 shifts to that position
        lines = content.split('\n')
        assert lines[1] == "line3"

    def test_delete_line_none_content(self, tmp_path):
        """Test deleting a line by passing None as content.

        When content is None, the line content is replaced with "".
        Since ''.join(lines_content) uses "" as filler, the deleted line
        effectively disappears from the joined output.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [(2, None)])

        content = test_file.read_text()
        lines = content.split('\n')
        # The deleted line becomes empty content, shifting adjacent lines
        assert lines[1] == "line3"

    def test_delete_multiple_lines(self, tmp_path):
        """Test deleting multiple lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        replace_lines_in_file(str(test_file), [(2, ""), (4, "")])

        content = test_file.read_text()
        lines = content.split('\n')
        # After deletion, lines shift: line3 moves to index 1, line5 moves to index 2
        assert lines[1] == "line3"
        assert lines[2] == "line5"

    def test_json_string_input(self, tmp_path):
        """Test passing lines as a JSON string."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        json_str = json.dumps([[1, "new_line1"], [3, "new_line3"]])
        result = replace_lines_in_file(str(test_file), json_str)

        assert "new_line1" in result
        assert "new_line3" in result
        content = test_file.read_text()
        assert content == "new_line1\nline2\nnew_line3\n"

    def test_file_not_found(self, tmp_path):
        """Test raising exception when file does not exist."""
        nonexistent = tmp_path / "nonexistent.txt"
        with pytest.raises(Exception, match="File not found:"):
            replace_lines_in_file(str(nonexistent), [(1, "content")])

    def test_empty_file(self, tmp_path):
        """Test replacing lines in an empty file (no lines to replace)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        # No lines to modify since index won't be in range
        result = replace_lines_in_file(str(test_file), [(1, "content")])
        content = test_file.read_text()
        assert content == ""  # unchanged

    def test_line_out_of_range_upper(self, tmp_path):
        """Test when line number exceeds file length (should be ignored)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
        )

        result = replace_lines_in_file(str(test_file), [(10, "new_line")])
        content = test_file.read_text()
        assert content == "line1\nline2\n"  # unchanged

    def test_line_out_of_range_lower(self, tmp_path):
        """Test when line number is <= 0 (index < 0, should be ignored)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
        )

        result = replace_lines_in_file(str(test_file), [(0, "new_line")])
        content = test_file.read_text()
        assert content == "line1\nline2\n"  # unchanged

    def test_line_number_as_string(self, tmp_path):
        """Test line number passed as string is converted to int."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [("2", "modified_line2")])
        content = test_file.read_text()
        assert content == "line1\nmodified_line2\nline3\n"

    def test_replace_last_line(self, tmp_path):
        """Test replacing the last line of the file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [(3, "new_last_line")])
        content = test_file.read_text()
        assert content == "line1\nline2\nnew_last_line\n"

    def test_replace_first_line(self, tmp_path):
        """Test replacing the first line of the file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [(1, "new_first_line")])
        content = test_file.read_text()
        assert content == "new_first_line\nline2\nline3\n"

    def test_file_without_trailing_newline(self, tmp_path):
        """Test file that doesn't end with a newline."""
        test_file = tmp_path / "test.txt"
        # No trailing newline
        test_file.write_text("line1\nline2\nline3")

        result = replace_lines_in_file(str(test_file), [(2, "new_line2")])
        content = test_file.read_text()
        # File should still not end with newline
        assert content == "line1\nnew_line2\nline3"
        assert not content.endswith('\n')

    def test_file_without_trailing_newline_replace_last(self, tmp_path):
        """Test replacing last line of file without trailing newline."""
        test_file = tmp_path / "test.txt"
        # No trailing newline
        test_file.write_text("line1\nline2\nline3")

        result = replace_lines_in_file(str(test_file), [(3, "new_last_line")])
        content = test_file.read_text()
        assert content == "line1\nline2\nnew_last_line"
        assert not content.endswith('\n')

    def test_file_without_trailing_newline_delete_last(self, tmp_path):
        """Test deleting last line of file without trailing newline."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3")

        result = replace_lines_in_file(str(test_file), [(3, "")])
        content = test_file.read_text()
        # Last line becomes empty, no trailing newline kept
        lines = content.split('\n')
        assert lines[2] == ""

    def test_content_with_line_ending_newline(self, tmp_path):
        """Test new content that already ends with \\n preserves properly."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [(2, "new_line2_with_newline\n")])
        content = test_file.read_text()
        assert content == "line1\nnew_line2_with_newline\nline3\n"

    def test_content_with_carriage_return_newline(self, tmp_path):
        """Test new content that ends with \\r\\n.

        Note: Python text mode with universal newlines converts \\r\\n to \\n
        on read, so the original \\r\\n is not preserved.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [(2, "new_line2\r\n")])
        content = test_file.read_text()
        # Since the file content is read via universal newlines in replace_lines_in_file,
        # the \r\n in new content becomes just \n after the write/read cycle
        assert content == "line1\nnew_line2\nline3\n"

    def test_content_with_carriage_return(self, tmp_path):
        """Test new content that ends with \\r (old Mac style).

        Note: Python text mode with universal newlines converts \\r to \\n
        on read, so the original \\r is not preserved.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [(2, "new_line2\r")])
        content = test_file.read_text()
        # \r is converted to \n via universal newlines in the read/write cycle
        assert content == "line1\nnew_line2\nline3\n"

    def test_preserve_original_line_endings(self, tmp_path):
        """Test that original line endings are preserved.

        Note: Python text mode with universal newlines converts \\r\\n to \\n
        on read (both in replace_lines_in_file's open() and test_file.read_text()).
        So the original \\r\\n endings become \\n after processing.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\r\nline2\r\nline3\r\n")

        result = replace_lines_in_file(str(test_file), [(2, "new_line2")])
        content = test_file.read_text()
        # Universal newlines convert \r\n to \n; the line ending is still preserved as \n
        assert "new_line2\n" in content
        assert content == "line1\nnew_line2\nline3\n"

    def test_returns_diff_string(self, tmp_path):
        """Test that the function returns a string with diff content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = replace_lines_in_file(str(test_file), [(2, "modified")])
        assert isinstance(result, str)
        # Diff should show the change
        assert "modified" in result or "line2" in result

    def test_unicode_content(self, tmp_path):
        """Test replacing lines with unicode characters."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello\n世界\nfoo\n")

        result = replace_lines_in_file(str(test_file), [(2, "🌍✨")])
        content = test_file.read_text()
        assert content == "hello\n🌍✨\nfoo\n"

    def test_single_line_file(self, tmp_path):
        """Test replacing the only line in a single-line file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("only_line\n")

        result = replace_lines_in_file(str(test_file), [(1, "replaced")])
        content = test_file.read_text()
        assert content == "replaced\n"

    def test_single_line_file_no_newline(self, tmp_path):
        """Test replacing the only line in a single-line file without trailing newline."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("only_line")

        result = replace_lines_in_file(str(test_file), [(1, "replaced")])
        content = test_file.read_text()
        assert content == "replaced"
        assert not content.endswith('\n')

    def test_json_string_with_dict_format(self, tmp_path):
        """Test JSON string input with dict format (not tuple format)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        json_str = json.dumps([
            {"line_number": 1, "content": "new1"},
            {"line_number": 3, "content": "new3"},
        ])
        result = replace_lines_in_file(str(test_file), json_str)
        content = test_file.read_text()
        assert content == "new1\nline2\nnew3\n"

    def test_replace_with_multiline_content_expands_lines(self, tmp_path):
        """Test that replacement content containing \\n adds extra lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        # Replace line 3 with content that contains multiple lines
        result = replace_lines_in_file(str(test_file), [
            (3, "line3a\nline3b\nline3c\n")
        ])

        content = test_file.read_text()
        assert content == (
            "line1\n"
            "line2\n"
            "line3a\n"
            "line3b\n"
            "line3c\n"
            "line4\n"
            "line5\n"
        )

    def test_replace_with_multiline_content_no_trailing_newline(self, tmp_path):
        """Test replacement with multiline content that lacks final \\n."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
        )

        # Replace line 2 with multi-line content that doesn't end with \n
        result = replace_lines_in_file(str(test_file), [
            (2, "new_line2a\nnew_line2b")
        ])

        content = test_file.read_text()
        # The second sub-line becomes "new_line2b\n" (original line ending preserved),
        # and line 3's content becomes "line3\n" etc.
        assert content == (
            "line1\n"
            "new_line2a\n"
            "new_line2b\n"
            "line3\n"
            "line4\n"
        )

    def test_multiline_with_embedded_blank_line(self, tmp_path):
        """Test replacement with content containing a blank line (\\n\\n)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        # Replace line 2 with content that has an embedded blank line
        result = replace_lines_in_file(str(test_file), [
            (2, "aaa\nbbb\n\nccc\n")
        ])

        content = test_file.read_text()
        assert content == (
            "line1\n"
            "aaa\n"
            "bbb\n"
            "\n"
            "ccc\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

    def test_multiline_with_multiple_consecutive_blank_lines(self, tmp_path):
        """Test replacement with content having multiple consecutive blank lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        # Replace line 2 with content containing double and triple blank lines
        result = replace_lines_in_file(str(test_file), [
            (2, "aaa\n\n\nbbb\n")
        ])

        content = test_file.read_text()
        assert content == (
            "line1\n"
            "aaa\n"
            "\n"
            "\n"
            "bbb\n"
            "line3\n"
        )

    def test_multiline_with_blank_line_no_trailing_newline(self, tmp_path):
        """Test replacement with blank line content that lacks final \\n."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
        )

        # Replace line 3 with content that has a blank line but no trailing \n
        result = replace_lines_in_file(str(test_file), [
            (3, "single\n\nlast")
        ])

        content = test_file.read_text()
        # "last" gets the original line ending (\n) from line3, then line4 follows
        assert content == (
            "line1\n"
            "line2\n"
            "single\n"
            "\n"
            "last\n"
            "line4\n"
        )

    def test_mix_delete_and_multiline_replacement(self, tmp_path):
        """Test mixing line deletion with multiline replacement."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        # Delete line 1, expand line 3 with multiline content, delete line 5
        result = replace_lines_in_file(str(test_file), [
            (1, ""),
            (3, "expanded_a\n\nexpanded_b\n"),
            (5, ""),
        ])

        content = test_file.read_text()
        # lines_content before join: ['', 'line2\n', 'expanded_a\n\nexpanded_b\n', 'line4\n', '']
        assert content == (
            "line2\n"
            "expanded_a\n"
            "\n"
            "expanded_b\n"
            "line4\n"
        )

    def test_complex_multiple_operations_mixed_types(self, tmp_path):
        """Test complex scenario: deletions, multiline, single-line, blank lines.

        When the first line is deleted (set to ""), ''.'join' absorbs the empty
        string so the joined text starts with the next element, no leading blank line.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
            "line6\n"
        )

        # Mix of operations: delete line 1, multiline on 2, blank-line multiline on 4,
        # single line replacement on 5, delete line 6
        result = replace_lines_in_file(str(test_file), [
            (1, ""),
            (2, "multi_a\nmulti_b\nmulti_c\n"),
            (4, "gap1\n\ngap2\n\ngap3\n"),
            (5, "single_replaced"),
            (6, ""),
        ])

        content = test_file.read_text()
        lines = content.split('\n')

        # line1 deleted (""), merged into next element by ''.join → no leading blank
        # line2 expanded to 3 lines
        assert lines[0] == "multi_a"
        assert lines[1] == "multi_b"
        assert lines[2] == "multi_c"
        # line3 unchanged
        assert lines[3] == "line3"
        # line4 expanded to gap1, blank, gap2, blank, gap3
        assert lines[4] == "gap1"
        assert lines[5] == ""
        assert lines[6] == "gap2"
        assert lines[7] == ""
        assert lines[8] == "gap3"
        # line5 single replacement (with \n ending preserved)
        assert lines[9] == "single_replaced"
        # line6 deleted ("") → final element is empty string from trailing \n
        assert lines[10] == ""
        assert len(lines) == 11

    def test_replace_consecutive_lines_no_trailing_newline_preserves_surrounding(self, tmp_path):
        """Test replacing consecutive lines (2 and 3) without trailing \\n.

        File content:
          line1
          line2
          line3
          line4
        Replace line2 with "new2" (no \\n) and line3 with "new3" (no \\n).
        The original line endings from lines 2 and 3 should be preserved,
        and line1 and line4 must remain unchanged.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
        )

        # Replace lines 2 and 3 with content that has no trailing \n
        result = replace_lines_in_file(str(test_file), [
            (2, "new2"),
            (3, "new3"),
        ])

        content = test_file.read_text()
        assert content == (
            "line1\n"
            "new2\n"
            "new3\n"
            "line4\n"
        )

    def test_replace_with_multiline_content_consecutive_insert(self, tmp_path):
        """Test multiple consecutive line replacements with multiline content.

        The function replaces each line entry individually in the original
        lines_content list (no line expansion), so consecutive replacements
        each replace their respective entry in the list.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        # Replace both line 2 and line 3 with multiline content
        result = replace_lines_in_file(str(test_file), [
            (2, "new_line2a\nnew_line2b\n"),
            (3, "new_line3a\nnew_line3b\n"),
        ])

        content = test_file.read_text()
        # Each element is replaced independently in the list, then joined.
        # Total = line1\n + new_line2a\nnew_line2b\n + new_line3a\nnew_line3b\n
        assert content == (
            "line1\n"
            "new_line2a\n"
            "new_line2b\n"
            "new_line3a\n"
            "new_line3b\n"
        )

    def test_replace_large_range_middle_lines(self, tmp_path):
        """Test replacing a large range of lines (11-23) in a 30-line file."""
        # Create a 30-line file
        original_lines = [f"line_{i}" for i in range(1, 31)]
        test_file = tmp_path / "test.txt"
        test_file.write_text("\n".join(original_lines) + "\n")

        # Replace lines 11 through 23
        replacements = [(i, f"replaced_line_{i}") for i in range(11, 24)]
        result = replace_lines_in_file(str(test_file), replacements)

        content = test_file.read_text()
        lines = content.strip().split('\n')

        # Verify unchanged lines (1-10 and 24-30)
        for i in range(1, 11):
            assert lines[i - 1] == f"line_{i}", f"Line {i} should be unchanged"
        # New line indices: 1-10 at [0..9], then replaced lines at [10..22], then 24-30 at [23..29]
        for i in range(11, 24):
            assert lines[i - 1] == f"replaced_line_{i}", f"Line {i} should be replaced"
        for i in range(24, 31):
            assert lines[i - 1] == f"line_{i}", f"Line {i} should be unchanged"

        # Verify total line count
        assert len(lines) == 30

        # Verify diff contains the replacements
        for i in range(11, 24):
            assert f"replaced_line_{i}" in result

    def test_multiple_operations_same_line(self, tmp_path):
        """Test that only the last operation on same line takes effect."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
        )

        result = replace_lines_in_file(str(test_file), [
            (2, "first_change"),
            (2, "second_change"),
        ])
        content = test_file.read_text()
        assert content == "line1\nsecond_change\nline3\n"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])