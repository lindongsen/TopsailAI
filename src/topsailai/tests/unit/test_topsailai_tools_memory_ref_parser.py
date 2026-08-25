"""Unit tests for inline story-memory reference parsing."""

from unittest import TestCase

from topsailai.tools.memory_tool_utils import memory_ref_parser


class TestMemoryRefParser(TestCase):
    def test_parse_preserves_duplicates_and_special_characters(self):
        text = "Use @memory[Roadmap (Q&A).md] and @memory[ Roadmap (Q&A).md ]."

        self.assertEqual(
            memory_ref_parser.parse_memory_refs(text),
            ["Roadmap (Q&A).md", "Roadmap (Q&A).md"],
        )

    def test_parse_empty_and_non_string_inputs(self):
        self.assertEqual(memory_ref_parser.parse_memory_refs(""), [])
        self.assertEqual(memory_ref_parser.parse_memory_refs(None), [])

    def test_normalize_casefolds_and_collapses_whitespace(self):
        self.assertEqual(
            memory_ref_parser.normalize_title("  STRASSE\t Memory\n.MD "),
            "strasse memory .md",
        )
        self.assertEqual(memory_ref_parser.normalize_title("Straße.md"), "strasse.md")

    def test_build_index_ignores_invalid_values_and_deduplicates_ids(self):
        index = memory_ref_parser.build_title_index(["One.md", None, "One.md"])

        self.assertEqual(index.exact, {"One.md": ("One.md",)})
        self.assertEqual(index.normalized, {"one.md": ("One.md",)})
        self.assertEqual(index.aliases, {"one": ("One.md",)})
        self.assertEqual(
            memory_ref_parser.build_title_index(None),
            memory_ref_parser.TitleIndex(exact={}, normalized={}, aliases={}),
        )

    def test_resolve_prefers_exact_title(self):
        index = memory_ref_parser.build_title_index(["Memory.md", "memory.md"])

        self.assertEqual(
            memory_ref_parser.resolve_ref("Memory.md", index),
            ("Memory.md", None),
        )

    def test_resolve_uses_case_and_whitespace_insensitive_fallback(self):
        index = memory_ref_parser.build_title_index(["Project   Notes.md"])

        self.assertEqual(
            memory_ref_parser.resolve_ref(" project notes.MD ", index),
            ("Project   Notes.md", None),
        )

    def test_resolve_reports_ambiguous_normalized_title(self):
        index = memory_ref_parser.build_title_index(["Memory.md", "memory.md"])

        with self.assertLogs(memory_ref_parser.logger, level="WARNING") as logs:
            result = memory_ref_parser.resolve_ref("MEMORY.MD", index)

        self.assertEqual(result, (None, "ambiguous"))
        self.assertIn("ambiguous normalized memory title", logs.output[0])

    def test_resolve_unique_bare_title(self):
        index = memory_ref_parser.build_title_index(
            ["20260303140000.Notes.md"]
        )

        self.assertEqual(
            memory_ref_parser.resolve_ref("Notes", index),
            ("20260303140000.Notes.md", None),
        )

    def test_resolve_prefixed_title_without_extension(self):
        index = memory_ref_parser.build_title_index(
            ["20260101120000.Roadmap.md"]
        )

        self.assertEqual(
            memory_ref_parser.resolve_ref("20260101120000.Roadmap", index),
            ("20260101120000.Roadmap.md", None),
        )

    def test_resolve_bare_title_with_extension(self):
        index = memory_ref_parser.build_title_index(
            ["20260303140000.Notes.md"]
        )

        self.assertEqual(
            memory_ref_parser.resolve_ref("Notes.md", index),
            ("20260303140000.Notes.md", None),
        )

    def test_resolve_bare_title_normalizes_case_and_whitespace(self):
        index = memory_ref_parser.build_title_index(
            ["20260303140000.Project   Notes.md"]
        )

        self.assertEqual(
            memory_ref_parser.resolve_ref(" project notes ", index),
            ("20260303140000.Project   Notes.md", None),
        )

    def test_resolve_reports_ambiguous_bare_title(self):
        index = memory_ref_parser.build_title_index(
            [
                "20260101120000.Roadmap.md",
                "20260202130000.Roadmap.md",
            ]
        )

        with self.assertLogs(memory_ref_parser.logger, level="WARNING") as logs:
            result = memory_ref_parser.resolve_ref("Roadmap", index)

        self.assertEqual(result, (None, "ambiguous"))
        self.assertIn("ambiguous bare memory title", logs.output[0])

    def test_resolve_bare_title_can_be_disabled(self):
        index = memory_ref_parser.build_title_index(
            ["20260303140000.Notes.md"]
        )

        with self.assertLogs(memory_ref_parser.logger, level="WARNING"):
            result = memory_ref_parser.resolve_ref(
                "Notes",
                index,
                bare_title_enabled=False,
            )

        self.assertEqual(result, (None, "unknown"))

    def test_resolve_reports_unknown_title(self):
        index = memory_ref_parser.build_title_index(["Known.md"])

        with self.assertLogs(memory_ref_parser.logger, level="WARNING") as logs:
            result = memory_ref_parser.resolve_ref("Missing.md", index)

        self.assertEqual(result, (None, "unknown"))
        self.assertIn("unknown memory title", logs.output[0])

    def test_collect_returns_deduplicated_structured_result(self):
        index = memory_ref_parser.build_title_index(
            ["Known.md", "Clash.md", "clash.md"]
        )
        text = (
            "@memory[Known.md] @memory[ known.MD ] @memory[UNKNOWN.md] "
            "@memory[UNKNOWN.md] @memory[CLASH.MD] @memory[CLASH.MD]"
        )

        with self.assertLogs(memory_ref_parser.logger, level="WARNING"):
            result = memory_ref_parser.collect_canonical_ids(text, index)

        self.assertEqual(result.resolved_ids, ("Known.md",))
        self.assertEqual(result.ambiguous_titles, ("CLASH.MD",))
        self.assertEqual(result.unknown_titles, ("UNKNOWN.md",))

    def test_collect_bare_ambiguity_is_not_resolved(self):
        index = memory_ref_parser.build_title_index(
            [
                "20260101120000.Roadmap.md",
                "20260202130000.Roadmap.md",
            ]
        )

        with self.assertLogs(memory_ref_parser.logger, level="WARNING"):
            result = memory_ref_parser.collect_canonical_ids(
                "@memory[Roadmap]",
                index,
            )

        self.assertEqual(result.resolved_ids, ())
        self.assertEqual(result.ambiguous_titles, ("Roadmap",))
        self.assertEqual(result.unknown_titles, ())

    def test_collect_empty_text_returns_empty_result(self):
        result = memory_ref_parser.collect_canonical_ids(
            "", memory_ref_parser.build_title_index([])
        )

        self.assertEqual(
            result,
            memory_ref_parser.MemoryRefResult((), (), ()),
        )
