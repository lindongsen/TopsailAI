#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the packaging-generated ``version`` record reader.

The record is the single source of truth for the build identity, so these tests
pin three contracts: the path the reader resolves, the fallback that keeps a
version request from ever failing, and the parity between ``--version`` and
``-v``.

Author: DawsonLin
"""

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

# Ensure the CLI source is importable.
CLI_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, CLI_DIR)

from cli_topsailai import core
from cli_topsailai import version as version_module


class VersionFilePathTest(unittest.TestCase):
    """Pin where the reader looks for the generated record."""

    def test_path_is_beside_the_package_root(self):
        """The record sits beside the package root, three levels above this file."""
        expected = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(version_module.__file__)))
            ),
            version_module.VERSION_FILE_NAME,
        )
        self.assertEqual(version_module.get_version_file_path(), expected)

    def test_path_matches_the_packaged_layout(self):
        """The resolved path is the one the packager writes into the package."""
        self.assertTrue(
            version_module.get_version_file_path().endswith(
                os.path.join("topsailai", version_module.VERSION_FILE_NAME)
            )
        )

    def test_path_agrees_with_the_packaged_project_base(self):
        """The record sits inside the tree the packager maps onto the install path.

        ``_import_topsailai.PROJECT_FOLDER_BASE`` is the repository root the
        packager maps to ``lib_home``, so deriving the record from it and from
        this module must name the same file. A disagreement would mean the CLI
        reads a path the packager never writes.
        """
        import _import_topsailai

        expected = os.path.join(
            _import_topsailai.PROJECT_FOLDER_BASE,
            "topsailai",
            version_module.VERSION_FILE_NAME,
        )
        self.assertEqual(version_module.get_version_file_path(), expected)


class ReadVersionInfoTest(unittest.TestCase):
    """Pin the record schema and every fallback path."""

    def setUp(self):
        """Create an isolated directory for record fixtures."""
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)

    def _write(self, content):
        """Write ``content`` to a record file and return its path."""
        path = os.path.join(self._temp_dir.name, "version")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def test_reads_a_complete_record(self):
        """A well-formed record is returned with every field intact."""
        record = {
            "schema_version": 1,
            "package": "topsailai",
            "version": "20261122085959+c3fbc696",
            "commit": "c3fbc696",
        }
        path = self._write(json.dumps(record))

        self.assertEqual(version_module.read_version_info(path), record)
        self.assertEqual(
            version_module.get_version_string(path), "20261122085959+c3fbc696"
        )

    def test_absent_record_falls_back_silently(self):
        """A source checkout has no record, and that is not an error."""
        path = os.path.join(self._temp_dir.name, "absent")
        stderr = StringIO()

        with patch("sys.stderr", stderr):
            self.assertIsNone(version_module.read_version_info(path))
            self.assertEqual(version_module.get_version_string(path), "dev")

        self.assertEqual(stderr.getvalue(), "")

    def test_invalid_json_falls_back_with_a_warning(self):
        """A corrupt record reports the fallback and explains itself on stderr."""
        path = self._write("not json")
        stderr = StringIO()

        with patch("sys.stderr", stderr):
            self.assertEqual(version_module.get_version_string(path), "dev")

        self.assertIn("[WARN]", stderr.getvalue())
        self.assertIn("not valid JSON", stderr.getvalue())

    def test_non_string_version_falls_back(self):
        """A record that cannot name a build is not a version."""
        path = self._write(json.dumps({"schema_version": 1, "version": 123}))
        stderr = StringIO()

        with patch("sys.stderr", stderr):
            self.assertEqual(version_module.get_version_string(path), "dev")

        self.assertIn("no usable 'version' string", stderr.getvalue())

    def test_blank_version_falls_back(self):
        """Whitespace is not a version either."""
        path = self._write(json.dumps({"version": "   "}))

        with patch("sys.stderr", StringIO()):
            self.assertEqual(version_module.get_version_string(path), "dev")

    def test_non_object_json_falls_back(self):
        """A JSON array is not a record."""
        path = self._write(json.dumps(["20261122085959"]))
        stderr = StringIO()

        with patch("sys.stderr", stderr):
            self.assertEqual(version_module.get_version_string(path), "dev")

        self.assertIn("not a JSON object", stderr.getvalue())

    def test_oversized_record_is_rejected_without_parsing(self):
        """A file above the size bound is not read into memory."""
        path = self._write(
            json.dumps({"version": "x" * (version_module.MAX_VERSION_FILE_BYTES + 1)})
        )
        stderr = StringIO()

        with patch("sys.stderr", stderr):
            self.assertEqual(version_module.get_version_string(path), "dev")

        self.assertIn("above the", stderr.getvalue())

    def test_unknown_keys_are_tolerated(self):
        """A newer packager may add fields without breaking an older reader."""
        path = self._write(
            json.dumps({"version": "20261122085959+c3fbc696", "future_field": True})
        )

        self.assertEqual(
            version_module.get_version_string(path), "20261122085959+c3fbc696"
        )

    def test_unknown_schema_version_still_reads_known_fields(self):
        """A schema bump warns but does not discard a readable version."""
        path = self._write(json.dumps({"schema_version": 99, "version": "1.2.3"}))
        stderr = StringIO()

        with patch("sys.stderr", stderr):
            self.assertEqual(version_module.get_version_string(path), "1.2.3")

        self.assertIn("schema_version", stderr.getvalue())

    def test_missing_commit_key_is_not_an_error(self):
        """A build without git records no commit, and that is valid."""
        path = self._write(json.dumps({"schema_version": 1, "version": "1.2.3"}))
        stderr = StringIO()

        with patch("sys.stderr", stderr):
            record = version_module.read_version_info(path)

        self.assertEqual(record["version"], "1.2.3")
        self.assertNotIn("commit", record)
        self.assertEqual(stderr.getvalue(), "")


class VersionOptionTest(unittest.TestCase):
    """Pin the CLI surface that reports the build identity."""

    def test_long_and_short_option_print_the_same_line(self):
        """``-v`` is an alias, not a second output format."""
        outputs = []
        for argv in (["--version"], ["-v"]):
            stdout = StringIO()
            with patch("sys.stdout", stdout):
                with self.assertRaises(SystemExit) as result:
                    core.main(argv)
            self.assertEqual(result.exception.code, 0)
            outputs.append(stdout.getvalue())

        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], "topsailai.py dev\n")

    def test_option_reports_the_record_value(self):
        """The printed value comes from the record, not from a constant."""
        stdout = StringIO()
        with patch.object(core, "get_version_string", return_value="20261122085959+c3fbc696"):
            with patch("sys.stdout", stdout):
                with self.assertRaises(SystemExit) as result:
                    core.main(["--version"])

        self.assertEqual(result.exception.code, 0)
        self.assertEqual(stdout.getvalue(), "topsailai.py 20261122085959+c3fbc696\n")

    def test_help_lists_the_short_option(self):
        """The alias is discoverable in help output."""
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            with self.assertRaises(SystemExit) as result:
                core.main(["--help"])

        self.assertEqual(result.exception.code, 0)
        self.assertIn("-v, --version", stdout.getvalue())

    def test_module_has_no_hardcoded_version_constant(self):
        """A second copy of the version is exactly what this change removed."""
        self.assertFalse(hasattr(core, "__version__"))


if __name__ == "__main__":
    unittest.main()
