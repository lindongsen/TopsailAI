import pytest
import chardet
from io import StringIO
import sys
from topsailai.utils.text_tool import safe_decode, check_repetition, print_repetition_report


def test_safe_decode_string_input():
    """Test that string input is returned unchanged."""
    input_str = "hello world"
    result = safe_decode(input_str)
    assert result == input_str


def test_safe_decode_empty_string():
    """Test that empty string input is returned unchanged."""
    result = safe_decode("")
    assert result == ""


def test_safe_decode_none_input():
    """Test that None input returns empty string."""
    result = safe_decode(None)
    assert result == ""


def test_safe_decode_utf8_bytes():
    """Test decoding UTF-8 encoded bytes."""
    test_bytes = "hello world".encode('utf-8')
    result = safe_decode(test_bytes)
    assert result == "hello world"


def test_safe_decode_latin1_bytes():
    """Test decoding Latin-1 encoded bytes."""
    test_bytes = "café".encode('latin-1')
    result = safe_decode(test_bytes)
    assert result == "café"


def test_safe_decode_with_special_characters():
    """Test decoding bytes with special characters."""
    test_bytes = "hello café world".encode('utf-8')
    result = safe_decode(test_bytes)
    assert result == "hello café world"


def test_safe_decode_invalid_bytes_fallback():
    """Test that invalid bytes fall back to UTF-8 with replacement."""
    # Create some invalid UTF-8 bytes
    invalid_bytes = b'\xff\xfehello'
    result = safe_decode(invalid_bytes)
    # Should not raise an exception and should return a string
    assert isinstance(result, str)
    assert len(result) > 0


def test_safe_decode_empty_bytes():
    """Test decoding empty bytes."""
    result = safe_decode(b'')
    assert result == ""


def test_safe_decode_consistency():
    """Test that the function behaves consistently."""
    test_cases = [
        "hello",
        "",
        "café",
        "hello world with spaces",
        b'hello',
        b'',
    ]

    for case in test_cases:
        result1 = safe_decode(case)
        result2 = safe_decode(case)
        assert result1 == result2


# ============================================
# Tests for check_repetition
# ============================================

