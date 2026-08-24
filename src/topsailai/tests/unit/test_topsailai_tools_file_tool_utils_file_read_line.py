import pytest

from topsailai.tools.file_tool_utils.file_read_line import (
    read_file_with_context,
    read_file_around_line,
    read_file_lines,
    TOOLS,
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

    def test_case_sensitive_true_string(self, tmp_path):
        """Test case_sensitive with string 'true' input handling."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("LINE1\nLine2\nline3\n")

        result = read_file_with_context(str(test_file), "line1", context_num=0, case_sensitive="true")
        assert result == ""  # No match because case doesn't match

    def test_case_sensitive_false_string(self, tmp_path):
        """Test case_sensitive with string 'false' input handling."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("LINE1\nLine2\nline3\n")

        result = read_file_with_context(str(test_file), "line1", context_num=0, case_sensitive="false")
        assert "1:LINE1" in result  # Match found because case insensitive

    def test_context_num_zero(self, tmp_path):
        """Test context_num=0 returns only matching lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        result = read_file_with_context(str(test_file), "line3", context_num=0)
        lines = result.split("\n")

        assert len(lines) == 1
        assert lines[0] == "3:line3"

    def test_mixed_line_endings(self, tmp_path):
        """Test mixed line endings are handled transparently."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"line1\nline2\r\nline3\rline4\n")

        result = read_file_with_context(str(test_file), "line3", context_num=1)
        lines = result.split("\n")

        assert len(lines) == 3
        assert lines[0] == "2-line2"
        assert lines[1] == "3:line3"
        assert lines[2] == "4-line4"

    def test_utf8_bom_encoding(self, tmp_path):
        """Test UTF-8 BOM file is decoded and split correctly.

        The BOM byte sequence is preserved as part of the first line's content,
        matching the behavior of the original full-file chardet decode path.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_bytes("\ufeffline1\nline2\nline3\n".encode("utf-8-sig"))

        result = read_file_with_context(str(test_file), "line2", context_num=1)
        lines = result.split("\n")

        assert len(lines) == 3
        assert lines[0] == "1-\ufeffline1"
        assert lines[1] == "2:line2"
        assert lines[2] == "3-line3"

    def test_overlapping_matches_large_context(self, tmp_path):
        """Test multiple close matches with overlapping contexts."""
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

        result = read_file_with_context(str(test_file), "line[35]", context_num=2)
        lines = result.split("\n")

        # Should include all lines from 1 to 7 without duplication
        assert len(lines) == 7
        assert lines[0] == "1-line1"
        assert lines[1] == "2-line2"
        assert lines[2] == "3:line3"
        assert lines[3] == "4-line4"
        assert lines[4] == "5:line5"
        assert lines[5] == "6-line6"
        assert lines[6] == "7-line7"


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

    def test_context_num_zero(self, tmp_path):
        """Test context_num=0 returns only the target line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5\n")

        result = read_file_around_line(str(test_file), 3, context_num=0)
        lines = result.split("\n")

        assert len(lines) == 1
        assert lines[0] == "3:line3"

    def test_crlf_line_endings(self, tmp_path):
        """Test CRLF line endings are handled transparently."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"line1\r\nline2\r\nline3\r\n")

        result = read_file_around_line(str(test_file), 2, context_num=1)
        lines = result.split("\n")

        assert len(lines) == 3
        assert lines[0] == "1-line1"
        assert lines[1] == "2:line2"
        assert lines[2] == "3-line3"

    def test_gbk_encoding(self, tmp_path):
        """Test GBK encoded file is decoded correctly."""
        test_file = tmp_path / "test.txt"
        content = "第一行\n第二行\n第三行\n".encode("gbk")
        test_file.write_bytes(content)

        result = read_file_around_line(str(test_file), 2, context_num=1)
        lines = result.split("\n")

        assert len(lines) == 3
        assert lines[0] == "1-第一行"
        assert lines[1] == "2:第二行"
        assert lines[2] == "3-第三行"

    def test_unicode_multibyte(self, tmp_path):
        """Test Unicode multibyte characters across lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("emoji: 🚀\n中文: 测试\n\n")

        result = read_file_around_line(str(test_file), 2, context_num=1)
        lines = result.split("\n")

        assert len(lines) == 3
        assert lines[0] == "1-emoji: 🚀"
        assert lines[1] == "2:中文: 测试"
        assert lines[2] == "3-"


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

    def test_leading_dash_not_counted_as_content(self, tmp_path):
        """Verify the first '-' after the line number is the separator.

        A line that contains only three dashes must be rendered as
        ``109----`` (line 109, separator '-', content '---'), not as a
        line with four dashes.
        """
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\n---\nbbb\n")

        result = read_file_lines(str(test_file), 1, 3)
        lines = result.split("\n")

        assert len(lines) == 3
        assert lines[0] == "1-aaa"
        assert lines[1] == "2----"
        assert lines[2] == "3-bbb"

    def test_leading_dash_with_context(self, tmp_path):
        """Verify separator semantics in read_file_with_context."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\n---\nbbb\n")

        result = read_file_with_context(str(test_file), r"^---$", context_num=1)
        lines = result.split("\n")

        assert len(lines) == 3
        assert lines[0] == "1-aaa"
        assert lines[1] == "2:---"
        assert lines[2] == "3-bbb"

    def test_leading_dash_around_line(self, tmp_path):
        """Verify separator semantics in read_file_around_line."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\n---\nbbb\n")

        result = read_file_around_line(str(test_file), 2, context_num=1)
        lines = result.split("\n")

        assert len(lines) == 3
        assert lines[0] == "1-aaa"
        assert lines[1] == "2:---"
        assert lines[2] == "3-bbb"

    def test_start_num_zero(self, tmp_path):
        """Test start_num=0 is treated as 1."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), 0, 2)
        lines = result.split("\n")

        assert len(lines) == 2
        assert "1-line1" in lines[0]
        assert "2-line2" in lines[1]

    def test_string_numeric_inputs(self, tmp_path):
        """Test string numeric inputs for start_num and end_num."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), "2", "3")
        lines = result.split("\n")

        assert len(lines) == 2
        assert "2-line2" in lines[0]
        assert "3-line3" in lines[1]

    def test_end_num_zero(self, tmp_path):
        """Test end_num=0 reads to end of file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), 1, 0)
        lines = result.split("\n")

        assert len(lines) == 3
        assert "1-line1" in lines[0]
        assert "2-line2" in lines[1]
        assert "3-line3" in lines[2]

    def test_start_after_eof(self, tmp_path):
        """Test start_num beyond file length returns empty."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n")

        result = read_file_lines(str(test_file), 10, 15)
        assert result == ""

    def test_cr_line_endings(self, tmp_path):
        """Test CR-only line endings are handled transparently."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"line1\rline2\rline3\r")

        result = read_file_lines(str(test_file), 2, 2)
        lines = result.split("\n")

        assert len(lines) == 1
        assert lines[0] == "2-line2"

    def test_latin1_encoding(self, tmp_path):
        """Test Latin-1 encoded file is decoded correctly."""
        test_file = tmp_path / "test.txt"
        content = "café\nnaïve\nseñor\n".encode("latin-1")
        test_file.write_bytes(content)

        result = read_file_lines(str(test_file), 2, 2)
        lines = result.split("\n")

        assert len(lines) == 1
        assert lines[0] == "2-naïve"


class TestTools:
    """Test TOOLS dictionary."""

    def test_tools_contains_expected_keys(self):
        """Verify TOOLS dictionary contains expected keys."""
        assert "read_file_around_line" in TOOLS
        assert "read_file_lines" in TOOLS
        assert "read_file_with_context" in TOOLS
        assert len(TOOLS) == 3


@pytest.fixture(scope="session")
def large_file(tmp_path_factory):
    """Create a large file once per test session."""
    tmp_dir = tmp_path_factory.mktemp("large_file")
    test_file = tmp_dir / "large.txt"
    total = 1_000_000
    with open(test_file, "w", encoding="utf-8") as fd:
        for i in range(1, total + 1):
            fd.write(f"line{i}\n")
    return test_file


class TestLargeFileStreaming:
    """Test streaming behavior with large files."""

    def test_read_file_around_line_large_line_number(self, large_file):
        """Early-stop should make reading a window near EOF fast and correct."""
        total = 1_000_000
        result = read_file_around_line(str(large_file), total, context_num=2)
        lines = result.split("\n")

        assert len(lines) == 3
        assert f"{total - 2}-line{total - 2}" in lines[0]
        assert f"{total - 1}-line{total - 1}" in lines[1]
        assert f"{total}:line{total}" in lines[2]

    def test_read_file_lines_large_file_end_window(self, large_file):
        """Reading a small range near the end of a large file should work."""
        total = 1_000_000
        result = read_file_lines(str(large_file), total - 2, total)
        lines = result.split("\n")

        assert len(lines) == 3
        assert f"{total - 2}-line{total - 2}" in lines[0]
        assert f"{total - 1}-line{total - 1}" in lines[1]
        assert f"{total}-line{total}" in lines[2]

    def test_read_file_with_context_large_file_rolling_window(self, large_file):
        """Rolling-window regex search should find matches in a large file."""
        total = 1_000_000
        target = 999_998
        result = read_file_with_context(
            str(large_file), f"line{target}", context_num=2
        )
        lines = result.split("\n")

        assert len(lines) == 5
        assert f"{target - 2}-line{target - 2}" in lines[0]
        assert f"{target - 1}-line{target - 1}" in lines[1]
        assert f"{target}:line{target}" in lines[2]
        assert f"{target + 1}-line{target + 1}" in lines[3]
        assert f"{target + 2}-line{target + 2}" in lines[4]

    def test_read_file_with_context_no_match_large_file(self, large_file):
        """Rolling-window search with no match should return empty quickly."""
        result = read_file_with_context(str(large_file), "NOT_IN_FILE", context_num=2)
        assert result == ""


class TestDocumentedStreamingHelpers:
    """Test the documented streaming and decoding helpers directly."""

    def test_detect_encoding_defaults_to_utf8_for_empty_or_unknown_sample(self):
        """Empty input and undetected encodings fall back to UTF-8."""
        from unittest.mock import patch
        from topsailai.tools.file_tool_utils.file_read_line import _detect_encoding

        assert _detect_encoding(b"") == "utf-8"
        with patch(
            "topsailai.tools.file_tool_utils.file_read_line.chardet.detect",
            return_value={"encoding": None},
        ):
            assert _detect_encoding(b"sample") == "utf-8"

    def test_detect_encoding_returns_detector_result(self):
        """A detector-provided encoding is returned unchanged."""
        from unittest.mock import patch
        from topsailai.tools.file_tool_utils.file_read_line import _detect_encoding

        with patch(
            "topsailai.tools.file_tool_utils.file_read_line.chardet.detect",
            return_value={"encoding": "ISO-8859-1"},
        ):
            assert _detect_encoding(b"sample") == "ISO-8859-1"

    @pytest.mark.parametrize(
        ("line", "expected"),
        [("a\r\n", "a"), ("a\n", "a"), ("a\r", "a"), ("a", "a")],
    )
    def test_strip_line_ending_handles_supported_endings(self, line, expected):
        """CRLF, LF, and CR are stripped while unterminated text is preserved."""
        from topsailai.tools.file_tool_utils.file_read_line import _strip_line_ending

        assert _strip_line_ending(line) == expected

    def test_open_text_stream_detects_encoding_rewinds_and_closes(self, tmp_path):
        """The context manager decodes from the beginning and closes its wrapper."""
        from topsailai.tools.file_tool_utils.file_read_line import _open_text_stream

        target = tmp_path / "latin1.txt"
        target.write_bytes(b"caf\xe9\nsecond\n")
        with _open_text_stream(str(target)) as stream:
            assert list(stream) == ["caf\xe9\n", "second\n"]
        assert stream.closed is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
