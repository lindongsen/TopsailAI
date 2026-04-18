
import pytest

from topsailai.tools.file_tool_utils.file_read_line import (
    read_file_with_context,
    read_file_around_line,
    read_file_lines,
)


class TestReadFileWithContext:
    """Test read_file_with_context function."""

    def test_basic_match(self, tmp_path):
        """Test basic pattern matching with context."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = read_file_with_context(str(test_file), "line3", context_num=1)
        lines = result.split("\n")

        assert len(lines) == 3
        assert "2-line2" in lines[0]
        assert "3:line3" in lines[1]  # Match marked with ':'
        assert "4-line4" in lines[2]

    def test_multiple_matches(self, tmp_path):
        """Test multiple matches with overlapping context."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
            "line6\n"
            "line7\n"
        )

        result = read_file_with_context(str(test_file), "line[35]", context_num=1)
        lines = result.split("\n")

        # Should include context for both matches without duplication
        assert any("3:line3" in l for l in lines)
        assert any("5:line5" in l for l in lines)
        assert any("4-line4" in l for l in lines)  # Shared context

    def test_no_match(self, tmp_path):
        """Test when pattern doesn't match anything."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_with_context(str(test_file), "notfound")
        assert result == ""

    def test_case_insensitive_by_default(self, tmp_path):
        """Test that search is case insensitive by default."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("LINE1\nLine2\nline3\n")

        result = read_file_with_context(str(test_file), "line1", context_num=0)
        assert "1:LINE1" in result

    def test_case_sensitive(self, tmp_path):
        """Test case sensitive search."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("LINE1\nLine2\nline3\n")

        result = read_file_with_context(str(test_file), "line1", context_num=0, case_sensitive=True)
        assert result == ""  # No match because case doesn't match

    def test_context_at_file_beginning(self, tmp_path):
        """Test context lines at the beginning of file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_with_context(str(test_file), "line1", context_num=2)
        lines = result.split("\n")

        # Should not go before line 1
        assert lines[0] == "1:line1"
        assert "2-line2" in lines[1]
        assert "3-line3" in lines[2]

    def test_context_at_file_end(self, tmp_path):
        """Test context lines at the end of file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_with_context(str(test_file), "line3", context_num=2)
        lines = result.split("\n")

        # Should not go after last line
        assert "1-line1" in lines[0]
        assert "2-line2" in lines[1]
        assert "3:line3" in lines[2]

    def test_file_not_found(self, tmp_path):
        """Test when file doesn't exist."""
        result = read_file_with_context(str(tmp_path / "nonexistent.txt"), "pattern")
        assert result.startswith("Error: File not found:")

    def test_invalid_regex_pattern(self, tmp_path):
        """Test with invalid regex pattern."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\n")

        result = read_file_with_context(str(test_file), "[invalid", context_num=0)
        assert result.startswith("Error: Invalid regex pattern")

    def test_empty_file(self, tmp_path):
        """Test with empty file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        result = read_file_with_context(str(test_file), "pattern")
        assert result == ""

    def test_large_context(self, tmp_path):
        """Test with context_num larger than file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_with_context(str(test_file), "line2", context_num=100)
        lines = result.split("\n")

        # Should show all lines
        assert len(lines) == 3
        assert "1-line1" in lines[0]
        assert "2:line2" in lines[1]
        assert "3-line3" in lines[2]

    def test_regex_pattern(self, tmp_path):
        """Test with regex pattern."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("abc123\nxyz789\nabc456\n")

        result = read_file_with_context(str(test_file), r"abc\d+", context_num=0)
        lines = result.split("\n")

        assert len(lines) == 2
        assert "1:abc123" in lines[0]
        assert "3:abc456" in lines[1]


