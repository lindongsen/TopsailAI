"""
Unit tests for ai_team/role.py

Test coverage:
- Constants: MANAGER_STARTSWITH, MEMBER_STARTSWITH
- get_manager_name(): Manager name resolution with env vars and defaults
- get_member_name(): Member name resolution with env vars and defaults
- get_manager_prompt(): Manager prompt generation
- get_member_prompt(): Member prompt generation with values file support
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock, mock_open

# Add project root to path
sys.path.insert(0, '/root/ai/TopsailAI/src')


class TestRoleConstants(unittest.TestCase):
    """Test cases for role module constants"""

    def test_manager_startswith_constant_value(self):
        """Test MANAGER_STARTSWITH constant has correct value 'AIManager.'"""
        from topsailai.ai_team.role import MANAGER_STARTSWITH
        self.assertEqual(MANAGER_STARTSWITH, "AIManager.")

    def test_member_startswith_constant_value(self):
        """Test MEMBER_STARTSWITH constant has correct value 'AIMember.'"""
        from topsailai.ai_team.role import MEMBER_STARTSWITH
        self.assertEqual(MEMBER_STARTSWITH, "AIMember.")


class TestGetManagerName(unittest.TestCase):
    """Test cases for get_manager_name() function"""

    def setUp(self):
        """Set up clean environment for each test"""
        self.temp_dir = tempfile.mkdtemp()
        # Create a clean copy of environment without TOPSAILAI_TEAM_MANAGER_NAME
        self.clean_env = os.environ.copy()
        if "TOPSAILAI_TEAM_MANAGER_NAME" in self.clean_env:
            del self.clean_env["TOPSAILAI_TEAM_MANAGER_NAME"]
        if "TOPSAILAI_AGENT_NAME" in self.clean_env:
            del self.clean_env["TOPSAILAI_AGENT_NAME"]
        self.env_patcher = patch.dict(os.environ, self.clean_env, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        """Clean up environment and temp directory"""
        self.env_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_manager_name_returns_default_when_none_provided(self):
        """Test get_manager_name returns 'AIManager.Manager' when no name provided and no env vars"""
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name(None)
        self.assertEqual(result, "AIManager.Manager")

    def test_get_manager_name_with_explicit_name(self):
        """Test get_manager_name adds AIManager. prefix to explicit name"""
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name("TestManager")
        self.assertEqual(result, "AIManager.TestManager")

    def test_get_manager_name_already_prefixed_no_double_prefix(self):
        """Test get_manager_name does not double-prefix when name already has AIManager."""
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name("AIManager.Existing")
        self.assertEqual(result, "AIManager.Existing")

    def test_get_manager_name_from_team_manager_env_var(self):
        """Test get_manager_name reads from TOPSAILAI_TEAM_MANAGER_NAME environment variable"""
        with patch.dict(os.environ, {"TOPSAILAI_TEAM_MANAGER_NAME": "EnvManager"}):
            from topsailai.ai_team.role import get_manager_name
            result = get_manager_name(None)
            self.assertEqual(result, "AIManager.EnvManager")

    def test_get_manager_name_from_agent_name_env_var(self):
        """Test get_manager_name falls back to TOPSAILAI_AGENT_NAME when TEAM_MANAGER not set"""
        with patch.dict(os.environ, {"TOPSAILAI_AGENT_NAME": "AgentManager"}):
            from topsailai.ai_team.role import get_manager_name
            result = get_manager_name(None)
            self.assertEqual(result, "AIManager.AgentManager")

    def test_get_manager_name_team_var_takes_precedence(self):
        """Test TOPSAILAI_TEAM_MANAGER_NAME takes precedence over TOPSAILAI_AGENT_NAME"""
        with patch.dict(os.environ, {
            "TOPSAILAI_TEAM_MANAGER_NAME": "TeamMgr",
            "TOPSAILAI_AGENT_NAME": "AgentMgr"
        }):
            from topsailai.ai_team.role import get_manager_name
            result = get_manager_name(None)
            self.assertEqual(result, "AIManager.TeamMgr")

    def test_get_manager_name_empty_string_defaults(self):
        """Test get_manager_name returns default when empty string provided"""
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name("")
        self.assertEqual(result, "AIManager.Manager")

    def test_get_manager_name_with_spaces(self):
        """Test get_manager_name handles name with spaces"""
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name("My Manager")
        self.assertEqual(result, "AIManager.My Manager")


class TestGetMemberName(unittest.TestCase):
    """Test cases for get_member_name() function"""

    def setUp(self):
        """Set up clean environment for each test"""
        self.temp_dir = tempfile.mkdtemp()
        self.clean_env = os.environ.copy()
        if "TOPSAILAI_TEAM_MEMBER_NAME" in self.clean_env:
            del self.clean_env["TOPSAILAI_TEAM_MEMBER_NAME"]
        if "TOPSAILAI_AGENT_NAME" in self.clean_env:
            del self.clean_env["TOPSAILAI_AGENT_NAME"]
        self.env_patcher = patch.dict(os.environ, self.clean_env, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        """Clean up environment and temp directory"""
        self.env_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_member_name_returns_default_when_none_provided(self):
        """Test get_member_name returns 'AIMember.Member' when no name provided and no env vars"""
        from topsailai.ai_team.role import get_member_name
        result = get_member_name(None)
        self.assertEqual(result, "AIMember.Member")

    def test_get_member_name_with_explicit_name(self):
        """Test get_member_name adds AIMember. prefix to explicit name"""
        from topsailai.ai_team.role import get_member_name
        result = get_member_name("TestMember")
        self.assertEqual(result, "AIMember.TestMember")

    def test_get_member_name_already_prefixed_no_double_prefix(self):
        """Test get_member_name does not double-prefix when name already has AIMember."""
        from topsailai.ai_team.role import get_member_name
        result = get_member_name("AIMember.Existing")
        self.assertEqual(result, "AIMember.Existing")

    def test_get_member_name_from_team_member_env_var(self):
        """Test get_member_name reads from TOPSAILAI_TEAM_MEMBER_NAME environment variable"""
        with patch.dict(os.environ, {"TOPSAILAI_TEAM_MEMBER_NAME": "EnvMember"}):
            from topsailai.ai_team.role import get_member_name
            result = get_member_name(None)
            self.assertEqual(result, "AIMember.EnvMember")

    def test_get_member_name_from_agent_name_env_var(self):
        """Test get_member_name falls back to TOPSAILAI_AGENT_NAME when TEAM_MEMBER not set"""
        with patch.dict(os.environ, {"TOPSAILAI_AGENT_NAME": "AgentMember"}):
            from topsailai.ai_team.role import get_member_name
            result = get_member_name(None)
            self.assertEqual(result, "AIMember.AgentMember")

    def test_get_member_name_team_var_takes_precedence(self):
        """Test TOPSAILAI_TEAM_MEMBER_NAME takes precedence over TOPSAILAI_AGENT_NAME"""
        with patch.dict(os.environ, {
            "TOPSAILAI_TEAM_MEMBER_NAME": "TeamMem",
            "TOPSAILAI_AGENT_NAME": "AgentMem"
        }):
            from topsailai.ai_team.role import get_member_name
            result = get_member_name(None)
            self.assertEqual(result, "AIMember.TeamMem")

    def test_get_member_name_empty_string_defaults(self):
        """Test get_member_name returns default when empty string provided"""
        from topsailai.ai_team.role import get_member_name
        result = get_member_name("")
        self.assertEqual(result, "AIMember.Member")


class TestGetManagerPrompt(unittest.TestCase):
    """Test cases for get_manager_prompt() function"""

    def setUp(self):
        """Set up clean environment for each test"""
        self.clean_env = os.environ.copy()
        if "TOPSAILAI_TEAM_MANAGER_NAME" in self.clean_env:
            del self.clean_env["TOPSAILAI_TEAM_MANAGER_NAME"]
        if "TOPSAILAI_AGENT_NAME" in self.clean_env:
            del self.clean_env["TOPSAILAI_AGENT_NAME"]
        self.env_patcher = patch.dict(os.environ, self.clean_env, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        """Clean up environment"""
        self.env_patcher.stop()

    def test_get_manager_prompt_contains_role_info(self):
        """Test get_manager_prompt contains 'YOUR ROLE IS Manager'"""
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt("TestManager")
        self.assertIn("YOUR ROLE IS Manager", result)

    def test_get_manager_prompt_contains_agent_name(self):
        """Test get_manager_prompt contains the agent name with AIManager. prefix"""
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt("TestManager")
        self.assertIn("AIManager.TestManager", result)

    def test_get_manager_prompt_uses_default_when_none_provided(self):
        """Test get_manager_prompt uses 'AIManager.Manager' when no name provided"""
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt(None)
        self.assertIn("AIManager.Manager", result)

    def test_get_manager_prompt_returns_string(self):
        """Test get_manager_prompt returns a string type"""
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt("TestManager")
        self.assertIsInstance(result, str)

    def test_get_manager_prompt_format_with_dashes(self):
        """Test get_manager_prompt contains dashes for formatting"""
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt("TestManager")
        self.assertIn("---", result)


class TestGetMemberPrompt(unittest.TestCase):
    """Test cases for get_member_prompt() function"""

    def setUp(self):
        """Set up temporary directory for values files"""
        self.temp_dir = tempfile.mkdtemp()
        self.env_patcher = patch.dict(os.environ, {
            "TOPSAILAI_TEAM_PATH": self.temp_dir
        })
        self.env_patcher.start()

    def tearDown(self):
        """Clean up temporary directory and environment"""
        self.env_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_member_prompt_contains_role_info(self):
        """Test get_member_prompt contains 'YOUR ROLE IS Member'"""
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("TestMember")
        self.assertIn("YOUR ROLE IS Member", result)

    def test_get_member_prompt_contains_agent_name(self):
        """Test get_member_prompt contains the agent name with AIMember. prefix"""
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("TestMember")
        self.assertIn("AIMember.TestMember", result)

    def test_get_member_prompt_returns_string(self):
        """Test get_member_prompt returns a string type"""
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("TestMember")
        self.assertIsInstance(result, str)

    def test_get_member_prompt_with_existing_values_file(self):
        """Test get_member_prompt reads and includes content from .values file"""
        values_path = os.path.join(self.temp_dir, "TestMember.values")
        with open(values_path, 'w', encoding='utf-8') as f:
            f.write("Custom values content here")
        
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("TestMember")
        self.assertIn("Custom values content here", result)

    def test_get_member_prompt_without_values_file(self):
        """Test get_member_prompt works correctly when .values file does not exist"""
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("NoValuesMember")
        self.assertIn("YOUR ROLE IS Member", result)
        self.assertIn("AIMember.NoValuesMember", result)

    def test_get_member_prompt_ends_with_dashes(self):
        """Test get_member_prompt ends with --- separator"""
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("TestMember")
        self.assertTrue(result.strip().endswith("---"))

    def test_get_member_prompt_with_already_prefixed_name(self):
        """Test get_member_prompt handles already prefixed name correctly"""
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("AIMember.Existing")
        self.assertIn("AIMember.Existing", result)

    def test_get_member_prompt_empty_values_file(self):
        """Test get_member_prompt handles empty .values file"""
        values_path = os.path.join(self.temp_dir, "EmptyMember.values")
        with open(values_path, 'w', encoding='utf-8') as f:
            f.write("")
        
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("EmptyMember")
        self.assertIn("YOUR ROLE IS Member", result)


class TestRolePrefixConstants(unittest.TestCase):
    """Test cases for role prefix constants behavior"""

    def test_manager_startswith_used_in_get_manager_name(self):
        """Test MANAGER_STARTSWITH is used correctly in get_manager_name"""
        from topsailai.ai_team.role import get_manager_name, MANAGER_STARTSWITH
        result = get_manager_name("Custom")
        self.assertTrue(result.startswith(MANAGER_STARTSWITH))

    def test_member_startswith_used_in_get_member_name(self):
        """Test MEMBER_STARTSWITH is used correctly in get_member_name"""
        from topsailai.ai_team.role import get_member_name, MEMBER_STARTSWITH
        result = get_member_name("Custom")
        self.assertTrue(result.startswith(MEMBER_STARTSWITH))

    def test_prefix_constants_are_strings(self):
        """Test both prefix constants are strings"""
        from topsailai.ai_team.role import MANAGER_STARTSWITH, MEMBER_STARTSWITH
        self.assertIsInstance(MANAGER_STARTSWITH, str)
        self.assertIsInstance(MEMBER_STARTSWITH, str)

    def test_prefix_constants_are_not_empty(self):
        """Test both prefix constants are not empty"""
        from topsailai.ai_team.role import MANAGER_STARTSWITH, MEMBER_STARTSWITH
        self.assertTrue(len(MANAGER_STARTSWITH) > 0)
        self.assertTrue(len(MEMBER_STARTSWITH) > 0)


class TestRoleIntegration(unittest.TestCase):
    """Integration tests for role module functions working together"""

    def setUp(self):
        """Set up clean environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.clean_env = os.environ.copy()
        for key in ["TOPSAILAI_TEAM_MANAGER_NAME", "TOPSAILAI_TEAM_MEMBER_NAME", "TOPSAILAI_AGENT_NAME"]:
            if key in self.clean_env:
                del self.clean_env[key]
        self.clean_env["TOPSAILAI_TEAM_PATH"] = self.temp_dir
        self.env_patcher = patch.dict(os.environ, self.clean_env, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        """Clean up"""
        self.env_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_manager_and_member_names_are_different(self):
        """Test manager and member names are different by default"""
        from topsailai.ai_team.role import get_manager_name, get_member_name
        manager = get_manager_name(None)
        member = get_member_name(None)
        self.assertNotEqual(manager, member)

    def test_manager_prompt_and_member_prompt_are_different(self):
        """Test manager and member prompts are different"""
        from topsailai.ai_team.role import get_manager_prompt, get_member_prompt
        manager_prompt = get_manager_prompt("TestAgent")
        member_prompt = get_member_prompt("TestAgent")
        self.assertNotEqual(manager_prompt, member_prompt)

    def test_prompt_contains_role_type(self):
        """Test prompts contain correct role type identifiers"""
        from topsailai.ai_team.role import get_manager_prompt, get_member_prompt
        manager_result = get_manager_prompt("Test")
        member_result = get_member_prompt("Test")
        self.assertIn("Manager", manager_result)
        self.assertIn("Member", member_result)


if __name__ == '__main__':
    unittest.main()