class TestCheckRepetition:
    """Tests for the check_repetition function."""

    def test_empty_text(self):
        """Test with empty text input."""
        result = check_repetition("")
        assert result["status"] == "no_content"
        assert result["total_lines"] == 0
        assert result["exact_duplicate_count"] == 0
        assert result["fuzzy_duplicate_count"] == 0
        assert result["repetition_rate"] == 0.0
        assert result["exact_duplicates"] == {}
        assert result["fuzzy_duplicates"] == []
        assert result["has_severe_repetition"] is False

    def test_whitespace_only_text(self):
        """Test with whitespace-only text."""
        result = check_repetition("   \n\n   \n\n")
        assert result["status"] == "no_content"
        assert result["total_lines"] == 0

    def test_single_line(self):
        """Test with single line text (no duplicates possible)."""
        result = check_repetition("Hello world")
        assert result["status"] == "analyzed"
        assert result["total_lines"] == 1
        assert result["exact_duplicate_count"] == 0
        assert result["fuzzy_duplicate_count"] == 0
        assert result["repetition_rate"] == 0.0
        assert result["has_severe_repetition"] is False

    def test_no_duplicates(self):
        """Test text with all unique and dissimilar lines."""
        # Use lines that are truly dissimilar (not just "Line 1", "Line 2", etc.)
        text = "Apple\nBanana\nCherry"
        result = check_repetition(text)
        assert result["status"] == "analyzed"
        assert result["total_lines"] == 3
        assert result["exact_duplicate_count"] == 0
        assert result["fuzzy_duplicate_count"] == 0
        assert result["repetition_rate"] == 0.0
        assert result["has_severe_repetition"] is False

    def test_exact_duplicates(self):
        """Test text with exact duplicate lines."""
        text = "Hello\nWorld\nHello\nHello"
        result = check_repetition(text)
        assert result["status"] == "analyzed"
        assert result["total_lines"] == 4
        assert result["exact_duplicate_count"] == 2  # Two duplicates of "Hello"
        assert result["fuzzy_duplicate_count"] == 0
        assert "Hello" in result["exact_duplicates"]
        assert result["exact_duplicates"]["Hello"] == 2  # "Hello" appears 2 extra times
        assert result["has_severe_repetition"] is True  # 2/4 = 50% > 30%

    def test_exact_duplicate_count_accuracy(self):
        """Test that exact duplicate count is accurate."""
        text = "A\nB\nA\nA\nA"
        result = check_repetition(text)
        assert result["exact_duplicate_count"] == 3  # Three duplicates of "A"
        assert result["exact_duplicates"]["A"] == 3

    def test_fuzzy_duplicates(self):
        """Test text with fuzzy duplicate lines (high similarity)."""
        # Lines with high similarity (> 0.8 by default)
        text = "Hello world\nHello word\nGoodbye"
        result = check_repetition(text, similarity_threshold=0.8)
        assert result["status"] == "analyzed"
        assert result["total_lines"] == 3
        assert result["fuzzy_duplicate_count"] >= 1  # "Hello word" is similar to "Hello world"
        # Check that fuzzy duplicate info is correct
        if result["fuzzy_duplicates"]:
            fuzzy = result["fuzzy_duplicates"][0]
            assert "index" in fuzzy
            assert "line" in fuzzy
            assert "matched_line" in fuzzy
            assert "similarity" in fuzzy

    def test_fuzzy_duplicate_similarity_value(self):
        """Test that similarity values are correctly calculated."""
        text = "abcdef\nabcdeg"
        result = check_repetition(text, similarity_threshold=0.5)
        assert result["fuzzy_duplicate_count"] == 1
        assert result["fuzzy_duplicates"][0]["similarity"] > 0.5

    def test_custom_similarity_threshold(self):
        """Test with custom similarity threshold."""
        text = "Hello world\nHello word"
        # With high threshold, no fuzzy duplicates
        result_high = check_repetition(text, similarity_threshold=0.99)
        # With low threshold, fuzzy duplicates detected
        result_low = check_repetition(text, similarity_threshold=0.5)
        assert result_high["fuzzy_duplicate_count"] <= result_low["fuzzy_duplicate_count"]

    def test_mixed_exact_and_fuzzy_duplicates(self):
        """Test text with both exact and fuzzy duplicates."""
        text = "Hello\nWorld\nHello\nWorlde\nHello"
        result = check_repetition(text, similarity_threshold=0.5)
        assert result["status"] == "analyzed"
        assert result["exact_duplicate_count"] >= 2  # At least 2 exact duplicates of "Hello"
        # "Worlde" might be fuzzy match with "World"
        assert result["total_lines"] == 5

    def test_severe_repetition_threshold(self):
        """Test that has_severe_repetition is True when rate > 30%."""
        # 4 lines, 2 duplicates = 50% > 30%
        text = "A\nB\nA\nB"
        result = check_repetition(text)
        assert result["repetition_rate"] == 0.5
        assert result["has_severe_repetition"] is True

        # 10 lines, 1 duplicate = 10% < 30%
        text2 = "A\nB\nC\nD\nE\nF\nG\nH\nI\nA"
        result2 = check_repetition(text2)
        assert result2["repetition_rate"] == 0.1
        assert result2["has_severe_repetition"] is False

    def test_repetition_rate_calculation(self):
        """Test repetition rate is calculated correctly."""
        # 4 lines, 2 duplicates
        text = "A\nB\nA\nB"
        result = check_repetition(text)
        assert result["repetition_rate"] == 0.5

        # 5 lines, 1 duplicate
        text2 = "A\nB\nC\nD\nA"
        result2 = check_repetition(text2)
        assert result2["repetition_rate"] == 0.2

    def test_lines_with_whitespace_stripped(self):
        """Test that lines are stripped of whitespace before comparison."""
        text = "  Hello  \nHello\n  Hello"
        result = check_repetition(text)
        assert result["exact_duplicate_count"] == 2
        assert result["total_lines"] == 3

    def test_empty_lines_ignored(self):
        """Test that empty lines are ignored."""
        text = "Hello\n\n\nWorld\n\nHello"
        result = check_repetition(text)
        assert result["total_lines"] == 3  # Only non-empty lines counted
        assert result["exact_duplicate_count"] == 1

    def test_return_dict_keys(self):
        """Test that all expected keys are present in return dict."""
        result = check_repetition("test")
        expected_keys = [
            "status", "total_lines", "exact_duplicate_count",
            "fuzzy_duplicate_count", "repetition_rate", "exact_duplicates",
            "fuzzy_duplicates", "has_severe_repetition"
        ]
        for key in expected_keys:
            assert key in result

    def test_real_world_log_example(self):
        """Test with a real-world log-like example."""
        log_data = """Let me check the API routes to see if there's any blocking issue:

Let me check the API routes to understand the issue better:

Let me check the API routes:

Let me check the API routes to understand the blocking issue:

Let me check the API routes:

Let me check the API routes to understand the blocking issue:

Let me check the API routes:"""
        result = check_repetition(log_data)
        assert result["status"] == "analyzed"
        assert result["total_lines"] > 0
        # This should detect both exact and fuzzy duplicates
        total_dups = result["exact_duplicate_count"] + result["fuzzy_duplicate_count"]
        assert total_dups > 0