class TestReadFileAroundLine:
    """Test read_file_around_line function."""

    def test_basic_around_line(self, tmp_path):
        """Test reading around a specific line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = read_file_around_line(str(test_file), 3, context_num=1)
        lines = result.split("\n")

        assert len(lines) == 3
        assert "2-line2" in lines[0]
        assert "3:line3" in lines[1]  # Target marked with ':'
        assert "4-line4" in lines[2]

    def test_line_at_beginning(self, tmp_path):
        """Test reading around first line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_around_line(str(test_file), 1, context_num=2)
        lines = result.split("\n")

        assert lines[0] == "1:line1"
        assert "2-line2" in lines[1]
        assert "3-line3" in lines[2]

    def test_line_at_end(self, tmp_path):
        """Test reading around last line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_around_line(str(test_file), 3, context_num=2)
        lines = result.split("\n")

        assert "1-line1" in lines[0]
        assert "2-line2" in lines[1]
        assert "3:line3" in lines[2]

    def test_line_out_of_range(self, tmp_path):
        """Test with line number out of range."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_around_line(str(test_file), 10, context_num=2)
        assert "out of range" in result

    def test_negative_line_number(self, tmp_path):
        """Test with negative line number."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_around_line(str(test_file), -1, context_num=2)
        assert "out of range" in result

    def test_file_not_found(self, tmp_path):
        """Test when file doesn't exist."""
        result = read_file_around_line(str(tmp_path / "nonexistent.txt"), 1, context_num=2)
        assert result.startswith("Error: File not found:")

    def test_empty_file(self, tmp_path):
        """Test with empty file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        result = read_file_around_line(str(test_file), 1, context_num=2)
        assert result == ""

    def test_large_context(self, tmp_path):
        """Test with context_num larger than file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_around_line(str(test_file), 2, context_num=100)
        lines = result.split("\n")

        assert len(lines) == 3
        assert "1-line1" in lines[0]
        assert "2:line2" in lines[1]
        assert "3-line3" in lines[2]


class TestReadFileLines:
    """Test read_file_lines function."""

    def test_basic_range(self, tmp_path):
        """Test reading a specific range of lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text(
            "line1\n"
            "line2\n"
            "line3\n"
            "line4\n"
            "line5\n"
        )

        result = read_file_lines(str(test_file), 2, 4)
        lines = result.split("\n")

        assert len(lines) == 3
        assert "2-line2" in lines[0]
        assert "3-line3" in lines[1]
        assert "4-line4" in lines[2]

    def test_single_line(self, tmp_path):
        """Test reading a single line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), 2, 2)
        lines = result.split("\n")

        assert len(lines) == 1
        assert "2-line2" in lines[0]

    def test_range_at_beginning(self, tmp_path):
        """Test reading from the beginning."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), 1, 2)
        lines = result.split("\n")

        assert len(lines) == 2
        assert "1-line1" in lines[0]
        assert "2-line2" in lines[1]

    def test_range_at_end(self, tmp_path):
        """Test reading at the end."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), 2, 3)
        lines = result.split("\n")

        assert len(lines) == 2
        assert "2-line2" in lines[0]
        assert "3-line3" in lines[1]

    def test_invalid_range(self, tmp_path):
        """Test with invalid range (start > end)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), 5, 2)
        assert "Invalid range" in result

    def test_file_not_found(self, tmp_path):
        """Test when file doesn't exist."""
        result = read_file_lines(str(tmp_path / "nonexistent.txt"), 1, 5)
        assert result.startswith("Error: File not found:")

    def test_empty_file(self, tmp_path):
        """Test with empty file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("")

        result = read_file_lines(str(test_file), 1, 5)
        assert result == ""

    def test_range_exceeds_file(self, tmp_path):
        """Test when range exceeds file length."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), 1, 100)
        lines = result.split("\n")

        # Should return all available lines
        assert len(lines) == 3

    def test_all_lines_use_dash_marker(self, tmp_path):
        """Test that all lines in range use '-' marker."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), 1, 3)
        lines = result.split("\n")

        # All lines should use '-' marker
        for line in lines:
            assert "-" in line
            assert ":" not in line  # No ':' marker


if __name__ == "__main__":
    pytest.main([__file__, "-v"])