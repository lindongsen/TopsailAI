"""Unit tests for raw-response story-memory reference accounting."""

import os
from unittest import TestCase
from unittest.mock import patch

from topsailai.tools.memory_tool_utils import memory_ref_scan_hook


class TestMemoryRefScanHook(TestCase):
    """Verify guarded citation accounting in the external response hook."""

    def setUp(self):
        """Create raw response text containing duplicate normalized references."""
        self.response = (
            "Use @memory[Known.md] while thinking. "
            "Then cite @memory[ known.MD ] in the final answer."
        )

    @patch("topsailai.tools.memory_tool_utils.memory_stat.record_memory_event")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_records_one_cite_for_duplicate_refs(
        self, list_memories, record_memory_event
    ):
        """Count a canonical memory at most once in one raw LLM response."""
        list_memories.return_value = ["Known.md"]

        result = memory_ref_scan_hook.hook_execute(self.response)

        self.assertIs(result, self.response)
        record_memory_event.assert_called_once()
        workspace, memory_id, event = record_memory_event.call_args.args
        self.assertTrue(workspace)
        self.assertEqual((memory_id, event), ("Known.md", "cite"))

    @patch("topsailai.tools.memory_tool_utils.memory_stat.record_memory_event")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_unknown_and_ambiguous_refs_are_not_recorded(
        self, list_memories, record_memory_event
    ):
        """Ignore unresolved titles while preserving raw response processing."""
        list_memories.return_value = ["Clash.md", "clash.md"]
        response = "@memory[CLASH.MD] and @memory[Missing.md]"

        result = memory_ref_scan_hook.hook_execute(response)

        self.assertIs(result, response)
        record_memory_event.assert_not_called()

    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_disabled_env_is_fast_noop(self, list_memories):
        """Skip imports, title enumeration, and writes when explicitly disabled."""
        with patch.dict(
            os.environ,
            {"TOPSAILAI_MEMORY_REFERENCE_SCAN_ENABLED": "0"},
        ):
            result = memory_ref_scan_hook.hook_execute(self.response)

        self.assertIs(result, self.response)
        list_memories.assert_not_called()

    @patch("topsailai.tools.memory_tool_utils.memory_ref_scan_hook.logger.warning")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_accounting_error_is_logged_and_swallowed(
        self, list_memories, log_warning
    ):
        """Never let citation-accounting failures interrupt response delivery."""
        list_memories.side_effect = RuntimeError("unavailable")

        result = memory_ref_scan_hook.hook_execute(self.response)

        self.assertIs(result, self.response)
        log_warning.assert_called_once()
        self.assertIn(
            "Failed to record story-memory references",
            log_warning.call_args.args[0],
        )

    @patch("topsailai.tools.memory_tool_utils.memory_stat.record_memory_event")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_non_string_content_is_returned_unchanged(
        self, list_memories, record_memory_event
    ):
        """Preserve unexpected content types without recording citations."""
        list_memories.return_value = ["Known.md"]
        content = {"content": "@memory[Known.md]"}

        result = memory_ref_scan_hook.hook_execute(content)

        self.assertIs(result, content)
        record_memory_event.assert_not_called()
