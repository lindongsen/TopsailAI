"""
Unit tests for skill_hub/skill_hook.py module.

Tests the hook functionality for skill execution including:
- Hook loading and caching via get_hooks()
- SkillHookData initialization and configuration
- SkillHookHandler hook execution

Author: mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock
import os


class TestGetHooks(unittest.TestCase):
    """Test suite for get_hooks() function."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset global hooks before each test
        import topsailai.skill_hub.skill_hook as skill_hook_module
        skill_hook_module.g_hooks = {}

    def tearDown(self):
        """Clean up after each test."""
        import topsailai.skill_hub.skill_hook as skill_hook_module
        skill_hook_module.g_hooks = {}

    @patch.dict(os.environ, {"TOPSAILAI_HOOK_MODULE_SKILLS": "test_hook_module"})
    @patch("topsailai.skill_hub.skill_hook.module_tool")
    def test_get_hooks_loads_from_env_var(self, mock_module_tool):
        """Test that get_hooks() loads hooks from TOPSAILAI_HOOK_MODULE_SKILLS env var."""
        mock_module_tool.get_external_function_map.return_value = {
            "hook1": MagicMock(),
            "hook2": MagicMock(),
        }

        from topsailai.skill_hub import skill_hook
        result = skill_hook.get_hooks()

        mock_module_tool.get_external_function_map.assert_called_once_with(
            "test_hook_module", key="HOOKS"
        )
        self.assertEqual(result, {"hook1": mock_module_tool.get_external_function_map.return_value["hook1"], 
                                   "hook2": mock_module_tool.get_external_function_map.return_value["hook2"]})

    @patch.dict(os.environ, {"TOPSAILAI_HOOK_MODULE_SKILLS": "test_hook_module"})
    @patch("topsailai.skill_hub.skill_hook.module_tool")
    def test_get_hooks_caches_hooks(self, mock_module_tool):
        """Test that get_hooks() returns cached hooks on second call."""
        mock_module_tool.get_external_function_map.return_value = {
            "cached_hook": MagicMock(),
        }

        from topsailai.skill_hub import skill_hook
        first_result = skill_hook.get_hooks()
        second_result = skill_hook.get_hooks()

        # Should only call get_external_function_map once
        self.assertEqual(mock_module_tool.get_external_function_map.call_count, 1)
        self.assertEqual(first_result, second_result)
        self.assertEqual(first_result, {"cached_hook": mock_module_tool.get_external_function_map.return_value["cached_hook"]})

    @patch.dict(os.environ, {})
    def test_get_hooks_handles_empty_env_var(self):
        """Test that get_hooks() handles empty environment variable."""
        from topsailai.skill_hub import skill_hook
        result = skill_hook.get_hooks()

        self.assertEqual(result, {})

    @patch.dict(os.environ, {"TOPSAILAI_HOOK_MODULE_SKILLS": "module1,module2"})
    @patch("topsailai.skill_hub.skill_hook.module_tool")
    def test_get_hooks_merges_multiple_modules(self, mock_module_tool):
        """Test that get_hooks() merges hooks from multiple modules."""
        mock_module_tool.get_external_function_map.side_effect = [
            {"hook_a": MagicMock(), "hook_b": MagicMock()},
            {"hook_c": MagicMock(), "hook_d": MagicMock()},
        ]

        from topsailai.skill_hub import skill_hook
        result = skill_hook.get_hooks()

        self.assertEqual(mock_module_tool.get_external_function_map.call_count, 2)
        self.assertIn("hook_a", result)
        self.assertIn("hook_b", result)
        self.assertIn("hook_c", result)
        self.assertIn("hook_d", result)


class TestSkillHookDataInit(unittest.TestCase):
    """Test suite for SkillHookData.__init__() method."""

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    def test_init_stores_skill_folder_and_cmd_list(self, mock_get_hooks):
        """Test that __init__() stores skill_folder and cmd_list."""
        mock_get_hooks.return_value = {}

        from topsailai.skill_hub.skill_hook import SkillHookData
        hook_data = SkillHookData("/path/to/skill", ["cmd1", "cmd2"])

        self.assertEqual(hook_data.skill_folder, "/path/to/skill")
        self.assertEqual(hook_data.cmd_list, ["cmd1", "cmd2"])

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    def test_init_calls_get_hooks(self, mock_get_hooks):
        """Test that __init__() calls get_hooks() to populate hooks."""
        mock_get_hooks.return_value = {"test_hook": MagicMock()}

        from topsailai.skill_hub.skill_hook import SkillHookData
        hook_data = SkillHookData("/path/to/skill", ["cmd1"])

        mock_get_hooks.assert_called_once()
        self.assertEqual(hook_data.hooks, {"test_hook": mock_get_hooks.return_value["test_hook"]})

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_initializes_session_flags_to_false(self, mock_is_matched, mock_get_hooks):
        """Test that __init__() initializes need_lock_session and need_refresh_session."""
        mock_get_hooks.return_value = {}
        mock_is_matched.return_value = False

        from topsailai.skill_hub.skill_hook import SkillHookData
        hook_data = SkillHookData("/path/to/skill", ["cmd1"])

        # Initially set to False by init() when no match
        self.assertFalse(hook_data.need_lock_session)
        self.assertFalse(hook_data.need_refresh_session)


