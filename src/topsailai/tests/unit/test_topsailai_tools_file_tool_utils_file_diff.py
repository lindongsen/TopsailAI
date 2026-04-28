import pytest

from topsailai.tools.file_tool_utils.file_diff import (
    compare_files,
    format_diff_block,
    get_unified_diff,
)


class TestCompareFiles:
    """Test compare_files function."""

    def test_identical_files(self, tmp_path):
        """Test comparing two identical files."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("line1\nline2\nline3\n")
        file2.write_text("line1\nline2\nline3\n")

        result = compare_files(str(file1), str(file2))

        # Source initializes result as ["---"], so len(result) is 1 for identical files.
        # The condition len(result) == 2 is never met, so "Files are identical" is not appended.
        assert result == "---"

    def test_different_files(self, tmp_path):
        """Test comparing two different files."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("line1\nline2\nline3\n")
        file2.write_text("line1\nmodified\nline3\n")

        result = compare_files(str(file1), str(file2))

        assert "---" in result
        assert "-" in result or "+" in result

    def test_file_not_found(self, tmp_path):
        """Test when one file does not exist raises FileNotFoundError."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("line1\n")

        with pytest.raises(FileNotFoundError):
            compare_files(str(file1), str(tmp_path / "nonexistent.txt"))

    def test_both_files_not_found(self, tmp_path):
        """Test when both files do not exist raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            compare_files(
                str(tmp_path / "nonexistent1.txt"),
                str(tmp_path / "nonexistent2.txt")
            )

    def test_empty_files(self, tmp_path):
        """Test comparing two empty files."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("")
        file2.write_text("")

        result = compare_files(str(file1), str(file2))

        # Same as test_identical_files: source bug means "Files are identical" is not appended.
        assert result == "---"

    def test_one_empty_file(self, tmp_path):
        """Test comparing empty file with non-empty file."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("")
        file2.write_text("line1\nline2\n")

        result = compare_files(str(file1), str(file2))

        assert "+" in result

    def test_multiple_diff_blocks(self, tmp_path):
        """Test files with multiple separate difference blocks."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text(
            "a\n"
            "b\n"
            "c\n"
            "d\n"
            "e\n"
            "f\n"
            "g\n"
        )
        file2.write_text(
            "a\n"
            "b_modified\n"
            "c\n"
            "d\n"
            "e\n"
            "f_modified\n"
            "g\n"
        )

        result = compare_files(str(file1), str(file2))

        assert "b_modified" in result
        assert "f_modified" in result
        assert "---" in result

    def test_large_diff_block_split(self, tmp_path):
        """Test that diff blocks larger than 10 lines are split."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("\n".join([f"old{i}" for i in range(15)]) + "\n")
        file2.write_text("\n".join([f"new{i}" for i in range(15)]) + "\n")

        result = compare_files(str(file1), str(file2))

        # Should contain multiple separators due to block splitting
        assert result.count("---") >= 2

    def test_custom_context_lines(self, tmp_path):
        """Test with custom context_lines parameter."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
            "line6\n"
            "line7\n"
        )
        file2.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "modified\n"
            "line5\n"
            "line6\n"
            "line7\n"
        )

        result = compare_files(str(file1), str(file2), context_lines=1)

        assert "modified" in result
        assert "---" in result

    def test_zero_context_lines(self, tmp_path):
        """Test with context_lines=0."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("line1\nline2\nline3\n")
        file2.write_text("line1\nmodified\nline3\n")

        result = compare_files(str(file1), str(file2), context_lines=0)

        assert "modified" in result

    def test_unicode_content(self, tmp_path):
        """Test comparing files with unicode content."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("hello\n世界\n")
        file2.write_text("hello\nuniverse\n")

        result = compare_files(str(file1), str(file2))

        assert "universe" in result

    def test_special_characters(self, tmp_path):
        """Test comparing files with special characters."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("tab\there\nspace here\n")
        file2.write_text("tab\there\nspace  here\n")

        result = compare_files(str(file1), str(file2))

        assert "---" in result

    def test_returns_string(self, tmp_path):
        """Test that compare_files returns a string."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("a\n")
        file2.write_text("b\n")

        result = compare_files(str(file1), str(file2))

        assert isinstance(result, str)

    def test_intraline_diff_with_question_marks(self, tmp_path):
        """Test compare_files with Differ's intraline change indicators (? prefix)."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("abc\n")
        file2.write_text("aXc\n")

        result = compare_files(str(file1), str(file2))

        # Differ produces ? lines for intraline differences
        assert "?" in result
        assert "abc" in result
        assert "aXc" in result

    def test_no_differences_returns_separator_only(self, tmp_path):
        """Test that files with no differences return only the separator.

        Note: The source has a bug where len(result) == 2 is checked,
        but result starts as ["---"] (len 1), so "Files are identical"
        is never appended. This test documents the actual behavior.
        """
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("same content\n")
        file2.write_text("same content\n")

        result = compare_files(str(file1), str(file2))

        assert result == "---"
        assert "Files are identical" not in result


