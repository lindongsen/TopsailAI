"""
Unit tests for ai_team/manager.py

Author: DawsonLin
Test Developer: AIMember.mm-m25
"""

import unittest
from unittest.mock import patch, MagicMock, mock_open


class TestGetMembersCache(unittest.TestCase):
    """Tests for get_members_cache() function."""

    def setUp(self):
        """Reset global state before each test."""
        # Import and reset global
        from topsailai.ai_team import manager
        manager.g_members = []

    def tearDown(self):
        """Clean up after each test."""
        from topsailai.ai_team import manager
        manager.g_members = []

    def test_get_members_cache_returns_list(self):
        """Test that get_members_cache returns a list type."""
        from topsailai.ai_team.manager import get_members_cache
        result = get_members_cache()
        self.assertIsInstance(result, list)

    def test_get_members_cache_returns_global_members(self):
        """Test that get_members_cache returns the global g_members list."""
        from topsailai.ai_team.manager import get_members_cache, g_members
        # Add some test data
        g_members.extend(["member1", "member2"])
        result = get_members_cache()
        self.assertEqual(result, ["member1", "member2"])


class TestGetTeamList(unittest.TestCase):
    """Tests for get_team_list() function."""

    def setUp(self):
        """Reset global state before each test."""
        from topsailai.ai_team import manager
        manager.g_members = []

    def tearDown(self):
        """Clean up after each test."""
        from topsailai.ai_team import manager
        manager.g_members = []

    @patch('topsailai.ai_team.manager.os.getenv')
    @patch('topsailai.ai_team.manager.os.listdir')
    @patch('topsailai.ai_team.manager.os.path.isdir')
    @patch('topsailai.ai_team.manager.os.path.join')
    @patch('topsailai.ai_team.manager.os.path.exists')
    @patch('topsailai.ai_team.manager.open', new_callable=mock_open, read_data="Test member info")
    def test_get_team_list_reads_from_team_path(self, mock_open, mock_exists, mock_join, mock_isdir, mock_listdir, mock_getenv):
        """Test that get_team_list reads .member files from team path directory."""
        from topsailai.ai_team.manager import get_team_list
        
        mock_getenv.return_value = "/path/to/team"
        mock_isdir.return_value = True
        mock_listdir.return_value = ["test_member.member"]
        mock_join.return_value = "/path/to/team/test_member.member"
        mock_exists.return_value = False
        
        result = get_team_list()
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["member_id"], "test_member")
        self.assertEqual(result[0]["member_info"], "Test member info")

    @patch('topsailai.ai_team.manager.os.getenv')
    @patch('topsailai.ai_team.manager.os.listdir')
    @patch('topsailai.ai_team.manager.os.path.isdir')
    @patch('topsailai.ai_team.manager.os.path.join')
    @patch('topsailai.ai_team.manager.os.path.exists')
    @patch('topsailai.ai_team.manager.open', new_callable=mock_open, read_data="Member content here")
    def test_get_team_list_parses_member_info(self, mock_open, mock_exists, mock_join, mock_isdir, mock_listdir, mock_getenv):
        """Test that get_team_list correctly parses member_id and member_info."""
        from topsailai.ai_team.manager import get_team_list
        
        mock_getenv.return_value = "/path/to/team"
        mock_isdir.return_value = True
        mock_listdir.return_value = ["my_member.member"]
        mock_join.return_value = "/path/to/team/my_member.member"
        mock_exists.return_value = False
        
        result = get_team_list()
        
        self.assertEqual(result[0]["member_id"], "my_member")
        self.assertEqual(result[0]["member_info"], "Member content here")

    @patch('topsailai.ai_team.manager.os.getenv')
    @patch('topsailai.ai_team.manager.os.listdir')
    @patch('topsailai.ai_team.manager.os.path.isdir')
    @patch('topsailai.ai_team.manager.os.path.join')
    @patch('topsailai.ai_team.manager.os.path.exists')
    @patch('topsailai.ai_team.manager.os.system')
    @patch('topsailai.ai_team.manager.open', new_callable=mock_open, read_data="Chat member")
    def test_get_team_list_detects_chat_ability(self, mock_open, mock_system, mock_exists, mock_join, mock_isdir, mock_listdir, mock_getenv):
        """Test that get_team_list detects .chat file existence."""
        from topsailai.ai_team.manager import get_team_list
        
        mock_getenv.return_value = "/path/to/team"
        mock_isdir.return_value = True
        mock_listdir.return_value = ["chat_member.member"]
        mock_join.return_value = "/path/to/team/chat_member.member"
        # Return True for .chat file existence
        mock_exists.side_effect = lambda path: ".chat" in path
        
        result = get_team_list()
        
        self.assertTrue(result[0]["is_able_to_call_chat"])
        self.assertFalse(result[0]["is_able_to_call_agent"])

    @patch('topsailai.ai_team.manager.os.getenv')
    @patch('topsailai.ai_team.manager.os.listdir')
    @patch('topsailai.ai_team.manager.os.path.isdir')
    @patch('topsailai.ai_team.manager.os.path.join')
    @patch('topsailai.ai_team.manager.os.path.exists')
    @patch('topsailai.ai_team.manager.os.system')
    @patch('topsailai.ai_team.manager.open', new_callable=mock_open, read_data="Agent member")
    def test_get_team_list_detects_agent_ability(self, mock_open, mock_system, mock_exists, mock_join, mock_isdir, mock_listdir, mock_getenv):
        """Test that get_team_list detects .agent file existence."""
        from topsailai.ai_team.manager import get_team_list
        
        mock_getenv.return_value = "/path/to/team"
        mock_isdir.return_value = True
        mock_listdir.return_value = ["agent_member.member"]
        mock_join.return_value = "/path/to/team/agent_member.member"
        # Return True for .agent file existence
        mock_exists.side_effect = lambda path: ".agent" in path
        
        result = get_team_list()
        
        self.assertFalse(result[0]["is_able_to_call_chat"])
        self.assertTrue(result[0]["is_able_to_call_agent"])

    @patch('topsailai.ai_team.manager.os.getenv')
    @patch('topsailai.ai_team.manager.os.path.isdir')
    def test_get_team_list_asserts_invalid_path(self, mock_isdir, mock_getenv):
        """Test that get_team_list raises AssertionError for invalid path."""
        from topsailai.ai_team.manager import get_team_list
        
        mock_getenv.return_value = None
        mock_isdir.return_value = False
        
        with self.assertRaises(AssertionError):
            get_team_list()


