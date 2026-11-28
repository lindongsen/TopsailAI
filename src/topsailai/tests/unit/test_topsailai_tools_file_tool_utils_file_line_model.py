#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Unit tests for file_line_model.

The module exists because the write tools and the read tool disagreed on what a
line is. These tests pin the shared model against the read tool's behaviour, so
a future change to either side cannot silently reintroduce the divergence.
'''

import io

import pytest

from topsailai.tools.file_tool_utils import file_line_model


# Characters that str.splitlines() treats as line boundaries but the read tool
# (io.TextIOWrapper with universal newlines) does not.
NON_UNIVERSAL_SEPARATORS = [
    ("\x0b", "vertical tab"),
    ("\x0c", "form feed"),
    ("\x1c", "file separator"),
    ("\x1d", "group separator"),
    ("\x1e", "record separator"),
    ("\x85", "next line"),
    ("\u2028", "line separator"),
    ("\u2029", "paragraph separator"),
]

UNIVERSAL_SEPARATORS = [
    ("\n", "LF"),
    ("\r", "CR"),
    ("\r\n", "CRLF"),
]


def _read_tool_line_count(text: str) -> int:
    """Count lines the way the read tool does, through a real text wrapper."""
    return len(io.StringIO(text, newline=None).readlines())


class TestSplitLinesAgreesWithReadTool:
    """split_lines must count lines exactly as the read tool reports them."""

    @pytest.mark.parametrize("separator,label", UNIVERSAL_SEPARATORS)
    def test_universal_separator_is_a_boundary(self, separator, label):
        """LF, CR and CRLF are line boundaries for both sides."""
        text = f"a{separator}b{separator}c{separator}"

        lines = file_line_model.split_lines(text)

        assert len(lines) == 3, f"{label} must produce 3 lines"
        assert len(lines) == _read_tool_line_count(text)

    @pytest.mark.parametrize("separator,label", NON_UNIVERSAL_SEPARATORS)
    def test_non_universal_separator_is_not_a_boundary(self, separator, label):
        """The eight extra str.splitlines characters must not split a line."""
        text = f"a{separator}b\nc\n"

        lines = file_line_model.split_lines(text)

        assert len(lines) == 2, f"{label} must not create a line boundary"
        assert len(lines) == _read_tool_line_count(text)

    @pytest.mark.parametrize("separator,label", NON_UNIVERSAL_SEPARATORS)
    def test_splitlines_would_disagree(self, separator, label):
        """Negative control: str.splitlines really does count differently."""
        text = f"a{separator}b\nc\n"

        assert len(text.splitlines()) == 3, (
            f"{label} is a str.splitlines boundary, which is why the shared "
            "model cannot use str.splitlines"
        )
        assert len(file_line_model.split_lines(text)) == 2


class TestSplitLinesPreservesEndings:
    """Every line ending must survive splitting byte for byte."""

    @pytest.mark.parametrize("separator,label", UNIVERSAL_SEPARATORS)
    def test_ending_is_kept(self, separator, label):
        """The separator stays attached to its line."""
        text = f"a{separator}b{separator}"

        lines = file_line_model.split_lines(text)

        assert lines == [f"a{separator}", f"b{separator}"], label

    def test_mixed_endings_are_kept_individually(self):
        """A file with mixed endings keeps each one."""
        text = "a\r\nb\nc\rd"

        lines = file_line_model.split_lines(text)

        assert lines == ["a\r\n", "b\n", "c\r", "d"]

    def test_round_trip_is_byte_identical(self):
        """Joining the split lines reproduces the input exactly."""
        text = "a\r\nb\nc\rd\x0ce\r\n"

        assert "".join(file_line_model.split_lines(text)) == text


class TestSplitLinesEdgeCases:
    """Boundary shapes that a write tool must not mis-count."""

    def test_empty_text_yields_no_lines(self):
        """An empty file has zero lines, not one empty line."""
        assert file_line_model.split_lines("") == []

    def test_single_line_without_ending(self):
        """A file with no trailing newline is one line."""
        assert file_line_model.split_lines("a") == ["a"]

    def test_trailing_newline_does_not_add_empty_line(self):
        """A trailing newline terminates the last line, it does not add one."""
        assert file_line_model.split_lines("a\n") == ["a\n"]

    def test_only_newlines(self):
        """A file of newlines is one line per newline."""
        assert file_line_model.split_lines("\n\n") == ["\n", "\n"]

    def test_blank_line_in_the_middle_is_kept(self):
        """A blank line is a real line and must keep its position."""
        assert file_line_model.split_lines("a\n\nb\n") == ["a\n", "\n", "b\n"]


class TestLineEndingOf:
    """line_ending_of must return the ending only, never trailing whitespace."""

    @pytest.mark.parametrize(
        "line,expected",
        [
            ("a\r\n", "\r\n"),
            ("a\n", "\n"),
            ("a\r", "\r"),
            ("a", ""),
            ("", ""),
        ],
    )
    def test_plain_endings(self, line, expected):
        """Each ending form is reported exactly."""
        assert file_line_model.line_ending_of(line) == expected

    def test_trailing_spaces_are_not_part_of_the_ending(self):
        """rstrip() would return '  \\n' here and inject the spaces."""
        assert file_line_model.line_ending_of("b  \n") == "\n"

    def test_trailing_tab_is_not_part_of_the_ending(self):
        """A tab before the newline belongs to the content, not the ending."""
        assert file_line_model.line_ending_of("b\t\n") == "\n"

    def test_trailing_spaces_without_ending(self):
        """Content with trailing spaces and no ending has no ending."""
        assert file_line_model.line_ending_of("b  ") == ""

    def test_crlf_after_trailing_spaces(self):
        """CRLF is detected even when spaces precede it."""
        assert file_line_model.line_ending_of("b  \r\n") == "\r\n"

    def test_rstrip_would_disagree(self):
        """Negative control: the old expression returns the spaces too."""
        line = "b  \n"

        assert line[len(line.rstrip()):] == "  \n"
        assert file_line_model.line_ending_of(line) == "\n"


class TestReadWriteText:
    """read_text and write_text must not translate line endings."""

    def test_write_then_read_preserves_crlf(self, tmp_path):
        """A CRLF file survives a write/read round trip."""
        path = tmp_path / "crlf.txt"

        file_line_model.write_text(str(path), "a\r\nb\r\n")

        assert path.read_bytes() == b"a\r\nb\r\n"
        assert file_line_model.read_text(str(path)) == "a\r\nb\r\n"

    def test_write_then_read_preserves_cr_only(self, tmp_path):
        """A CR-only file survives a write/read round trip."""
        path = tmp_path / "cr.txt"

        file_line_model.write_text(str(path), "a\rb\r")

        assert path.read_bytes() == b"a\rb\r"
        assert file_line_model.read_text(str(path)) == "a\rb\r"

    def test_read_does_not_translate_mixed_endings(self, tmp_path):
        """Mixed endings are returned unchanged."""
        path = tmp_path / "mixed.txt"
        path.write_bytes(b"a\r\nb\nc\rd")

        assert file_line_model.read_text(str(path)) == "a\r\nb\nc\rd"

    def test_default_newline_would_translate(self, tmp_path):
        """Negative control: the default open() flattens every ending."""
        path = tmp_path / "mixed.txt"
        path.write_bytes(b"a\r\nb\nc\rd")

        with open(str(path), "r", encoding="utf-8") as handle:
            translated = handle.read()

        assert translated == "a\nb\nc\nd"
        assert file_line_model.read_text(str(path)) == "a\r\nb\nc\rd"

    def test_write_preserves_utf8_content(self, tmp_path):
        """Non-ASCII content is written as UTF-8."""
        path = tmp_path / "utf8.txt"

        file_line_model.write_text(str(path), "中文\r\n")

        assert path.read_bytes() == "中文\r\n".encode("utf-8")
        assert file_line_model.read_text(str(path)) == "中文\r\n"

    def test_write_empty_text(self, tmp_path):
        """An empty write produces an empty file."""
        path = tmp_path / "empty.txt"

        file_line_model.write_text(str(path), "")

        assert path.read_bytes() == b""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
