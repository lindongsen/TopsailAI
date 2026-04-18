"""
Unit tests for ai_base/prompt_base module - ThresholdContextHistory and utility functions.

Test coverage:
- ThresholdContextHistory class (threshold checking logic)
- get_prompt_by_cmd function (command execution)
- get_prompt_by_script function (script-based prompt retrieval)

Author: mm-m25
"""

import os
import sys
import unittest
from unittest.mock import patch


class TestThresholdContextHistory(unittest.TestCase):
    """Test cases for ThresholdContextHistory class."""

    def setUp(self):
        """Set environment variables to known default values for deterministic tests."""
        # Store original values for restoration
        self.original_env = {}
        for var in ["CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS", "CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH"]:
            self.original_env[var] = os.environ.get(var)
        
        # EXPLICITLY SET to defaults to override .env pollution
        os.environ["CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS"] = "1280000"
        os.environ["CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH"] = "43"

    def tearDown(self):
        """Restore original environment variables after each test."""
        # Clear module cache FIRST to ensure fresh imports
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]
        
        # Restore original env vars
        for var, original_value in self.original_env.items():
            if original_value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = original_value

    @patch("dotenv.load_dotenv")
    def test_init_default_values(self, mock_load_dotenv):
        """Test that default values are used when env vars are not set."""
        # Temporarily delete env vars to test defaults
        original_tokens = os.environ.pop("CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS", None)
        original_len = os.environ.pop("CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH", None)
        try:
            # Clear module cache to force re-import
            modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
            for mod in modules_to_clear:
                del sys.modules[mod]
            
            # Re-import after clearing env vars
            from topsailai.ai_base.prompt_base import ThresholdContextHistory
            threshold = ThresholdContextHistory()
            
            assert threshold.token_max == 1280000
            assert threshold.slim_len == 43
        finally:
            # Restore env vars
            if original_tokens is not None:
                os.environ["CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS"] = original_tokens
            if original_len is not None:
                os.environ["CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH"] = original_len

    def test_init_env_override_token_max(self):
        """Test that CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS env var overrides token_max."""
        os.environ["CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS"] = "640000"
        if "topsailai.ai_base.prompt_base" in sys.modules:
            del sys.modules["topsailai.ai_base.prompt_base"]

        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        self.assertEqual(instance.token_max, 640000)

    def test_init_env_override_slim_len(self):
        """Test that CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH env var overrides slim_len."""
        os.environ["CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH"] = "50"
        if "topsailai.ai_base.prompt_base" in sys.modules:
            del sys.modules["topsailai.ai_base.prompt_base"]

        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        self.assertEqual(instance.slim_len, 50)

    def test_exceed_ratio_true(self):
        """Test exceed_ratio returns True when token count is at or above 0.8 ratio."""
        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        # 1024000 / 1280000 = 0.8 exactly
        result = instance.exceed_ratio(1024000)
        self.assertTrue(result)

    def test_exceed_ratio_false(self):
        """Test exceed_ratio returns False when token count is below 0.8 ratio."""
        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        # 100000 / 1280000 = 0.078 < 0.8
        result = instance.exceed_ratio(100000)
        self.assertFalse(result)

    def test_exceed_ratio_exact_boundary(self):
        """Test exceed_ratio returns True at exact boundary (>= comparison)."""
        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        # Exactly 0.8 * 1280000 = 1024000
        result = instance.exceed_ratio(1024000)
        self.assertTrue(result)

    def test_exceed_msg_len_true(self):
        """Test exceed_msg_len returns True when msg_len equals slim_len."""
        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        # slim_len=43, msg_len=43 should be True (>= comparison)
        result = instance.exceed_msg_len(43)
        self.assertTrue(result)

    def test_exceed_msg_len_false(self):
        """Test exceed_msg_len returns False when msg_len is below threshold."""
        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        # slim_len=43, msg_len=42 should be False
        result = instance.exceed_msg_len(42)
        self.assertFalse(result)

    def test_exceed_msg_len_with_small_slim_len(self):
        """Test exceed_msg_len uses SLIM_MIN_LEN when slim_len is smaller."""
        os.environ["CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH"] = "10"
        if "topsailai.ai_base.prompt_base" in sys.modules:
            del sys.modules["topsailai.ai_base.prompt_base"]

        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        # slim_len=10, but SLIM_MIN_LEN=27, so threshold is max(27, 10)=27
        # msg_len=27 should be True (>= comparison)
        result = instance.exceed_msg_len(27)
        self.assertTrue(result)

    def test_exceed_msg_len_with_small_slim_len_false(self):
        """Test exceed_msg_len returns False when msg_len is below max threshold."""
        os.environ["CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH"] = "10"
        if "topsailai.ai_base.prompt_base" in sys.modules:
            del sys.modules["topsailai.ai_base.prompt_base"]

        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        # slim_len=10, but SLIM_MIN_LEN=27, so threshold is max(27, 10)=27
        # msg_len=26 should be False
        result = instance.exceed_msg_len(26)
        self.assertFalse(result)

    @patch("topsailai.ai_base.prompt_base.count_tokens")
    def test_is_exceeded_by_msg_len(self, mock_count_tokens):
        """Test is_exceeded returns True when message length exceeds threshold."""
        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        # Create messages list with length >= slim_len (43)
        messages = [{"role": "user", "content": f"msg{i}"} for i in range(50)]
        mock_count_tokens.return_value = 100  # Low token count

        result = instance.is_exceeded(messages)
        self.assertTrue(result)

    @patch("topsailai.ai_base.prompt_base.count_tokens")
    def test_is_exceeded_by_token_ratio(self, mock_count_tokens):
        """Test is_exceeded returns True when token ratio exceeds threshold."""
        from topsailai.ai_base.prompt_base import ThresholdContextHistory
        instance = ThresholdContextHistory()

        messages = [{"role": "user", "content": "test"}]
        # Mock count_tokens to return high value (>= 0.8 * 1280000)
        mock_count_tokens.return_value = 1100000

        result = instance.is_exceeded(messages)
        self.assertTrue(result)


