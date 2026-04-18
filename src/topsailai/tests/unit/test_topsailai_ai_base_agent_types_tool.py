import pytest

from topsailai.ai_base.agent_types.tool import get_tool_func


def test_get_tool_func_exact_match():
    """Test get_tool_func with exact name matches."""
    def mock_tool_1():
        return "tool_1_result"

    def mock_tool_2():
        return "tool_2_result"

    tool_map = {
        "tool.one": mock_tool_1,
        "tool-two": mock_tool_2,
        "tool_three": lambda: "tool_3_result"
    }

    # Test exact match
    result = get_tool_func(tool_map, "tool.one")
    assert result == mock_tool_1
    assert result() == "tool_1_result"

    result = get_tool_func(tool_map, "tool-two")
    assert result == mock_tool_2
    assert result() == "tool_2_result"


def test_get_tool_func_dot_to_dash_replacement():
    """Test get_tool_func with dot-to-dash replacement."""
    def mock_tool():
        return "mock_result"

    tool_map = {
        "api.get.user": mock_tool,
        "database.query": lambda: "db_result"
    }

    # Test replacing dots with dashes in search
    result = get_tool_func(tool_map, "api-get-user")
    assert result == mock_tool
    assert result() == "mock_result"

    # Test the reverse - searching with dots when tool has dashes
    tool_map_dash = {
        "api-get-user": mock_tool,
        "database-query": lambda: "db_result"
    }

    result = get_tool_func(tool_map_dash, "api.get.user")
    assert result == mock_tool
    assert result() == "mock_result"


def test_get_tool_func_edge_cases():
    """Test get_tool_func with edge cases and invalid inputs."""
    def mock_tool():
        return "result"

    tool_map = {"valid.tool": mock_tool}

    # Test empty tool_map
    assert get_tool_func({}, "any.tool") is None

    # Test None tool_map
    assert get_tool_func(None, "any.tool") is None

    # Test empty tool_name
    assert get_tool_func(tool_map, "") is None
    assert get_tool_func(tool_map, "   ") is None

    # Test None tool_name
    assert get_tool_func(tool_map, None) is None

    # Test tool not found
    assert get_tool_func(tool_map, "nonexistent.tool") is None
    assert get_tool_func(tool_map, "nonexistent-tool") is None


def test_get_tool_func_multiple_matches():
    """Test get_tool_func behavior with multiple potential matches."""
    def tool_a():
        return "a"

    def tool_b():
        return "b"

    # Test that exact match takes precedence over pattern match
    tool_map = {
        "tool.a": tool_a,
        "tool-a": tool_b
    }

    # Should return exact match for "tool.a"
    result = get_tool_func(tool_map, "tool.a")
    assert result == tool_a

    # Should return exact match for "tool-a"
    result = get_tool_func(tool_map, "tool-a")
    assert result == tool_b

    # Should return tool_a when searching "tool-a" if only "tool.a" exists
    tool_map_single = {"tool.a": tool_a}
    result = get_tool_func(tool_map_single, "tool-a")
    assert result == tool_a


def test_get_tool_func_with_whitespace():
    """Test get_tool_func handles whitespace in tool names."""
    def mock_tool():
        return "result"

    tool_map = {"  tool.name  ": mock_tool}

    # Test with whitespace in tool_map key
    result = get_tool_func(tool_map, "tool.name")
    assert result == mock_tool

    # Test with whitespace in search term
    result = get_tool_func(tool_map, "  tool.name  ")
    assert result == mock_tool


def test_get_tool_func_complex_patterns():
    """Test get_tool_func with complex naming patterns."""
    def api_tool():
        return "api"

    def db_tool():
        return "db"

    tool_map = {
        "api.v1.users.get": api_tool,
        "database.queries.select": db_tool,
        "external-service-call": lambda: "external"
    }

    # Test multiple dot replacement
    result = get_tool_func(tool_map, "api-v1-users-get")
    assert result == api_tool

    result = get_tool_func(tool_map, "database-queries-select")
    assert result == db_tool

    # Test dash to dot (reverse)
    result = get_tool_func(tool_map, "external.service.call")
    assert result() == "external"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
