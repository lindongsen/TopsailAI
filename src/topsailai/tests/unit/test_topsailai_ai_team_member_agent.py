"""
Unit tests for ai_team/member_agent.py

This module contains unit tests for the member_agent module which handles
system prompt generation for team member agents.

Author: mm-m25
"""

import os
import unittest
from unittest.mock import patch, MagicMock


class TestExtendSystemPrompt(unittest.TestCase):
    """Tests for extend_system_prompt() function."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Store original env var if it exists
        self.original_env = None
        if "SYSTEM_PROMPT_EXTRA_FILES" in __import__('os').environ:
            self.original_env = __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"]
    
    def tearDown(self):
        """Clean up test environment."""
        if self.original_env is not None:
            __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"] = self.original_env
        elif "SYSTEM_PROMPT_EXTRA_FILES" in __import__('os').environ:
            del __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"]
    
    def test_returns_none(self):
        """Test that extend_system_prompt returns None."""
        from topsailai.ai_team.member_agent import extend_system_prompt
        result = extend_system_prompt()
        self.assertIsNone(result)
    
    def test_sets_default_when_not_set(self):
        """Test that extend_system_prompt sets default value when env var not set."""
        # Ensure env var is not set
        if "SYSTEM_PROMPT_EXTRA_FILES" in __import__('os').environ:
            del __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"]
        
        from topsailai.ai_team.member_agent import extend_system_prompt
        extend_system_prompt()
        
        self.assertEqual(
            __import__('os').environ.get("SYSTEM_PROMPT_EXTRA_FILES"),
            "work_mode/sop/work_agreement.md"
        )
    
    def test_does_not_override_existing(self):
        """Test that extend_system_prompt does not override existing env var."""
        __import__('os').environ["SYSTEM_PROMPT_EXTRA_FILES"] = "custom/path.md"
        
        from topsailai.ai_team.member_agent import extend_system_prompt
        extend_system_prompt()
        
        self.assertEqual(
            __import__('os').environ.get("SYSTEM_PROMPT_EXTRA_FILES"),
            "custom/path.md"
        )


class TestGetSystemPrompt(unittest.TestCase):
    """Tests for get_system_prompt() function."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_file_content = "You are a helpful AI assistant."
        self.mock_member_prompt = "\n\n## Role\nYou are a team member."
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_returns_string_type(self, mock_extend, mock_get_member, mock_file):
        """Test that get_system_prompt returns string type."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        self.assertIsInstance(result, str)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_contains_base_system_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that result contains base system prompt content."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        self.assertIn(self.mock_file_content, result)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_appends_member_prompt_when_not_present(self, mock_extend, mock_get_member, mock_file):
        """Test that member prompt is appended when not in system prompt."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        self.assertIn(self.mock_member_prompt.strip(), result)
        mock_get_member.assert_called_once_with("mm-m25")
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_does_not_append_duplicate_member_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that member prompt is not appended twice when already present."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        # Member prompt already in system prompt
        combined_content = self.mock_file_content + self.mock_member_prompt
        mock_file.return_value = (None, combined_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        # Should only appear once
        self.assertEqual(result.count(self.mock_member_prompt), 1)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_calls_extend_system_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that extend_system_prompt is called."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        get_system_prompt("mm-m25")
        
        mock_extend.assert_called_once()
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_handles_empty_system_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that function handles empty system prompt gracefully."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, "")
        mock_get_member.return_value = self.mock_member_prompt
        
        result = get_system_prompt("mm-m25")
        
        self.assertIn(self.mock_member_prompt, result)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_handles_empty_member_prompt(self, mock_extend, mock_get_member, mock_file):
        """Test that function handles empty member prompt gracefully."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = ""
        
        result = get_system_prompt("mm-m25")
        
        self.assertEqual(result, self.mock_file_content)
    
    @patch('topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    @patch('topsailai.ai_team.member_agent.extend_system_prompt')
    def test_uses_agent_name_parameter(self, mock_extend, mock_get_member, mock_file):
        """Test that agent_name parameter is passed to get_member_prompt."""
        from topsailai.ai_team.member_agent import get_system_prompt
        
        mock_file.return_value = (None, self.mock_file_content)
        mock_get_member.return_value = self.mock_member_prompt
        
        get_system_prompt("test-agent-42")
        
        mock_get_member.assert_called_once_with("test-agent-42")



class TestPrecomposedLaunchDetection(unittest.TestCase):
    """Tests for structured plugin-launch provenance detection."""

    def test_matching_plugin_launch_signals_are_precomposed(self):
        """Matching prompt paths plus published Team content identify the plugin."""
        from topsailai.ai_team.member_agent import is_team_prompt_precomposed_launch

        with patch.dict(
            "os.environ",
            {
                "SYSTEM_PROMPT": "/tmp/member-prompt",
                "TOPSAILAI_SYSTEM_PROMPT": "/tmp/member-prompt",
                "TOPSAILAI_TEAM_PROMPT_CONTENT": "# AI Team",
            },
            clear=False,
        ):
            self.assertTrue(is_team_prompt_precomposed_launch())

    def test_direct_launch_without_plugin_prompt_path_is_not_precomposed(self):
        """Published Manager state alone does not suppress direct composition."""
        from topsailai.ai_team.member_agent import is_team_prompt_precomposed_launch

        with patch.dict(
            "os.environ",
            {
                "SYSTEM_PROMPT": "direct-base",
                "TOPSAILAI_TEAM_PROMPT_CONTENT": "# AI Team",
            },
            clear=False,
        ):
            os.environ.pop("TOPSAILAI_SYSTEM_PROMPT", None)
            self.assertFalse(is_team_prompt_precomposed_launch())


class TestTeamPromptComposition(unittest.TestCase):
    """Tests for shared and Member-scoped prompt composition."""

    @patch("topsailai.ai_team.member_agent.extend_system_prompt")
    @patch("topsailai.ai_team.member_agent.get_member_prompt")
    @patch("topsailai.ai_team.member_agent.team_prompt.load_team_values")
    @patch("topsailai.ai_team.member_agent.team_prompt.resolve_runtime_team_prompt")
    @patch("topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy")
    def test_direct_member_uses_canonical_team_order(
        self,
        mock_file,
        mock_resolve_runtime,
        mock_load_team_values,
        mock_get_member,
        mock_extend,
    ):
        """A direct Member receives runtime, shared, and private layers in order."""
        from topsailai.ai_team.member_agent import get_system_prompt

        mock_file.return_value = (None, "BASE")
        mock_resolve_runtime.return_value = "RUNTIME"
        mock_load_team_values.return_value = "TEAM_VALUES"
        mock_get_member.return_value = "ROLE\nMEMBER_VALUES"

        with patch.dict(
            "os.environ",
            {
                "TOPSAILAI_TEAM_PROMPT": "runtime-source",
                "TOPSAILAI_TEAM_PATH": "/team",
            },
            clear=False,
        ):
            result = get_system_prompt("member-a")

        self.assertEqual(
            result,
            "BASE\nRUNTIME\nTEAM_VALUES\nROLE\nMEMBER_VALUES",
        )
        mock_load_team_values.assert_called_once_with("/team")
        mock_get_member.assert_called_once_with("member-a")

    @patch("topsailai.ai_team.member_agent.extend_system_prompt")
    @patch("topsailai.ai_team.member_agent.get_member_prompt")
    @patch("topsailai.ai_team.member_agent.team_prompt.load_team_values")
    @patch("topsailai.ai_team.member_agent.team_prompt.resolve_runtime_team_prompt")
    @patch("topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy")
    def test_precomposed_member_does_not_reload_team_layers(
        self,
        mock_file,
        mock_resolve_runtime,
        mock_load_team_values,
        mock_get_member,
        mock_extend,
    ):
        """Explicit provenance prevents a plugin prompt from loading team layers twice."""
        from topsailai.ai_team.member_agent import get_system_prompt

        mock_file.return_value = (None, "BASE\nRUNTIME\nTEAM_VALUES")
        mock_get_member.return_value = "ROLE\nMEMBER_VALUES"

        result = get_system_prompt("member-a", team_prompt_precomposed=True)

        self.assertEqual(
            result,
            "BASE\nRUNTIME\nTEAM_VALUES\nROLE\nMEMBER_VALUES",
        )
        mock_resolve_runtime.assert_not_called()
        mock_load_team_values.assert_not_called()

    @patch("topsailai.ai_team.member_agent.extend_system_prompt")
    @patch("topsailai.ai_team.member_agent.get_member_prompt")
    @patch("topsailai.ai_team.member_agent.team_prompt.load_team_values")
    @patch("topsailai.ai_team.member_agent.team_prompt.resolve_runtime_team_prompt")
    @patch("topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy")
    def test_omitted_provenance_detects_precomposed_plugin_launch(
        self,
        mock_file,
        mock_resolve_runtime,
        mock_load_team_values,
        mock_get_member,
        mock_extend,
    ):
        """Omitted provenance uses structured launch state to avoid duplication."""
        from topsailai.ai_team.member_agent import get_system_prompt

        mock_file.return_value = (None, "BASE\n# AI Team\nTEAM_VALUES")
        mock_get_member.return_value = "ROLE\nMEMBER_VALUES"

        with patch.dict(
            "os.environ",
            {
                "SYSTEM_PROMPT": "/tmp/member-prompt",
                "TOPSAILAI_SYSTEM_PROMPT": "/tmp/member-prompt",
                "TOPSAILAI_TEAM_PROMPT_CONTENT": "# AI Team\nTEAM_VALUES",
                "TOPSAILAI_TEAM_PROMPT": "runtime-source",
                "TOPSAILAI_TEAM_PATH": "/team",
            },
            clear=True,
        ):
            result = get_system_prompt("member-a")

        self.assertEqual(
            result,
            "BASE\n# AI Team\nTEAM_VALUES\nROLE\nMEMBER_VALUES",
        )
        self.assertEqual(result.count("# AI Team"), 1)
        mock_resolve_runtime.assert_not_called()
        mock_load_team_values.assert_not_called()

    @patch("topsailai.ai_team.member_agent.extend_system_prompt")
    @patch("topsailai.ai_team.member_agent.get_member_prompt")
    @patch("topsailai.ai_team.member_agent.team_prompt.load_team_values")
    @patch("topsailai.ai_team.member_agent.team_prompt.resolve_runtime_team_prompt")
    @patch("topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy")
    def test_omitted_provenance_keeps_direct_launch_composition(
        self,
        mock_file,
        mock_resolve_runtime,
        mock_load_team_values,
        mock_get_member,
        mock_extend,
    ):
        """Omitted provenance keeps direct-launch Team layers and ordering."""
        from topsailai.ai_team.member_agent import get_system_prompt

        mock_file.return_value = (None, "BASE")
        mock_resolve_runtime.return_value = "RUNTIME"
        mock_load_team_values.return_value = "TEAM_VALUES"
        mock_get_member.return_value = "ROLE\nMEMBER_VALUES"

        with patch.dict(
            "os.environ",
            {
                "SYSTEM_PROMPT": "direct-base",
                "TOPSAILAI_TEAM_PROMPT": "runtime-source",
                "TOPSAILAI_TEAM_PATH": "/team",
            },
            clear=True,
        ):
            result = get_system_prompt("member-a")

        self.assertEqual(
            result,
            "BASE\nRUNTIME\nTEAM_VALUES\nROLE\nMEMBER_VALUES",
        )
        mock_resolve_runtime.assert_called_once_with("runtime-source")
        mock_load_team_values.assert_called_once_with("/team")

    @patch("topsailai.ai_team.member_agent.extend_system_prompt")
    @patch("topsailai.ai_team.member_agent.get_member_prompt")
    @patch("topsailai.ai_team.member_agent.team_prompt.load_team_values")
    @patch("topsailai.ai_team.member_agent.team_prompt.resolve_runtime_team_prompt")
    @patch("topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy")
    def test_explicit_false_overrides_automatic_precomposed_detection(
        self,
        mock_file,
        mock_resolve_runtime,
        mock_load_team_values,
        mock_get_member,
        mock_extend,
    ):
        """An explicit value takes priority over matching plugin launch state."""
        from topsailai.ai_team.member_agent import get_system_prompt

        mock_file.return_value = (None, "BASE")
        mock_resolve_runtime.return_value = "RUNTIME"
        mock_load_team_values.return_value = "TEAM_VALUES"
        mock_get_member.return_value = "ROLE"

        with patch.dict(
            "os.environ",
            {
                "SYSTEM_PROMPT": "/tmp/member-prompt",
                "TOPSAILAI_SYSTEM_PROMPT": "/tmp/member-prompt",
                "TOPSAILAI_TEAM_PROMPT_CONTENT": "PRECOMPOSED",
                "TOPSAILAI_TEAM_PROMPT": "runtime-source",
                "TOPSAILAI_TEAM_PATH": "/team",
            },
            clear=True,
        ):
            result = get_system_prompt(
                "member-a", team_prompt_precomposed=False
            )

        self.assertEqual(result, "BASE\nRUNTIME\nTEAM_VALUES\nROLE")
        mock_resolve_runtime.assert_called_once_with("runtime-source")
        mock_load_team_values.assert_called_once_with("/team")

    @patch("topsailai.ai_team.member_agent.extend_system_prompt")
    @patch("topsailai.ai_team.member_agent.get_member_prompt")
    @patch("topsailai.ai_team.member_agent.team_prompt.load_team_values")
    @patch("topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy")
    def test_same_heading_in_team_values_is_not_content_deduplicated(
        self,
        mock_file,
        mock_load_team_values,
        mock_get_member,
        mock_extend,
    ):
        """Legitimate repeated headings remain when segments have distinct provenance."""
        from topsailai.ai_team.member_agent import get_system_prompt

        mock_file.return_value = (None, "BASE\n# AI Team\nBASE_POLICY")
        mock_load_team_values.return_value = "# AI Team\nSHARED_POLICY"
        mock_get_member.return_value = "ROLE"

        with patch.dict(
            "os.environ",
            {
                "SYSTEM_PROMPT": "direct-base",
                "TOPSAILAI_TEAM_PROMPT": "",
                "TOPSAILAI_TEAM_PATH": "/team",
            },
            clear=True,
        ):
            result = get_system_prompt("member-a")

        self.assertEqual(result.count("# AI Team"), 2)
        self.assertIn("BASE_POLICY", result)
        self.assertIn("SHARED_POLICY", result)

    @patch("topsailai.ai_team.member_agent.extend_system_prompt")
    @patch("topsailai.ai_team.member_agent.get_member_prompt")
    @patch("topsailai.ai_team.member_agent.team_prompt.load_team_values")
    @patch("topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy")
    def test_missing_or_empty_team_values_preserve_legacy_result(
        self,
        mock_file,
        mock_load_team_values,
        mock_get_member,
        mock_extend,
    ):
        """No shared values segment preserves the base-plus-Member behavior."""
        from topsailai.ai_team.member_agent import get_system_prompt

        mock_file.return_value = (None, "BASE")
        mock_load_team_values.return_value = ""
        mock_get_member.return_value = "ROLE\nMEMBER_VALUES"

        with patch.dict("os.environ", {"TOPSAILAI_TEAM_PROMPT": ""}, clear=False):
            result = get_system_prompt("member-a")

        self.assertEqual(result, "BASE\nROLE\nMEMBER_VALUES")

    @patch("topsailai.ai_team.member_agent.extend_system_prompt")
    @patch("topsailai.ai_team.member_agent.get_member_prompt")
    @patch("topsailai.ai_team.member_agent.team_prompt.load_team_values")
    @patch("topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy")
    def test_unreadable_team_values_fail_closed(
        self,
        mock_file,
        mock_load_team_values,
        mock_get_member,
        mock_extend,
    ):
        """A read failure from an existing shared values file is propagated."""
        from topsailai.ai_team.member_agent import get_system_prompt

        mock_file.return_value = (None, "BASE")
        mock_load_team_values.side_effect = PermissionError("denied")

        with self.assertRaisesRegex(PermissionError, "denied"):
            get_system_prompt("member-a")
        mock_get_member.assert_not_called()

    @patch("topsailai.ai_team.member_agent.extend_system_prompt")
    @patch("topsailai.ai_team.member_agent.get_member_prompt")
    @patch("topsailai.ai_team.member_agent.team_prompt.load_team_values")
    @patch("topsailai.ai_team.member_agent.file_tool.get_file_content_fuzzy")
    def test_selected_member_prompt_remains_isolated(
        self,
        mock_file,
        mock_load_team_values,
        mock_get_member,
        mock_extend,
    ):
        """Composition requests only the selected Member's role and values."""
        from topsailai.ai_team.member_agent import get_system_prompt

        mock_file.return_value = (None, "BASE")
        mock_load_team_values.return_value = "TEAM_VALUES"
        mock_get_member.return_value = "ROLE_A\nPRIVATE_A"

        result = get_system_prompt("member-a")

        self.assertIn("TEAM_VALUES", result)
        self.assertIn("PRIVATE_A", result)
        self.assertNotIn("PRIVATE_B", result)
        mock_get_member.assert_called_once_with("member-a")

if __name__ == '__main__':
    unittest.main()
