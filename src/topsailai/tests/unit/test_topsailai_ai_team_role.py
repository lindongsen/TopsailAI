"""
Unit tests for ai_team role module.

This module tests the role-related functions for AI team members and managers,
including name generation, prefix handling, and prompt generation.

Test Coverage:
- Constants: MANAGER_STARTSWITH, MEMBER_STARTSWITH
- Functions: get_manager_name, get_member_name, get_manager_prompt, get_member_prompt
"""

import pytest
from unittest.mock import patch, mock_open, MagicMock


class TestConstants:
    """Test cases for module-level constants."""

    def test_manager_startwith_value(self):
        """Verify MANAGER_STARTSWITH has correct value."""
        from topsailai.ai_team.role import MANAGER_STARTSWITH
        assert MANAGER_STARTSWITH == "AIManager."

    def test_member_startwith_value(self):
        """Verify MEMBER_STARTSWITH has correct value."""
        from topsailai.ai_team.role import MEMBER_STARTSWITH
        assert MEMBER_STARTSWITH == "AIMember."


class TestGetManagerName:
    """Test cases for get_manager_name function."""

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_default_name_without_env(self, mock_env_instance):
        """Test default manager name when no env var is set and no param provided."""
        # Arrange: No env vars set
        mock_env_instance.get.return_value = None

        # Act
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name()

        # Assert
        assert result == "AIManager.Manager"

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_custom_name_without_prefix(self, mock_env_instance):
        """Test custom name without prefix gets AIManager. prefix added."""
        # Arrange
        mock_env_instance.get.return_value = None

        # Act
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name("CustomMgr")

        # Assert
        assert result == "AIManager.CustomMgr"

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_custom_name_with_prefix(self, mock_env_instance):
        """Test custom name with prefix is kept as-is."""
        # Arrange
        mock_env_instance.get.return_value = None

        # Act
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name("AIManager.AlreadyPrefixed")

        # Assert
        assert result == "AIManager.AlreadyPrefixed"

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_name_from_env_team_manager_name(self, mock_env_instance):
        """Test name is read from TOPSAILAI_TEAM_MANAGER_NAME env var."""
        # Arrange
        mock_env_instance.get.side_effect = lambda key: "EnvMgr" if key == "TOPSAILAI_TEAM_MANAGER_NAME" else None

        # Act
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name()

        # Assert
        assert result == "AIManager.EnvMgr"

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_name_from_env_agent_name_fallback(self, mock_env_instance):
        """Test fallback to TOPSAILAI_AGENT_NAME when TEAM_MANAGER_NAME is not set."""
        # Arrange: First call returns None (TOPSAILAI_TEAM_MANAGER_NAME), second returns value (TOPSAILAI_AGENT_NAME)
        mock_env_instance.get.side_effect = lambda key: None if key == "TOPSAILAI_TEAM_MANAGER_NAME" else "AgentName"

        # Act
        from topsailai.ai_team.role import get_manager_name
        result = get_manager_name()

        # Assert
        assert result == "AIManager.AgentName"


class TestGetMemberName:
    """Test cases for get_member_name function."""

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_default_name_without_env(self, mock_env_instance):
        """Test default member name when no env var is set and no param provided."""
        # Arrange: No env vars set
        mock_env_instance.get.return_value = None

        # Act
        from topsailai.ai_team.role import get_member_name
        result = get_member_name()

        # Assert
        assert result == "AIMember.Member"

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_custom_name_without_prefix(self, mock_env_instance):
        """Test custom name without prefix gets AIMember. prefix added."""
        # Arrange
        mock_env_instance.get.return_value = None

        # Act
        from topsailai.ai_team.role import get_member_name
        result = get_member_name("CustomMem")

        # Assert
        assert result == "AIMember.CustomMem"

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_custom_name_with_prefix(self, mock_env_instance):
        """Test custom name with prefix is kept as-is."""
        # Arrange
        mock_env_instance.get.return_value = None

        # Act
        from topsailai.ai_team.role import get_member_name
        result = get_member_name("AIMember.AlreadyPrefixed")

        # Assert
        assert result == "AIMember.AlreadyPrefixed"

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_name_from_env_team_member_name(self, mock_env_instance):
        """Test name is read from TOPSAILAI_TEAM_MEMBER_NAME env var."""
        # Arrange
        mock_env_instance.get.side_effect = lambda key: "EnvMem" if key == "TOPSAILAI_TEAM_MEMBER_NAME" else None

        # Act
        from topsailai.ai_team.role import get_member_name
        result = get_member_name()

        # Assert
        assert result == "AIMember.EnvMem"

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_name_from_env_agent_name_fallback(self, mock_env_instance):
        """Test fallback to TOPSAILAI_AGENT_NAME when TEAM_MEMBER_NAME is not set."""
        # Arrange: First call returns None (TOPSAILAI_TEAM_MEMBER_NAME), second returns value (TOPSAILAI_AGENT_NAME)
        mock_env_instance.get.side_effect = lambda key: None if key == "TOPSAILAI_TEAM_MEMBER_NAME" else "AgentName"

        # Act
        from topsailai.ai_team.role import get_member_name
        result = get_member_name()

        # Assert
        assert result == "AIMember.AgentName"