class TestGenerateTeamPrompt(unittest.TestCase):
    """Tests for generate_team_prompt() function."""

    def test_generate_team_prompt_returns_string(self):
        """Test that generate_team_prompt returns a string type."""
        from topsailai.ai_team.manager import generate_team_prompt
        
        team_list = [{"member_id": "test", "member_info": "info"}]
        result = generate_team_prompt(team_list)
        
        self.assertIsInstance(result, str)

    def test_generate_team_prompt_contains_yaml(self):
        """Test that generate_team_prompt contains YAML-formatted content."""
        from topsailai.ai_team.manager import generate_team_prompt
        
        team_list = [{"member_id": "test", "member_info": "info"}]
        result = generate_team_prompt(team_list)
        
        self.assertIn("yaml", result.lower())
        self.assertIn("test", result)

    def test_generate_team_prompt_removes_ability_flags_when_only_agent(self):
        """Test that is_able_to_call_* flags are removed when only_agent=True."""
        from topsailai.ai_team.manager import generate_team_prompt
        
        team_list = [
            {
                "member_id": "test",
                "member_info": "info",
                "is_able_to_call_chat": True,
                "is_able_to_call_agent": True
            }
        ]
        result = generate_team_prompt(team_list, only_agent=True)
        
        self.assertNotIn("is_able_to_call_chat", result)
        self.assertNotIn("is_able_to_call_agent", result)

    def test_generate_team_prompt_keeps_ability_flags_when_only_agent_false(self):
        """Test that is_able_to_call_* flags are kept when only_agent=False."""
        from topsailai.ai_team.manager import generate_team_prompt
        
        team_list = [
            {
                "member_id": "test",
                "member_info": "info",
                "is_able_to_call_chat": True,
                "is_able_to_call_agent": True
            }
        ]
        result = generate_team_prompt(team_list, only_agent=False)
        
        self.assertIn("is_able_to_call_chat", result)
        self.assertIn("is_able_to_call_agent", result)

    def test_generate_team_prompt_asserts_empty_list(self):
        """Test that generate_team_prompt raises AssertionError for empty team_list."""
        from topsailai.ai_team.manager import generate_team_prompt
        
        with self.assertRaises(AssertionError):
            generate_team_prompt([])


class TestBuildManagerMessage(unittest.TestCase):
    """Tests for build_manager_message() function."""

    def setUp(self):
        """Set up test fixtures."""
        from topsailai.ai_team import manager
        manager.g_members = []

    def tearDown(self):
        """Clean up after each test."""
        from topsailai.ai_team import manager
        manager.g_members = []

    def test_build_manager_message_returns_string(self):
        """Test that build_manager_message returns a string type."""
        from topsailai.ai_team.manager import build_manager_message
        
        result = build_manager_message("test message")
        
        self.assertIsInstance(result, str)

    def test_build_manager_message_appends_note_when_member_mentioned(self):
        """Test that 'Manager to use tool call' is appended when member is mentioned."""
        from topsailai.ai_team.manager import build_manager_message, g_members
        
        g_members.append("test_member")
        message = "Hello @test_member, please help"
        result = build_manager_message(message)
        
        self.assertIn("Manager to use tool call", result)

    def test_build_manager_message_no_change_when_no_mention(self):
        """Test that original message is returned when no member is mentioned."""
        from topsailai.ai_team.manager import build_manager_message, g_members
        
        g_members.append("test_member")
        message = "Hello world, no mention here"
        result = build_manager_message(message)
        
        self.assertEqual(result, message)

    def test_build_manager_message_handles_member_name_in_message(self):
        """Test that member name without @ symbol is detected."""
        from topsailai.ai_team.manager import build_manager_message, g_members
        
        g_members.append("john")
        message = "Hi john, can you help?"
        result = build_manager_message(message)
        
        self.assertIn("Manager to use tool call", result)


