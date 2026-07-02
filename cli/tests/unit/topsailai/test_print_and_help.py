#!/usr/bin/env python3
"""
Unit tests for print helpers and help text in topsailai.py.

Covers:
- print_header()
- print_table()
- print_help()
- format_size()
- format_timestamp()
"""

import sys
import os
import unittest
import io
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai as cli


class TestFormatSize(unittest.TestCase):
    """Tests for format_size()."""

    def test_bytes(self):
        self.assertEqual(cli.format_size(0), "0B")
        self.assertEqual(cli.format_size(512), "512B")

    def test_kilobytes(self):
        self.assertEqual(cli.format_size(1024), "1.0K")
        self.assertEqual(cli.format_size(1536), "1.5K")

    def test_megabytes(self):
        self.assertEqual(cli.format_size(1024 * 1024), "1.0M")

    def test_gigabytes(self):
        self.assertEqual(cli.format_size(1024 * 1024 * 1024), "1.0G")


class TestFormatTimestamp(unittest.TestCase):
    """Tests for format_timestamp()."""

    def test_known_timestamp(self):
        ts = 1700000000.0
        result = cli.format_timestamp(ts)
        expected = datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")
        self.assertEqual(result, expected)


class TestFormatTimestampFull(unittest.TestCase):
    """Tests for format_timestamp_full()."""

    def test_full_format(self):
        ts = 1700000000.0
        result = cli.format_timestamp_full(ts)
        expected = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        self.assertEqual(result, expected)


class TestPrintHeader(unittest.TestCase):
    """Tests for print_header()."""

    def test_prints_title(self):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            cli.print_header("Test Title")
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("Test Title", output)
        self.assertIn("=", output)


class TestPrintTable(unittest.TestCase):
    """Tests for print_table()."""

    def test_empty_rows(self):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            cli.print_table([])
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("No .stdout log files found", output)

    def test_basic_rows(self):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            cli.print_table([
                {
                    "filename": "foo.stdout",
                    "path": "/tmp/foo.stdout",
                    "session_id": "sid1",
                    "pid": 123,
                    "size": 1024,
                    "mtime": 1700000000.0,
                }
            ])
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("foo.stdout", output)
        self.assertIn("sid1", output)


class TestPrintHelp(unittest.TestCase):
    """Tests for print_help()."""

    def test_contains_commands(self):
        captured = io.StringIO()
        sys.stdout = captured
        try:
            cli.print_help()
        finally:
            sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("Available Commands", output)
        self.assertIn("/help", output)
        self.assertIn("/clean", output)
        self.assertIn("/refresh", output)


if __name__ == "__main__":
    unittest.main()