class TestGetPromptByCmd(unittest.TestCase):
    """Test cases for get_prompt_by_cmd function."""

    @patch("topsailai.ai_base.prompt_base.cmd_tool")
    def test_get_prompt_by_cmd_success(self, mock_cmd_tool):
        """Test get_prompt_by_cmd returns stripped content on success."""
        from topsailai.ai_base.prompt_base import get_prompt_by_cmd

        mock_cmd_tool.exec_cmd.return_value = (0, "hello world\n")

        result = get_prompt_by_cmd("echo hello")

        self.assertEqual(result, "hello world")
        mock_cmd_tool.exec_cmd.assert_called_once_with("echo hello", timeout=60)

    @patch("topsailai.ai_base.prompt_base.cmd_tool")
    def test_get_prompt_by_cmd_failure(self, mock_cmd_tool):
        """Test get_prompt_by_cmd returns empty string on command failure."""
        from topsailai.ai_base.prompt_base import get_prompt_by_cmd

        mock_cmd_tool.exec_cmd.return_value = (1, "error message")

        result = get_prompt_by_cmd("false")

        self.assertEqual(result, "")

    @patch("topsailai.ai_base.prompt_base.cmd_tool")
    def test_get_prompt_by_cmd_empty_output(self, mock_cmd_tool):
        """Test get_prompt_by_cmd returns empty string when output is whitespace only."""
        from topsailai.ai_base.prompt_base import get_prompt_by_cmd

        mock_cmd_tool.exec_cmd.return_value = (0, "   \n")

        result = get_prompt_by_cmd("echo ''")

        self.assertEqual(result, "")


class TestGetPromptByScript(unittest.TestCase):
    """Test cases for get_prompt_by_script function."""

    @patch.dict(os.environ, {}, clear=True)
    def test_get_prompt_by_script_no_env(self):
        """Test get_prompt_by_script returns empty string when env var is not set."""
        from topsailai.ai_base.prompt_base import get_prompt_by_script

        result = get_prompt_by_script("TOPSAILAI_OBTAIN_SYSTEM_PROMPT_SCRIPT")

        self.assertEqual(result, "")

    @patch("topsailai.ai_base.prompt_base.get_prompt_by_cmd")
    @patch.dict(os.environ, {"TOPSAILAI_OBTAIN_SYSTEM_PROMPT_SCRIPT": "/path/to/script.sh"})
    def test_get_prompt_by_script_with_env(self, mock_get_prompt_by_cmd):
        """Test get_prompt_by_script calls get_prompt_by_cmd when env var is set."""
        from topsailai.ai_base.prompt_base import get_prompt_by_script

        mock_get_prompt_by_cmd.return_value = "prompt content"

        result = get_prompt_by_script("TOPSAILAI_OBTAIN_SYSTEM_PROMPT_SCRIPT")

        self.assertEqual(result, "prompt content")
        mock_get_prompt_by_cmd.assert_called_once_with("/path/to/script.sh")


if __name__ == "__main__":
    unittest.main()