class TestGenerateSystemPrompt(unittest.TestCase):
    """Tests for generate_system_prompt() function."""

    def setUp(self):
        """Reset global state before each test."""
        from topsailai.ai_team import manager
        manager.g_members = []

    def tearDown(self):
        """Clean up after each test."""
        from topsailai.ai_team import manager
        manager.g_members = []
        # Clean up environment variable
        import os
        if "TOPSAILAI_TEAM_PROMPT" in os.environ:
            del os.environ["TOPSAILAI_TEAM_PROMPT"]
        if "TOPSAILAI_TEAM_PROMPT_CONTENT" in os.environ:
            del os.environ["TOPSAILAI_TEAM_PROMPT_CONTENT"]

    @patch('topsailai.ai_team.manager.get_team_list')
    @patch('topsailai.ai_team.manager.generate_team_prompt')
    @patch('topsailai.ai_team.manager.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.manager.prompt_tool.read_prompt')
    @patch('topsailai.ai_team.manager.get_manager_prompt')
    def test_generate_system_prompt_returns_string(self, mock_get_manager, mock_read_prompt, mock_get_file, mock_gen_prompt, mock_get_list):
        """Test that generate_system_prompt returns a string type."""
        from topsailai.ai_team.manager import generate_system_prompt
        
        mock_get_list.return_value = []
        mock_gen_prompt.return_value = "## Team Detail\n```yaml\n[]\n```"
        mock_get_file.return_value = (None, "content")
        mock_read_prompt.return_value = "collaboration prompt"
        mock_get_manager.return_value = "manager prompt"
        
        result = generate_system_prompt()
        
        self.assertIsInstance(result, str)

    @patch('topsailai.ai_team.manager.get_team_list')
    @patch('topsailai.ai_team.manager.generate_team_prompt')
    @patch('topsailai.ai_team.manager.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.manager.prompt_tool.read_prompt')
    @patch('topsailai.ai_team.manager.get_manager_prompt')
    def test_generate_system_prompt_contains_team_info(self, mock_get_manager, mock_read_prompt, mock_get_file, mock_gen_prompt, mock_get_list):
        """Test that generate_system_prompt contains team information."""
        from topsailai.ai_team.manager import generate_system_prompt
        
        mock_get_list.return_value = [{"member_id": "test", "member_info": "info"}]
        mock_gen_prompt.return_value = "## Team Detail\n```yaml\ntest\n```"
        mock_get_file.return_value = (None, "")
        mock_read_prompt.return_value = ""
        mock_get_manager.return_value = ""
        
        result = generate_system_prompt()
        
        self.assertIn("Team Detail", result)

    @patch('topsailai.ai_team.manager.get_team_list')
    @patch('topsailai.ai_team.manager.generate_team_prompt')
    @patch('topsailai.ai_team.manager.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.manager.prompt_tool.read_prompt')
    @patch('topsailai.ai_team.manager.get_manager_prompt')
    def test_generate_system_prompt_sets_env_var(self, mock_get_manager, mock_read_prompt, mock_get_file, mock_gen_prompt, mock_get_list):
        """Test that generate_system_prompt sets TOPSAILAI_TEAM_PROMPT_CONTENT env var."""
        import os
        from topsailai.ai_team.manager import generate_system_prompt
        
        mock_get_list.return_value = []
        mock_gen_prompt.return_value = "## Team Detail\n```yaml\n[]\n```"
        mock_get_file.return_value = (None, "")
        mock_read_prompt.return_value = ""
        mock_get_manager.return_value = ""
        
        generate_system_prompt()
        
        self.assertIn("TOPSAILAI_TEAM_PROMPT_CONTENT", os.environ)

    @patch('topsailai.ai_team.manager.get_team_list')
    @patch('topsailai.ai_team.manager.generate_team_prompt')
    @patch('topsailai.ai_team.manager.file_tool.get_file_content_fuzzy')
    @patch('topsailai.ai_team.manager.prompt_tool.read_prompt')
    @patch('topsailai.ai_team.manager.get_manager_prompt')
    def test_generate_system_prompt_combines_multiple_sources(self, mock_get_manager, mock_read_prompt, mock_get_file, mock_gen_prompt, mock_get_list):
        """Test that generate_system_prompt combines system, team, and manager prompts."""
        from topsailai.ai_team.manager import generate_system_prompt
        
        mock_get_list.return_value = []
        mock_gen_prompt.return_value = "## Team Detail"
        mock_get_file.return_value = (None, "system content")
        mock_read_prompt.return_value = "collaboration"
        mock_get_manager.return_value = "manager prompt"
        
        result = generate_system_prompt()
        
        # Should contain content from multiple sources
        self.assertIn("system content", result)
        self.assertIn("Team Detail", result)


if __name__ == '__main__':
    unittest.main()