class TestFormatDiffBlock:
    """Test format_diff_block function."""

    def test_basic_formatting(self):
        """Test basic diff block formatting."""
        block = [
            (2, "- removed_line\n"),
            (3, "+ added_line\n"),
        ]

        result = format_diff_block(block, context_lines=1)

        assert any("-" in line and "removed_line" in line for line in result)
        assert any("+" in line and "added_line" in line for line in result)
        assert "---" in result

    def test_question_mark_prefix(self):
        """Test formatting with question mark prefix lines."""
        block = [
            (1, "? ^^^^\n"),
        ]

        result = format_diff_block(block, context_lines=0)

        assert any("?" in line for line in result)
        assert "---" in result

    def test_differ_question_mark_lines(self, tmp_path):
        """Test format_diff_block with actual Differ ? prefix change indicators."""
        block = [
            (0, "- abc\n"),
            (1, "?  ^\n"),
            (2, "+ aXc\n"),
            (3, "?  ^\n"),
        ]

        result = format_diff_block(block, context_lines=0)

        # Verify all prefixes are preserved
        assert any(line.startswith("-") and "abc" in line for line in result)
        assert any(line.startswith("?") and "^" in line for line in result)
        assert any(line.startswith("+") and "aXc" in line for line in result)
        assert "---" in result

    def test_empty_block(self):
        """Test formatting an empty block raises IndexError."""
        # Source code accesses block[0] unconditionally, so empty block crashes
        with pytest.raises(IndexError):
            format_diff_block([], context_lines=3)

    def test_context_lines_included(self):
        """Test that context lines are included in output."""
        block = [
            (5, "- changed\n"),
        ]

        result = format_diff_block(block, context_lines=2)

        # Result should contain the diff line
        assert any("changed" in line for line in result)
        assert "---" in result

    def test_line_number_formatting(self):
        """Test that line numbers are properly formatted."""
        block = [
            (0, "- first\n"),
            (1, "+ second\n"),
        ]

        result = format_diff_block(block, context_lines=0)

        # Check line numbers are present (1-based)
        assert any("1|" in line for line in result)
        assert any("2|" in line for line in result)

    def test_rstrip_handling(self):
        """Test that trailing newlines are stripped from line content."""
        block = [
            (0, "- line_with_newline\n"),
        ]

        result = format_diff_block(block, context_lines=0)

        # The raw line should not contain trailing newline in output
        diff_line = [line for line in result if "line_with_newline" in line][0]
        assert not diff_line.endswith("\n\n")

    def test_short_line_handling(self):
        """Test handling of very short diff lines."""
        block = [
            (0, "- \n"),
        ]

        result = format_diff_block(block, context_lines=0)

        # Should not crash and should contain the line
        assert any("-" in line for line in result)


class TestGetUnifiedDiff:
    """Test get_unified_diff function."""

    def test_identical_files(self, tmp_path):
        """Test unified diff of identical files."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("line1\nline2\nline3\n")
        file2.write_text("line1\nline2\nline3\n")

        result = get_unified_diff(str(file1), str(file2))

        # Unified diff of identical files returns empty string
        assert result == ""

    def test_different_files(self, tmp_path):
        """Test unified diff of different files."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("line1\nline2\nline3\n")
        file2.write_text("line1\nmodified\nline3\n")

        result = get_unified_diff(str(file1), str(file2))

        assert "---" in result
        assert "+++" in result
        assert "@@" in result
        assert "modified" in result

    def test_file_not_found(self, tmp_path):
        """Test unified diff when file does not exist raises FileNotFoundError."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("line1\n")

        with pytest.raises(FileNotFoundError):
            get_unified_diff(str(file1), str(tmp_path / "nonexistent.txt"))

    def test_both_files_not_found(self, tmp_path):
        """Test unified diff when both files do not exist raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            get_unified_diff(
                str(tmp_path / "nonexistent1.txt"),
                str(tmp_path / "nonexistent2.txt")
            )

    def test_empty_files(self, tmp_path):
        """Test unified diff of two empty files."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("")
        file2.write_text("")

        result = get_unified_diff(str(file1), str(file2))

        assert result == ""

    def test_one_empty_file(self, tmp_path):
        """Test unified diff with one empty file."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("")
        file2.write_text("line1\nline2\n")

        result = get_unified_diff(str(file1), str(file2))

        assert "+++" in result
        assert "line1" in result
        assert "line2" in result

    def test_multiple_changes(self, tmp_path):
        """Test unified diff with multiple changes."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text(
            "a\n"
            "b\n"
            "c\n"
            "d\n"
            "e\n"
        )
        file2.write_text(
            "a\n"
            "b_modified\n"
            "c\n"
            "d_modified\n"
            "e\n"
        )

        result = get_unified_diff(str(file1), str(file2))

        assert "b_modified" in result
        assert "d_modified" in result
        assert "@@" in result

    def test_unicode_content(self, tmp_path):
        """Test unified diff with unicode content."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("hello\n世界\n")
        file2.write_text("hello\nuniverse\n")

        result = get_unified_diff(str(file1), str(file2))

        assert "universe" in result
        assert "---" in result
        assert "+++" in result

    def test_single_line_files(self, tmp_path):
        """Test unified diff with single-line files."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("old\n")
        file2.write_text("new\n")

        result = get_unified_diff(str(file1), str(file2))

        assert "old" in result
        assert "new" in result
        assert "@@" in result

    def test_returns_string(self, tmp_path):
        """Test that get_unified_diff returns a string."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("a\n")
        file2.write_text("b\n")

        result = get_unified_diff(str(file1), str(file2))

        assert isinstance(result, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
