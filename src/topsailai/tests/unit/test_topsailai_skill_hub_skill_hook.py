"""
Unit tests for skill_hub/skill_hook.py module.

This module tests the hook functionality for skill execution, including:
- Hook initialization and caching
- Session locking configuration
- Session refresh configuration
- Before/after hook execution

Author: mm-m25
"""

import os
import unittest
from unittest.mock import MagicMock, patch


class TestGetHooks(unittest.TestCase):
    """Test cases for get_hooks() function."""

    def setUp(self):
        """Set up test fixtures."""
        import topsailai.skill_hub.skill_hook as skill_hook_module
        skill_hook_module.g_hooks = {}

    def tearDown(self):
        """Clean up after each test."""
        import topsailai.skill_hub.skill_hook as skill_hook_module
        skill_hook_module.g_hooks = {}

    @patch.dict(os.environ, {"TOPSAILAI_HOOK_MODULE_SKILLS": ""})
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    def test_get_hooks_empty_env_var(self, mock_env_tool):
        """Test get_hooks returns empty dict when env var is empty."""
        import topsailai.skill_hub.skill_hook as skill_hook_module

        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        result = skill_hook_module.get_hooks()

        self.assertEqual(result, {})
        mock_env_tool.EnvReaderInstance.get_list_str.assert_called_once()

    @patch.dict(os.environ, {"TOPSAILAI_HOOK_MODULE_SKILLS": ""})
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    def test_get_hooks_none_env_var(self, mock_env_tool):
        """Test get_hooks returns empty dict when env var is None."""
        import topsailai.skill_hub.skill_hook as skill_hook_module

        mock_env_tool.EnvReaderInstance.get_list_str.return_value = None

        result = skill_hook_module.get_hooks()

        self.assertEqual(result, {})

    @patch.dict(os.environ, {"TOPSAILAI_HOOK_MODULE_SKILLS": "test_module"})
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.module_tool")
    def test_get_hooks_loads_from_module(self, mock_module_tool, mock_env_tool):
        """Test get_hooks loads hooks from module."""
        import topsailai.skill_hub.skill_hook as skill_hook_module

        mock_env_tool.EnvReaderInstance.get_list_str.return_value = ["test_module"]
        mock_module_tool.get_external_function_map.return_value = {
            "hook1": MagicMock(),
            "hook2": MagicMock()
        }

        result = skill_hook_module.get_hooks()

        self.assertEqual(len(result), 2)
        self.assertIn("hook1", result)
        self.assertIn("hook2", result)
        mock_module_tool.get_external_function_map.assert_called_once_with("test_module", key="HOOKS")

    @patch.dict(os.environ, {"TOPSAILAI_HOOK_MODULE_SKILLS": "test_module"})
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.module_tool")
    def test_get_hooks_caching(self, mock_module_tool, mock_env_tool):
        """Test get_hooks returns cached hooks on second call."""
        import topsailai.skill_hub.skill_hook as skill_hook_module

        mock_env_tool.EnvReaderInstance.get_list_str.return_value = ["test_module"]
        mock_module_tool.get_external_function_map.return_value = {"hook1": MagicMock()}

        result1 = skill_hook_module.get_hooks()
        result2 = skill_hook_module.get_hooks()

        self.assertEqual(result1, result2)
        self.assertEqual(mock_module_tool.get_external_function_map.call_count, 1)

    @patch.dict(os.environ, {"TOPSAILAI_HOOK_MODULE_SKILLS": "module1,module2"})
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.module_tool")
    def test_get_hooks_merges_multiple_modules(self, mock_module_tool, mock_env_tool):
        """Test get_hooks merges hooks from multiple modules."""
        import topsailai.skill_hub.skill_hook as skill_hook_module

        mock_env_tool.EnvReaderInstance.get_list_str.return_value = ["module1", "module2"]
        mock_module_tool.get_external_function_map.side_effect = [
            {"hook1": MagicMock()},
            {"hook2": MagicMock()}
        ]

        result = skill_hook_module.get_hooks()

        self.assertEqual(len(result), 2)
        self.assertIn("hook1", result)
        self.assertIn("hook2", result)
        self.assertEqual(mock_module_tool.get_external_function_map.call_count, 2)

    @patch.dict(os.environ, {"TOPSAILAI_HOOK_MODULE_SKILLS": "test_module"})
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.module_tool")
    def test_get_hooks_handles_none_from_module(self, mock_module_tool, mock_env_tool):
        """Test get_hooks handles None returned from module."""
        import topsailai.skill_hub.skill_hook as skill_hook_module

        mock_env_tool.EnvReaderInstance.get_list_str.return_value = ["test_module"]
        mock_module_tool.get_external_function_map.return_value = None

        result = skill_hook_module.get_hooks()

        self.assertEqual(result, {})


