"""
Unit tests for ai_team module.

Test coverage:
- constants: DEFAULT_HEAD_TAIL_OFFSET
- common: get_session_id()
- role: get_manager_name, get_member_name, get_manager_prompt, get_member_prompt
- manager: get_members_cache, get_team_list, generate_team_prompt, build_manager_message
- member_agent: extend_system_prompt, get_system_prompt
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, '/root/ai/TopsailAI/src')


class TestConstants(unittest.TestCase):
    """Test cases for ai_team/constants.py"""

    def test_default_head_tail_offset_value(self):
        """Test DEFAULT_HEAD_TAIL_OFFSET has correct value"""
        from topsailai.ai_team.constants import DEFAULT_HEAD_TAIL_OFFSET
        self.assertEqual(DEFAULT_HEAD_TAIL_OFFSET, 7)


class TestCommon(unittest.TestCase):
    """Test cases for ai_team/common.py"""

    def test_get_session_id_returns_string(self):
        """Test get_session_id returns a string"""
        from topsailai.ai_team.common import get_session_id
        session_id = get_session_id()
        self.assertIsInstance(session_id, str)
        self.assertTrue(len(session_id) > 0)

    def test_get_session_id_consistent(self):
        """Test get_session_id returns consistent value within same session"""
        from topsailai.ai_team.common import get_session_id
        session_id1 = get_session_id()
        session_id2 = get_session_id()
        self.assertEqual(session_id1, session_id2)


class TestRole(unittest.TestCase):
    """Test cases for ai_team/role.py"""

    def setUp(self):
        """Set up test environment variables"""
        self.temp_dir = tempfile.mkdtemp()
        # Clear TOPSAILAI_TEAM_MANAGER_NAME to test default behavior
        clean_env = os.environ.copy()
        if "TOPSAILAI_TEAM_MANAGER_NAME" in clean_env:
            del clean_env["TOPSAILAI_TEAM_MANAGER_NAME"]
        clean_env["TOPSAILAI_TEAM_PATH"] = self.temp_dir
        self.env_patcher = patch.dict(os.environ, clean_env, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        """Clean up environment variables"""
        self.env_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_manager_name_with_none(self):
        """Test get_manager_name returns default when no env vars set"""
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name(None)
        self.assertEqual(result, "AIManager.Manager")

    def test_get_manager_name_with_explicit_name(self):
        """Test get_manager_name with explicit name"""
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name("TestManager")
        self.assertEqual(result, "AIManager.TestManager")

    def test_get_manager_name_already_prefixed(self):
        """Test get_manager_name does not double-prefix"""
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name("AIManager.Existing")
        self.assertEqual(result, "AIManager.Existing")

    def test_get_manager_name_from_env_var(self):
        """Test get_manager_name reads from environment variable"""
        with patch.dict(os.environ, {"TOPSAILAI_TEAM_MANAGER_NAME": "EnvManager"}):
            from topsailai.ai_team.role import get_manager_name
            result = get_manager_name(None)
            self.assertEqual(result, "AIManager.EnvManager")

    def test_get_member_name_with_none(self):
        """Test get_member_name returns default when no env vars set"""
        from topsailai.ai_team.role import get_member_name
        result = get_member_name(None)
        self.assertEqual(result, "AIMember.Member")

    def test_get_member_name_with_explicit_name(self):
        """Test get_member_name with explicit name"""
        from topsailai.ai_team.role import get_member_name
        result = get_member_name("TestMember")
        self.assertEqual(result, "AIMember.TestMember")

    def test_get_member_name_already_prefixed(self):
        """Test get_member_name does not double-prefix"""
        from topsailai.ai_team.role import get_member_name
        result = get_member_name("AIMember.Existing")
        self.assertEqual(result, "AIMember.Existing")

    def test_get_manager_prompt_format(self):
        """Test get_manager_prompt returns correctly formatted string"""
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt("TestManager")
        self.assertIn("YOUR ROLE IS Manager", result)
        self.assertIn("AIManager.TestManager", result)

    def test_get_manager_prompt_default(self):
        """Test get_manager_prompt uses default when no name provided"""
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt(None)
        self.assertIn("YOUR ROLE IS Manager", result)
        self.assertIn("AIManager.Manager", result)

    def test_get_member_prompt_format(self):
        """Test get_member_prompt returns correctly formatted string"""
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("TestMember")
        self.assertIn("YOUR ROLE IS Member", result)
        self.assertIn("AIMember.TestMember", result)

    def test_get_member_prompt_with_values_file(self):
        """Test get_member_prompt reads values from .values file if exists"""
        values_path = os.path.join(self.temp_dir, "TestMember.values")
        with open(values_path, 'w') as f:
            f.write("Custom values content")
        
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("TestMember")
        self.assertIn("Custom values content", result)

    def test_get_member_prompt_without_values_file(self):
        """Test get_member_prompt works without .values file"""
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("NoValuesMember")
        self.assertIn("YOUR ROLE IS Member", result)

    def test_get_member_prompt_values_file_empty(self):
        """Test get_member_prompt handles empty values file gracefully"""
        values_path = os.path.join(self.temp_dir, "EmptyMember.values")
        with open(values_path, 'w') as f:
            f.write("")
        
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("EmptyMember")
        self.assertIn("YOUR ROLE IS Member", result)
        self.assertIn("AIMember.EmptyMember", result)

    def test_get_member_prompt_values_file_permission_error(self):
        """Test get_member_prompt raises PermissionError when file cannot be read"""
        values_path = os.path.join(self.temp_dir, "PermMember.values")
        with open(values_path, 'w') as f:
            f.write("Some content")
        
        # Mock os.path.exists to return True and open to raise PermissionError
        with patch('os.path.exists', return_value=True):
            with patch('builtins.open', side_effect=PermissionError("Access denied")):
                from topsailai.ai_team.role import get_member_prompt
                # Source code does not handle PermissionError, it propagates
                with self.assertRaises(PermissionError):
                    get_member_prompt("PermMember")

    def test_get_member_prompt_values_file_unicode_content(self):
        """Test get_member_prompt handles unicode/special characters in values file"""
        values_path = os.path.join(self.temp_dir, "UnicodeMember.values")
        unicode_content = "中文内容 🚀 émojis & special <chars>"  
        with open(values_path, 'w', encoding='utf-8') as f:
            f.write(unicode_content)
        
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("UnicodeMember")
        self.assertIn(unicode_content, result)

    def test_get_manager_name_env_var_override(self):
        """Test explicit name overrides environment variable"""
        with patch.dict(os.environ, {"TOPSAILAI_TEAM_MANAGER_NAME": "EnvManager"}):
            from topsailai.ai_team.role import get_manager_name
            result = get_manager_name("ExplicitManager")
            self.assertEqual(result, "AIManager.ExplicitManager")

    def test_get_member_name_both_env_vars(self):
        """Test TOPSAILAI_TEAM_MEMBER_NAME takes precedence over TOPSAILAI_AGENT_NAME"""
        with patch.dict(os.environ, {
            "TOPSAILAI_AGENT_NAME": "AgentName",
            "TOPSAILAI_TEAM_MEMBER_NAME": "MemberName"
        }):
            from topsailai.ai_team.role import get_member_name
            result = get_member_name(None)
            self.assertEqual(result, "AIMember.MemberName")


class TestManagerFunctions(unittest.TestCase):
    """Test cases for ai_team/manager.py functions"""

    def setUp(self):
        """Set up temporary directory for team files"""
        self.temp_dir = tempfile.mkdtemp()
        self.env_patcher = patch.dict(os.environ, {
            "TOPSAILAI_TEAM_PATH": self.temp_dir
        })
        self.env_patcher.start()

    def tearDown(self):
        """Clean up temporary directory and environment"""
        self.env_patcher.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_member_file(self, name: str, content: str = "Test member info"):
        """Helper to create a member file"""
        filepath = os.path.join(self.temp_dir, f"{name}.member")
        with open(filepath, 'w') as f:
            f.write(content)
        return filepath

    def test_get_members_cache_empty_initially(self):
        """Test get_members_cache returns empty list initially"""
        from topsailai.ai_team.manager import get_members_cache
        result = get_members_cache()
        self.assertIsInstance(result, list)

    def test_get_team_list_returns_list(self):
        """Test get_team_list returns a list"""
        from topsailai.ai_team.manager import get_team_list
        result = get_team_list()
        self.assertIsInstance(result, list)

    def test_get_team_list_with_no_members(self):
        """Test get_team_list with empty directory"""
        from topsailai.ai_team.manager import get_team_list
        result = get_team_list()
        self.assertEqual(result, [])

    def test_get_team_list_with_members(self):
        """Test get_team_list correctly parses member files"""
        self._create_member_file("test-member-1", "Info for member 1")
        self._create_member_file("test-member-2", "Info for member 2")

        from topsailai.ai_team.manager import get_team_list
        result = get_team_list()

        self.assertEqual(len(result), 2)
        member_ids = [m["member_id"] for m in result]
        self.assertIn("test-member-1", member_ids)
        self.assertIn("test-member-2", member_ids)

    def test_get_team_list_member_info_parsed(self):
        """Test get_team_list correctly parses member info content"""
        test_content = "Custom member description"
        self._create_member_file("my-member", test_content)

        from topsailai.ai_team.manager import get_team_list
        result = get_team_list()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["member_info"], test_content)

    def test_get_team_list_ability_flags(self):
        """Test get_team_list sets ability flags correctly"""
        self._create_member_file("capable-member", "Info")

        from topsailai.ai_team.manager import get_team_list
        result = get_team_list()

        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["is_able_to_call_chat"])
        self.assertFalse(result[0]["is_able_to_call_agent"])

    def test_get_team_list_ability_flags_with_extensions(self):
        """Test get_team_list detects .chat and .agent extensions"""
        self._create_member_file("full-member", "Info")
        base_path = os.path.join(self.temp_dir, "full-member")
        open(f"{base_path}.chat", 'w').close()
        open(f"{base_path}.agent", 'w').close()

        from topsailai.ai_team.manager import get_team_list
        result = get_team_list()

        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["is_able_to_call_chat"])
        self.assertTrue(result[0]["is_able_to_call_agent"])

        os.remove(f"{base_path}.chat")
        os.remove(f"{base_path}.agent")

    def test_get_team_list_ignores_non_member_files(self):
        """Test get_team_list ignores non-.member files"""
        self._create_member_file("valid-member", "Info")
        with open(os.path.join(self.temp_dir, "not-a-member.txt"), 'w') as f:
            f.write("Should be ignored")

        from topsailai.ai_team.manager import get_team_list
        result = get_team_list()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["member_id"], "valid-member")

    def test_generate_team_prompt_empty_list_raises(self):
        """Test generate_team_prompt raises AssertionError for empty list"""
        from topsailai.ai_team.manager import generate_team_prompt
        with self.assertRaises(AssertionError):
            generate_team_prompt([])

    def test_generate_team_prompt_format(self):
        """Test generate_team_prompt returns correctly formatted string"""
        from topsailai.ai_team.manager import generate_team_prompt
        team_list = [
            {"member_id": "test-1", "member_info": "Info 1", "is_able_to_call_chat": True}
        ]
        result = generate_team_prompt(team_list)
        self.assertIn("yaml", result.lower())
        self.assertIn("test-1", result)

    def test_generate_team_prompt_only_agent_true(self):
        """Test generate_team_prompt removes ability flags when only_agent=True"""
        from topsailai.ai_team.manager import generate_team_prompt
        team_list = [
            {"member_id": "test-1", "member_info": "Info 1", "is_able_to_call_chat": True}
        ]
        result = generate_team_prompt(team_list, only_agent=True)
        self.assertNotIn("is_able_to_call_chat", result)

    def test_generate_team_prompt_only_agent_false(self):
        """Test generate_team_prompt keeps ability flags when only_agent=False"""
        from topsailai.ai_team.manager import generate_team_prompt
        team_list = [
            {"member_id": "test-1", "member_info": "Info 1", "is_able_to_call_chat": True}
        ]
        result = generate_team_prompt(team_list, only_agent=False)
        self.assertIn("is_able_to_call_chat", result)

    def test_build_manager_message_no_mention(self):
        """Test build_manager_message returns unchanged message when no member mentioned"""
        from topsailai.ai_team.manager import build_manager_message
        result = build_manager_message("Hello world")
        self.assertEqual(result, "Hello world")

    def test_build_manager_message_with_mention(self):
        """Test build_manager_message appends instruction when member mentioned"""
        from topsailai.ai_team.manager import build_manager_message, g_members
        g_members.clear()
        g_members.append("TestMember")

        result = build_manager_message("Hello @TestMember")
        self.assertIn("Manager to use tool call", result)

    def test_build_manager_message_with_partial_match(self):
        """Test build_manager_message matches member name without @ prefix"""
        from topsailai.ai_team.manager import build_manager_message, g_members
        g_members.clear()
        g_members.append("SpecialAgent")

        result = build_manager_message("Ask SpecialAgent to help")
        self.assertIn("Manager to use tool call", result)

    def test_build_manager_message_empty_member_name(self):
        """Test build_manager_message skips empty member names"""
        from topsailai.ai_team.manager import build_manager_message, g_members
        g_members.clear()
        g_members.append("")

        result = build_manager_message("Hello world")
        self.assertEqual(result, "Hello world")

    def test_build_manager_message_whitespace_member_name(self):
        """Test build_manager_message skips whitespace-only member names"""
        from topsailai.ai_team.manager import build_manager_message, g_members
        g_members.clear()
        g_members.append("   ")

        result = build_manager_message("Hello world")
        self.assertEqual(result, "Hello world")


class TestMemberAgentFunctions(unittest.TestCase):
    """Test cases for ai_team/member_agent.py functions"""

    def setUp(self):
        """Set up test environment"""
        self.env_patcher = patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        """Clean up environment"""
        self.env_patcher.stop()

    def test_extend_system_prompt_sets_env_var(self):
        """Test extend_system_prompt sets SYSTEM_PROMPT_EXTRA_FILES"""
        from topsailai.ai_team.member_agent import extend_system_prompt
        extend_system_prompt()
        result = os.getenv("SYSTEM_PROMPT_EXTRA_FILES")
        self.assertEqual(result, "work_mode/sop/work_agreement.md")

    def test_extend_system_prompt_does_not_override(self):
        """Test extend_system_prompt does not override existing value"""
        with patch.dict(os.environ, {"SYSTEM_PROMPT_EXTRA_FILES": "custom/path.md"}):
            from topsailai.ai_team.member_agent import extend_system_prompt
            extend_system_prompt()
            result = os.getenv("SYSTEM_PROMPT_EXTRA_FILES")
            self.assertEqual(result, "custom/path.md")

    def test_extend_system_prompt_returns_none(self):
        """Test extend_system_prompt returns None"""
        from topsailai.ai_team.member_agent import extend_system_prompt
        result = extend_system_prompt()
        self.assertIsNone(result)

    @patch('topsailai.ai_team.member_agent.file_tool')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    def test_get_system_prompt_returns_string(self, mock_get_member_prompt, mock_file_tool):
        """Test get_system_prompt returns a string"""
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "Base prompt content")
        mock_get_member_prompt.return_value = "\n---\nYOUR ROLE IS Member\n---\n"

        from topsailai.ai_team.member_agent import get_system_prompt
        result = get_system_prompt("TestAgent")
        self.assertIsInstance(result, str)

    @patch('topsailai.ai_team.member_agent.file_tool')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    def test_get_system_prompt_includes_base_prompt(self, mock_get_member_prompt, mock_file_tool):
        """Test get_system_prompt includes base system prompt"""
        base_content = "Base system prompt"
        mock_file_tool.get_file_content_fuzzy.return_value = (None, base_content)
        mock_get_member_prompt.return_value = "\n---\nYOUR ROLE IS Member\n---\n"

        from topsailai.ai_team.member_agent import get_system_prompt
        result = get_system_prompt("TestAgent")
        self.assertIn(base_content, result)

    @patch('topsailai.ai_team.member_agent.file_tool')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    def test_get_system_prompt_includes_member_prompt(self, mock_get_member_prompt, mock_file_tool):
        """Test get_system_prompt includes member prompt"""
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "Base")
        member_prompt = "\n---\nYOUR ROLE IS Member\n---\n"
        mock_get_member_prompt.return_value = member_prompt

        from topsailai.ai_team.member_agent import get_system_prompt
        result = get_system_prompt("TestAgent")
        self.assertIn(member_prompt, result)

    @patch('topsailai.ai_team.member_agent.file_tool')
    @patch('topsailai.ai_team.member_agent.get_member_prompt')
    def test_get_system_prompt_calls_extend_system_prompt(self, mock_get_member_prompt, mock_file_tool):
        """Test get_system_prompt calls extend_system_prompt"""
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "Base")
        mock_get_member_prompt.return_value = "\n---\nYOUR ROLE IS Member\n---\n"

        from topsailai.ai_team.member_agent import get_system_prompt
        with patch('topsailai.ai_team.member_agent.extend_system_prompt') as mock_extend:
            get_system_prompt("TestAgent")
            mock_extend.assert_called_once()


class TestRoleConstants(unittest.TestCase):
    """Test cases for role module constants"""

    def test_manager_startswith_constant(self):
        """Test MANAGER_STARTSWITH constant value"""
        from topsailai.ai_team.role import MANAGER_STARTSWITH
        self.assertEqual(MANAGER_STARTSWITH, "AIManager.")

    def test_member_startswith_constant(self):
        """Test MEMBER_STARTSWITH constant value"""
        from topsailai.ai_team.role import MEMBER_STARTSWITH
        self.assertEqual(MEMBER_STARTSWITH, "AIMember.")


if __name__ == '__main__':
    unittest.main()