# ============================================
# Tests for print_repetition_report
# ============================================

class TestPrintRepetitionReport:
    """Tests for the print_repetition_report function."""

    def _capture_print_output(self, func, *args, **kwargs):
        """Helper to capture print output."""
        captured = StringIO()
        sys.stdout = captured
        try:
            func(*args, **kwargs)
        finally:
            sys.stdout = sys.__stdout__
        return captured.getvalue()

    def test_no_content_status(self):
        """Test report with no_content status."""
        result = {
            "status": "no_content",
            "total_lines": 0,
            "exact_duplicate_count": 0,
            "fuzzy_duplicate_count": 0,
            "repetition_rate": 0.0,
            "exact_duplicates": {},
            "fuzzy_duplicates": [],
            "has_severe_repetition": False
        }
        output = self._capture_print_output(print_repetition_report, result)
        assert "No content to analyze" in output

    def test_normal_report(self):
        """Test report with normal analysis results."""
        result = {
            "status": "analyzed",
            "total_lines": 4,
            "exact_duplicate_count": 1,
            "fuzzy_duplicate_count": 1,
            "repetition_rate": 0.5,
            "exact_duplicates": {"Hello": 1},
            "fuzzy_duplicates": [{
                "index": 2,
                "line": "Hello world",
                "matched_line": "Hello word",
                "matched_index": 0,
                "similarity": 0.9
            }],
            "has_severe_repetition": True
        }
        output = self._capture_print_output(print_repetition_report, result)
        assert "Analysis Started" in output
        assert "Statistics" in output
        assert "Exact duplicate lines: 1" in output
        assert "Highly similar lines" in output
        assert "50.00%" in output or "0.50" in output

    def test_report_with_exact_duplicates(self):
        """Test report displays exact duplicate info."""
        result = {
            "status": "analyzed",
            "total_lines": 5,
            "exact_duplicate_count": 3,
            "fuzzy_duplicate_count": 0,
            "repetition_rate": 0.6,
            "exact_duplicates": {"Line A": 2, "Line B": 1},
            "fuzzy_duplicates": [],
            "has_severe_repetition": True
        }
        output = self._capture_print_output(print_repetition_report, result)
        assert "Top 3 Frequent Exact Duplicates" in output
        assert "Line A" in output or "Line B" in output

    def test_report_with_fuzzy_duplicates(self):
        """Test report displays fuzzy duplicate examples."""
        result = {
            "status": "analyzed",
            "total_lines": 3,
            "exact_duplicate_count": 0,
            "fuzzy_duplicate_count": 2,
            "repetition_rate": 0.67,
            "exact_duplicates": {},
            "fuzzy_duplicates": [
                {
                    "index": 1,
                    "line": "This is a very long line that should be truncated in the report output",
                    "matched_line": "This is a very long line that might be similar",
                    "matched_index": 0,
                    "similarity": 0.85
                }
            ],
            "has_severe_repetition": True
        }
        output = self._capture_print_output(print_repetition_report, result)
        assert "Fuzzy Duplicate Examples" in output

    def test_report_severe_repetition_warning(self):
        """Test report shows warning for severe repetition."""
        result = {
            "status": "analyzed",
            "total_lines": 4,
            "exact_duplicate_count": 2,
            "fuzzy_duplicate_count": 0,
            "repetition_rate": 0.5,
            "exact_duplicates": {"A": 2},
            "fuzzy_duplicates": [],
            "has_severe_repetition": True
        }
        output = self._capture_print_output(print_repetition_report, result)
        assert "Warning" in output or "severe" in output.lower()

    def test_report_normal_repetition(self):
        """Test report shows normal message when no severe repetition."""
        result = {
            "status": "analyzed",
            "total_lines": 10,
            "exact_duplicate_count": 1,
            "fuzzy_duplicate_count": 0,
            "repetition_rate": 0.1,
            "exact_duplicates": {"A": 1},
            "fuzzy_duplicates": [],
            "has_severe_repetition": False
        }
        output = self._capture_print_output(print_repetition_report, result)
        assert "normal range" in output.lower() or "within normal" in output.lower()

    def test_report_with_custom_threshold(self):
        """Test report with custom similarity threshold."""
        result = {
            "status": "analyzed",
            "total_lines": 2,
            "exact_duplicate_count": 0,
            "fuzzy_duplicate_count": 1,
            "repetition_rate": 0.5,
            "exact_duplicates": {},
            "fuzzy_duplicates": [{
                "index": 1,
                "line": "test",
                "matched_line": "test",
                "matched_index": 0,
                "similarity": 0.9
            }],
            "has_severe_repetition": True
        }
        output = self._capture_print_output(print_repetition_report, result)
        assert "Analysis Started" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
