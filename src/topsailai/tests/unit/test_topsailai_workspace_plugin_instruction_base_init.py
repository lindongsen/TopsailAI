"""
Unit tests for topsailai.workspace.plugin_instruction.base.init

Tests the INSTRUCTIONS dict creation and expand_plugin_instructions function
which loads external plugin instructions from environment variables.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from topsailai.workspace.plugin_instruction.base import init as init_mod


@pytest.fixture(autouse=True)
def save_and_restore_instructions():
    """Save and restore INSTRUCTIONS state around each test."""
    original = dict(init_mod.INSTRUCTIONS)
    yield
    init_mod.INSTRUCTIONS.clear()
    init_mod.INSTRUCTIONS.update(original)


class TestExpandPluginInstructionsDirectCall:
    """Test expand_plugin_instructions by calling it directly."""

    @patch.dict(os.environ, {}, clear=True)
    def test_no_env_var_does_nothing(self):
        """When TOPSAILAI_PLUGIN_INSTRUCTIONS is not set, INSTRUCTIONS should not change."""
        original_keys = set(init_mod.INSTRUCTIONS.keys())
        init_mod.expand_plugin_instructions()
        assert set(init_mod.INSTRUCTIONS.keys()) == original_keys

    @patch.dict(os.environ, {"TOPSAILAI_PLUGIN_INSTRUCTIONS": ""}, clear=True)
    def test_empty_env_var_does_nothing(self):
        """When env var is empty string, INSTRUCTIONS should not change."""
        original_keys = set(init_mod.INSTRUCTIONS.keys())
        init_mod.expand_plugin_instructions()
        assert set(init_mod.INSTRUCTIONS.keys()) == original_keys

    @patch.dict(os.environ, {"TOPSAILAI_PLUGIN_INSTRUCTIONS": "/path/to/plugin"}, clear=True)
    @patch("topsailai.workspace.plugin_instruction.base.init.get_external_function_map")
    def test_single_valid_plugin_path(self, mock_ext):
        """A single valid plugin path should merge its instructions."""
        extra = {"plugin.cmd": MagicMock()}
        mock_ext.return_value = extra

        init_mod.expand_plugin_instructions()

        assert "plugin.cmd" in init_mod.INSTRUCTIONS
        mock_ext.assert_called_once_with("/path/to/plugin", "INSTRUCTIONS")

    @patch.dict(
        os.environ,
        {"TOPSAILAI_PLUGIN_INSTRUCTIONS": "/path/a;/path/b"},
        clear=True,
    )
    @patch("topsailai.workspace.plugin_instruction.base.init.get_external_function_map")
    def test_multiple_plugin_paths(self, mock_ext):
        """Multiple plugin paths separated by semicolon should all be loaded."""
        mock_ext.side_effect = [
            {"a.cmd": MagicMock()},
            {"b.cmd": MagicMock()},
        ]

        init_mod.expand_plugin_instructions()

        assert "a.cmd" in init_mod.INSTRUCTIONS
        assert "b.cmd" in init_mod.INSTRUCTIONS
        assert mock_ext.call_count == 2
        calls = [call.args for call in mock_ext.call_args_list]
        assert calls == [("/path/a", "INSTRUCTIONS"), ("/path/b", "INSTRUCTIONS")]

    @patch.dict(
        os.environ,
        {"TOPSAILAI_PLUGIN_INSTRUCTIONS": "/path/a;;/path/b"},
        clear=True,
    )
    @patch("topsailai.workspace.plugin_instruction.base.init.get_external_function_map")
    def test_empty_path_in_middle_ignored(self, mock_ext):
        """Empty path from double semicolon should be ignored."""
        mock_ext.side_effect = [
            {"a.cmd": MagicMock()},
            None,  # empty path -> get_external_function_map returns None for empty
            {"b.cmd": MagicMock()},
        ]

        init_mod.expand_plugin_instructions()

        assert "a.cmd" in init_mod.INSTRUCTIONS
        assert "b.cmd" in init_mod.INSTRUCTIONS

    @patch.dict(
        os.environ,
        {"TOPSAILAI_PLUGIN_INSTRUCTIONS": "/bad/path"},
        clear=True,
    )
    @patch("topsailai.workspace.plugin_instruction.base.init.get_external_function_map")
    def test_plugin_returns_none_not_merged(self, mock_ext):
        """When get_external_function_map returns None, INSTRUCTIONS should not change."""
        original_len = len(init_mod.INSTRUCTIONS)
        mock_ext.return_value = None

        init_mod.expand_plugin_instructions()

        assert len(init_mod.INSTRUCTIONS) == original_len

    @patch.dict(
        os.environ,
        {"TOPSAILAI_PLUGIN_INSTRUCTIONS": "/path/1;/path/2"},
        clear=True,
    )
    @patch("topsailai.workspace.plugin_instruction.base.init.get_external_function_map")
    def test_plugin_overwrites_existing_keys(self, mock_ext):
        """External plugin instructions can overwrite existing keys via dict.update."""
        # Pick an existing key to overwrite
        existing_keys = list(init_mod.INSTRUCTIONS.keys())
        assert existing_keys
        target_key = existing_keys[0]
        original_func = init_mod.INSTRUCTIONS[target_key]
        new_func = MagicMock()

        mock_ext.side_effect = [
            {target_key: new_func},
            None,
        ]

        init_mod.expand_plugin_instructions()

        assert init_mod.INSTRUCTIONS[target_key] is new_func

    @patch.dict(
        os.environ,
        {"TOPSAILAI_PLUGIN_INSTRUCTIONS": "/path/a"},
        clear=True,
    )
    @patch("topsailai.workspace.plugin_instruction.base.init.get_external_function_map")
    def test_expand_returns_none(self, mock_ext):
        """expand_plugin_instructions should return None."""
        mock_ext.return_value = None
        result = init_mod.expand_plugin_instructions()
        assert result is None

    @patch.dict(
        os.environ,
        {"TOPSAILAI_PLUGIN_INSTRUCTIONS": "  /path/with/spaces  "},
        clear=True,
    )
    @patch("topsailai.workspace.plugin_instruction.base.init.get_external_function_map")
    def test_path_with_spaces_not_stripped(self, mock_ext):
        """Paths with leading/trailing spaces are NOT stripped before processing."""
        mock_ext.return_value = {"space.cmd": MagicMock()}

        init_mod.expand_plugin_instructions()

        # The actual code does NOT call .strip() on plugin_path
        mock_ext.assert_called_once_with("  /path/with/spaces  ", "INSTRUCTIONS")
        assert "space.cmd" in init_mod.INSTRUCTIONS


class TestInstructionsStructure:
    """Test the structure and content of INSTRUCTIONS."""

    def test_instructions_is_dict(self):
        """INSTRUCTIONS should be a dict."""
        assert isinstance(init_mod.INSTRUCTIONS, dict)

    def test_instruction_keys_are_strings(self):
        """All keys in INSTRUCTIONS should be strings."""
        for key in init_mod.INSTRUCTIONS:
            assert isinstance(key, str)

    def test_instruction_values_are_callable(self):
        """All values in INSTRUCTIONS should be callable."""
        for value in init_mod.INSTRUCTIONS.values():
            assert callable(value)

    def test_instructions_not_empty(self):
        """The real INSTRUCTIONS dict should not be empty."""
        assert len(init_mod.INSTRUCTIONS) > 0


class TestRealInstructions:
    """Test with real (unmocked) INSTRUCTIONS to verify actual content."""

    def test_real_instructions_contains_expected_prefixes(self):
        """Real INSTRUCTIONS should contain keys from plugin_instruction modules."""
        # Based on the source files in plugin_instruction folder:
        # env.py -> env.set, env.get
        # agent.py -> agent.system_prompt, agent.env_prompt, etc.
        # skill.py -> skill.show, skill.load, skill.unload, skill.hooks
        # skill_repo.py -> skill_repo.list, skill_repo.install, skill_repo.uninstall
        # stat.py -> stat.tool_call, stat.tool_call_errors, stat.tool_call_reset, stat.tool_call_log
        expected_prefixes = [
            "env.",
            "agent.",
            "skill.",
            "skill_repo.",
            "stat.",
        ]
        keys = list(init_mod.INSTRUCTIONS.keys())
        for prefix in expected_prefixes:
            matching = [k for k in keys if k.startswith(prefix)]
            assert matching, f"Expected at least one key with prefix {prefix}"

    def test_real_instructions_has_env_set(self):
        """INSTRUCTIONS should contain env.set."""
        assert "env.set" in init_mod.INSTRUCTIONS

    def test_real_instructions_has_env_get(self):
        """INSTRUCTIONS should contain env.get."""
        assert "env.get" in init_mod.INSTRUCTIONS

    def test_real_instructions_has_agent_system_prompt(self):
        """INSTRUCTIONS should contain agent.system_prompt."""
        assert "agent.system_prompt" in init_mod.INSTRUCTIONS

    def test_real_instructions_has_skill_show(self):
        """INSTRUCTIONS should contain skill.show."""
        assert "skill.show" in init_mod.INSTRUCTIONS

    def test_real_instructions_has_skill_repo_list(self):
        """INSTRUCTIONS should contain skill_repo.list."""
        assert "skill_repo.list" in init_mod.INSTRUCTIONS

    def test_real_instructions_has_stat_tool_call(self):
        """INSTRUCTIONS should contain stat.tool_call."""
        assert "stat.tool_call" in init_mod.INSTRUCTIONS

    def test_real_instructions_has_stat_tool_call_reset(self):
        """INSTRUCTIONS should contain stat.tool_call_reset."""
        assert "stat.tool_call_reset" in init_mod.INSTRUCTIONS

    def test_real_instruction_functions_work(self):
        """Some instruction functions should be callable without error (where possible)."""
        # env.get is safe to call
        result = init_mod.INSTRUCTIONS["env.get"]("NONEXISTENT_VAR_12345")
        assert result is None

    def test_real_instructions_count(self):
        """Real INSTRUCTIONS should have at least 15 entries."""
        assert len(init_mod.INSTRUCTIONS) >= 15