class TestSkillHookDataInitMethod(unittest.TestCase):
    """Test suite for SkillHookData.init() method."""

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch.dict(os.environ, {"TOPSAILAI_SESSION_LOCK_ON_SKILLS": "skill1,skill2"})
    def test_init_sets_lock_session_when_matched(self, mock_is_matched, mock_get_hooks):
        """Test that init() sets need_lock_session=True when skill matches."""
        mock_get_hooks.return_value = {}
        mock_is_matched.return_value = True

        from topsailai.skill_hub.skill_hook import SkillHookData
        hook_data = SkillHookData("/path/to/skill1", ["cmd1"])

        self.assertTrue(hook_data.need_lock_session)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch.dict(os.environ, {"TOPSAILAI_SESSION_LOCK_ON_SKILLS": "skill1,skill2"})
    def test_init_sets_lock_session_false_when_not_matched(self, mock_is_matched, mock_get_hooks):
        """Test that init() sets need_lock_session=False when skill does not match."""
        mock_get_hooks.return_value = {}
        mock_is_matched.return_value = False

        from topsailai.skill_hub.skill_hook import SkillHookData
        hook_data = SkillHookData("/path/to/other_skill", ["cmd1"])

        self.assertFalse(hook_data.need_lock_session)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch.dict(os.environ, {"TOPSAILAI_SESSION_REFRESH_ON_SKILLS": "skill3"})
    def test_init_sets_refresh_session_when_matched(self, mock_is_matched, mock_get_hooks):
        """Test that init() sets need_refresh_session=True when skill matches."""
        mock_get_hooks.return_value = {}
        mock_is_matched.return_value = True

        from topsailai.skill_hub.skill_hook import SkillHookData
        hook_data = SkillHookData("/path/to/skill3", ["cmd1"])

        self.assertTrue(hook_data.need_refresh_session)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch.dict(os.environ, {})
    def test_init_handles_empty_env_vars(self, mock_is_matched, mock_get_hooks):
        """Test that init() handles empty environment variables gracefully."""
        mock_get_hooks.return_value = {}
        mock_is_matched.return_value = False

        from topsailai.skill_hub.skill_hook import SkillHookData
        hook_data = SkillHookData("/path/to/skill", ["cmd1"])

        self.assertFalse(hook_data.need_lock_session)
        self.assertFalse(hook_data.need_refresh_session)


class TestSkillHookHandlerCallHook(unittest.TestCase):
    """Test suite for SkillHookHandler._call_hook() method."""

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_call_hook_executes_matching_hooks(self, mock_logger, mock_get_hooks):
        """Test that _call_hook() executes hooks matching the key suffix."""
        mock_hook1 = MagicMock()
        mock_hook2 = MagicMock()
        mock_get_hooks.return_value = {
            "before_skill_hook": mock_hook1,
            "after_skill_hook": mock_hook2,
        }

        from topsailai.skill_hub.skill_hook import SkillHookHandler
        handler = SkillHookHandler("/path/to/skill", ["cmd1"])

        handler._call_hook("before_skill_hook")

        mock_hook1.assert_called_once_with(handler)
        mock_hook2.assert_not_called()

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_call_hook_logs_exception_on_failure(self, mock_logger, mock_get_hooks):
        """Test that _call_hook() logs exceptions without raising."""
        mock_hook = MagicMock(side_effect=Exception("Hook error"))
        mock_get_hooks.return_value = {
            "test_hook": mock_hook,
        }

        from topsailai.skill_hub.skill_hook import SkillHookHandler
        handler = SkillHookHandler("/path/to/skill", ["cmd1"])

        # Should not raise exception
        handler._call_hook("test_hook")

        mock_logger.exception.assert_called_once()
        mock_hook.assert_called_once_with(handler)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    def test_call_hook_does_nothing_when_no_hooks(self, mock_get_hooks):
        """Test that _call_hook() does nothing when hooks dict is empty."""
        mock_get_hooks.return_value = {}

        from topsailai.skill_hub.skill_hook import SkillHookHandler
        handler = SkillHookHandler("/path/to/skill", ["cmd1"])

        # Should not raise any exception
        handler._call_hook("any_key")

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_call_hook_skips_non_matching_hooks(self, mock_logger, mock_get_hooks):
        """Test that _call_hook() skips hooks that don't match the key suffix."""
        mock_hook1 = MagicMock()
        mock_hook2 = MagicMock()
        mock_get_hooks.return_value = {
            "other_hook": mock_hook1,
            "before_skill_hook": mock_hook2,
        }

        from topsailai.skill_hub.skill_hook import SkillHookHandler
        handler = SkillHookHandler("/path/to/skill", ["cmd1"])

        handler._call_hook("before_skill_hook")

        mock_hook1.assert_not_called()
        mock_hook2.assert_called_once_with(handler)


class TestSkillHookHandlerBeforeAfter(unittest.TestCase):
    """Test suite for handle_before_call_skill() and handle_after_call_skill() methods."""

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_handle_before_call_skill_calls_correct_key(self, mock_logger, mock_get_hooks):
        """Test that handle_before_call_skill() calls _call_hook with correct key."""
        mock_get_hooks.return_value = {}

        from topsailai.skill_hub.skill_hook import SkillHookHandler
        handler = SkillHookHandler("/path/to/skill", ["cmd1"])

        with patch.object(handler, "_call_hook") as mock_call_hook:
            handler.handle_before_call_skill()
            mock_call_hook.assert_called_once_with(SkillHookHandler.KEY_HANDLE_BEFORE_CALL_SKILL)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_handle_after_call_skill_calls_correct_key(self, mock_logger, mock_get_hooks):
        """Test that handle_after_call_skill() calls _call_hook with correct key."""
        mock_get_hooks.return_value = {}

        from topsailai.skill_hub.skill_hook import SkillHookHandler
        handler = SkillHookHandler("/path/to/skill", ["cmd1"])

        with patch.object(handler, "_call_hook") as mock_call_hook:
            handler.handle_after_call_skill()
            mock_call_hook.assert_called_once_with(SkillHookHandler.KEY_HANDLE_AFTER_CALL_SKILL)


if __name__ == "__main__":
    unittest.main()