class TestSkillHookDataInit(unittest.TestCase):
    """Test cases for SkillHookData.__init__() method."""

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_stores_skill_folder(self, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test __init__ stores skill_folder attribute."""
        from topsailai.skill_hub.skill_hook import SkillHookData

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        hook_data = SkillHookData("/path/to/skill", ["cmd1"])

        self.assertEqual(hook_data.skill_folder, "/path/to/skill")

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_stores_cmd_list(self, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test __init__ stores cmd_list attribute."""
        from topsailai.skill_hub.skill_hook import SkillHookData

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        hook_data = SkillHookData("/path/to/skill", ["cmd1", "cmd2"])

        self.assertEqual(hook_data.cmd_list, ["cmd1", "cmd2"])

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_loads_hooks(self, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test __init__ loads hooks via get_hooks()."""
        from topsailai.skill_hub.skill_hook import SkillHookData

        mock_hooks = {"hook1": MagicMock()}
        mock_get_hooks.return_value = mock_hooks
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        hook_data = SkillHookData("/path/to/skill", ["cmd1"])

        self.assertEqual(hook_data.hooks, mock_hooks)
        mock_get_hooks.assert_called_once()


class TestSkillHookDataInitSessionLock(unittest.TestCase):
    """Test cases for SkillHookData.init() session locking."""

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_need_lock_session_true(self, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test need_lock_session is True when skill matches env var."""
        from topsailai.skill_hub.skill_hook import SkillHookData

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = ["skill1", "skill2"]
        mock_is_matched.return_value = True

        hook_data = SkillHookData("/path/to/skill1", ["cmd1"])

        self.assertTrue(hook_data.need_lock_session)
        mock_is_matched.assert_called_with("/path/to/skill1", ["skill1", "skill2"])

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_need_lock_session_false_no_match(self, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test need_lock_session is False when skill does not match."""
        from topsailai.skill_hub.skill_hook import SkillHookData

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = ["skill1", "skill2"]
        mock_is_matched.return_value = False

        hook_data = SkillHookData("/path/to/other", ["cmd1"])

        self.assertFalse(hook_data.need_lock_session)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_need_lock_session_empty_env(self, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test need_lock_session is False when env var list is empty."""
        from topsailai.skill_hub.skill_hook import SkillHookData

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []
        mock_is_matched.return_value = False

        hook_data = SkillHookData("/path/to/skill", ["cmd1"])

        self.assertFalse(hook_data.need_lock_session)
        mock_is_matched.assert_called_with("/path/to/skill", [])


class TestSkillHookDataInitSessionRefresh(unittest.TestCase):
    """Test cases for SkillHookData.init() session refresh."""

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_need_refresh_session_true(self, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test need_refresh_session is True when skill matches env var."""
        from topsailai.skill_hub.skill_hook import SkillHookData

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.side_effect = [
            [],  # lock check
            ["refresh_skill"]  # refresh check
        ]
        mock_is_matched.return_value = True

        hook_data = SkillHookData("/path/to/refresh_skill", ["cmd1"])

        self.assertTrue(hook_data.need_refresh_session)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_need_refresh_session_false_no_match(self, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test need_refresh_session is False when skill does not match."""
        from topsailai.skill_hub.skill_hook import SkillHookData

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.side_effect = [
            [],  # lock check
            ["refresh_skill"]  # refresh check
        ]
        mock_is_matched.return_value = False

        hook_data = SkillHookData("/path/to/other", ["cmd1"])

        self.assertFalse(hook_data.need_refresh_session)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    def test_init_need_refresh_session_empty_env(self, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test need_refresh_session is False when env var list is empty."""
        from topsailai.skill_hub.skill_hook import SkillHookData

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.side_effect = [
            [],  # lock check
            []  # refresh check
        ]
        mock_is_matched.return_value = False

        hook_data = SkillHookData("/path/to/skill", ["cmd1"])

        self.assertFalse(hook_data.need_refresh_session)
        mock_is_matched.assert_called_with("/path/to/skill", [])


class TestSkillHookHandlerCallHook(unittest.TestCase):
    """Test cases for SkillHookHandler._call_hook() method."""

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_call_hook_no_hooks(self, mock_logger, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test _call_hook does nothing when hooks dict is empty."""
        from topsailai.skill_hub.skill_hook import SkillHookHandler

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        handler = SkillHookHandler("/path/to/skill", ["cmd1"])
        handler._call_hook("some_key")

        mock_logger.exception.assert_not_called()

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_call_hook_calls_matching_hooks(self, mock_logger, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test _call_hook calls hooks that match the key suffix."""
        from topsailai.skill_hub.skill_hook import SkillHookHandler

        mock_hook1 = MagicMock()
        mock_hook2 = MagicMock()
        mock_get_hooks.return_value = {
            "prefix_handle_before_call_skill": mock_hook1,
            "other_hook": mock_hook2,
            "another_handle_before_call_skill": MagicMock()
        }
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        handler = SkillHookHandler("/path/to/skill", ["cmd1"])
        handler._call_hook("handle_before_call_skill")

        self.assertEqual(mock_hook1.call_count, 1)
        self.assertEqual(mock_hook2.call_count, 0)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_call_hook_passes_self_to_hook(self, mock_logger, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test _call_hook passes self to hook function."""
        from topsailai.skill_hub.skill_hook import SkillHookHandler

        mock_hook = MagicMock()
        mock_get_hooks.return_value = {
            "test_hook_handle_before_call_skill": mock_hook
        }
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        handler = SkillHookHandler("/path/to/skill", ["cmd1"])
        handler._call_hook("handle_before_call_skill")

        mock_hook.assert_called_once_with(handler)

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_call_hook_logs_exception(self, mock_logger, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test _call_hook logs exception without raising."""
        from topsailai.skill_hub.skill_hook import SkillHookHandler

        mock_hook = MagicMock(side_effect=ValueError("test error"))
        mock_get_hooks.return_value = {
            "test_hook_handle_before_call_skill": mock_hook
        }
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        handler = SkillHookHandler("/path/to/skill", ["cmd1"])

        handler._call_hook("handle_before_call_skill")

        mock_logger.exception.assert_called_once()
        self.assertIn("call hook failed", mock_logger.exception.call_args[0][0])

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_call_hook_continues_on_exception(self, mock_logger, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test _call_hook continues to next hook after exception."""
        from topsailai.skill_hub.skill_hook import SkillHookHandler

        mock_hook1 = MagicMock(side_effect=ValueError("error"))
        mock_hook2 = MagicMock()
        mock_get_hooks.return_value = {
            "hook1_handle_before_call_skill": mock_hook1,
            "hook2_handle_before_call_skill": mock_hook2
        }
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        handler = SkillHookHandler("/path/to/skill", ["cmd1"])
        handler._call_hook("handle_before_call_skill")

        self.assertEqual(mock_hook2.call_count, 1)


class TestSkillHookHandlerBeforeAfter(unittest.TestCase):
    """Test cases for before/after hook execution methods."""

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_handle_before_call_skill(self, mock_logger, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test handle_before_call_skill calls _call_hook with correct key."""
        from topsailai.skill_hub.skill_hook import SkillHookHandler

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        handler = SkillHookHandler("/path/to/skill", ["cmd1"])

        with patch.object(handler, "_call_hook") as mock_call_hook:
            handler.handle_before_call_skill()
            mock_call_hook.assert_called_once_with("handle_before_call_skill")

    @patch("topsailai.skill_hub.skill_hook.get_hooks")
    @patch("topsailai.skill_hub.skill_hook.env_tool")
    @patch("topsailai.skill_hub.skill_hook.is_matched_skill")
    @patch("topsailai.skill_hub.skill_hook.logger")
    def test_handle_after_call_skill(self, mock_logger, mock_is_matched, mock_env_tool, mock_get_hooks):
        """Test handle_after_call_skill calls _call_hook with correct key."""
        from topsailai.skill_hub.skill_hook import SkillHookHandler

        mock_get_hooks.return_value = {}
        mock_env_tool.EnvReaderInstance.get_list_str.return_value = []

        handler = SkillHookHandler("/path/to/skill", ["cmd1"])

        with patch.object(handler, "_call_hook") as mock_call_hook:
            handler.handle_after_call_skill()
            mock_call_hook.assert_called_once_with("handle_after_call_skill")


class TestSkillHookHandlerConstants(unittest.TestCase):
    """Test cases for SkillHookHandler class constants."""

    def test_handler_has_before_constant(self):
        """Test SkillHookHandler has KEY_HANDLE_BEFORE_CALL_SKILL constant."""
        from topsailai.skill_hub.skill_hook import SkillHookHandler

        self.assertTrue(hasattr(SkillHookHandler, "KEY_HANDLE_BEFORE_CALL_SKILL"))
        self.assertEqual(
            SkillHookHandler.KEY_HANDLE_BEFORE_CALL_SKILL,
            "handle_before_call_skill"
        )

    def test_handler_has_after_constant(self):
        """Test SkillHookHandler has KEY_HANDLE_AFTER_CALL_SKILL constant."""
        from topsailai.skill_hub.skill_hook import SkillHookHandler

        self.assertTrue(hasattr(SkillHookHandler, "KEY_HANDLE_AFTER_CALL_SKILL"))
        self.assertEqual(
            SkillHookHandler.KEY_HANDLE_AFTER_CALL_SKILL,
            "handle_after_call_skill"
        )


if __name__ == "__main__":
    unittest.main()