class TestGetManagerPrompt:
    """Test cases for get_manager_prompt function."""

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_default_prompt_content(self, mock_env_instance):
        """Test default manager prompt contains expected content."""
        # Arrange: No env vars set
        mock_env_instance.get.return_value = None

        # Act
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt()

        # Assert
        assert "YOUR ROLE IS Manager" in result
        assert "AIManager.Manager" in result

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_custom_agent_name_in_prompt(self, mock_env_instance):
        """Test manager prompt with custom agent name."""
        # Arrange
        mock_env_instance.get.return_value = None

        # Act
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt("CustomMgr")

        # Assert
        assert "YOUR ROLE IS Manager" in result
        assert "AIManager.CustomMgr" in result

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    def test_prompt_format_with_separators(self, mock_env_instance):
        """Test manager prompt has proper formatting with separators."""
        # Arrange
        mock_env_instance.get.return_value = None

        # Act
        from topsailai.ai_team.role import get_manager_prompt
        result = get_manager_prompt()

        # Assert: Check for separator lines
        assert result.startswith("\n")
        assert "---" in result


class TestGetMemberPrompt:
    """Test cases for get_member_prompt function."""

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    @patch('topsailai.ai_team.role.os.path.exists')
    def test_default_prompt_without_values_file(self, mock_path_exists, mock_env_instance):
        """Test member prompt without values file returns basic prompt."""
        # Arrange: TOPSAILAI_TEAM_PATH set, values file does not exist
        def env_get_side_effect(key):
            if key == "TOPSAILAI_TEAM_PATH":
                return "/team/path"
            return None
        mock_env_instance.get.side_effect = env_get_side_effect
        mock_path_exists.return_value = False

        # Act
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt()

        # Assert
        assert "YOUR ROLE IS Member" in result
        assert "AIMember.Member" in result
        assert result.endswith("---\n")

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    @patch('topsailai.ai_team.role.os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="values content here")
    def test_prompt_with_values_file_content(self, mock_file, mock_path_exists, mock_env_instance):
        """Test member prompt includes values file content when file exists."""
        # Arrange: Values file exists with content
        mock_env_instance.get.side_effect = lambda key: "/team/path" if key == "TOPSAILAI_TEAM_PATH" else None
        mock_path_exists.return_value = True

        # Act
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("mm-m25")

        # Assert
        assert "YOUR ROLE IS Member" in result
        assert "AIMember.mm-m25" in result
        assert "values content here" in result
        assert result.endswith("---\n")

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    @patch('topsailai.ai_team.role.os.path.exists')
    def test_values_file_path_construction(self, mock_path_exists, mock_env_instance):
        """Test values file path is correctly constructed from env var."""
        # Arrange
        mock_env_instance.get.side_effect = lambda key: "/custom/team/path" if key == "TOPSAILAI_TEAM_PATH" else None
        mock_path_exists.return_value = False

        # Act
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("test-member")

        # Assert: Verify path.exists was called with correct path
        mock_path_exists.assert_called_once()
        called_path = mock_path_exists.call_args[0][0]
        assert called_path == "/custom/team/path/test-member.values"

    @patch('topsailai.ai_team.role.env_tool.EnvReaderInstance')
    @patch('topsailai.ai_team.role.os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="member values data")
    def test_prompt_with_prefixed_name(self, mock_file, mock_path_exists, mock_env_instance):
        """Test values file lookup uses name without prefix."""
        # Arrange: Name already has prefix
        mock_env_instance.get.side_effect = lambda key: "/team/path" if key == "TOPSAILAI_TEAM_PATH" else None
        mock_path_exists.return_value = True

        # Act
        from topsailai.ai_team.role import get_member_prompt
        result = get_member_prompt("AIMember.mm-m25")

        # Assert: Path should use name without prefix
        mock_path_exists.assert_called_once()
        called_path = mock_path_exists.call_args[0][0]
        assert called_path == "/team/path/mm-m25.values"
