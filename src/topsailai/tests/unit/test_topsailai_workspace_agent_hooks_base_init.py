"""
Unit tests for workspace/agent/hooks/base/init.py module.

Test coverage for:
- HOOKS dictionary (populated by get_function_map)
- get_hooks() function

Author: km3-programmer
"""

import pytest
from unittest.mock import patch, MagicMock


class TestGetHooks:
    """Tests for get_hooks() function."""

    def test_get_hooks_with_matching_prefix(self):
        """Test get_hooks returns hooks with matching prefix."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        # Mock HOOKS with known data
        mock_hooks = {
            "prefix_a.func1": MagicMock(),
            "prefix_a.func2": MagicMock(),
            "prefix_b.func1": MagicMock(),
            "other.func1": MagicMock(),
        }

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", mock_hooks):
            result = get_hooks("prefix_a")
            assert len(result) == 2
            assert mock_hooks["prefix_a.func1"] in result
            assert mock_hooks["prefix_a.func2"] in result

    def test_get_hooks_with_no_matching_prefix(self):
        """Test get_hooks returns empty list when no hooks match."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        mock_hooks = {
            "prefix_a.func1": MagicMock(),
            "prefix_b.func1": MagicMock(),
        }

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", mock_hooks):
            result = get_hooks("nonexistent")
            assert result == []
            assert isinstance(result, list)

    def test_get_hooks_with_empty_prefix(self):
        """Test get_hooks with empty prefix returns all hooks."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        mock_hooks = {
            "prefix_a.func1": MagicMock(),
            "prefix_b.func1": MagicMock(),
            "other.func1": MagicMock(),
        }

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", mock_hooks):
            result = get_hooks("")
            assert len(result) == 3

    def test_get_hooks_exact_match_prefix(self):
        """Test get_hooks with exact prefix match."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        mock_func = MagicMock()
        mock_hooks = {
            "exact": mock_func,
            "exact_extra": MagicMock(),
        }

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", mock_hooks):
            result = get_hooks("exact")
            assert len(result) == 2
            assert mock_func in result

    def test_get_hooks_returns_list(self):
        """Test get_hooks always returns a list."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", {}):
            result = get_hooks("any")
            assert isinstance(result, list)

    def test_get_hooks_sorted_order(self):
        """Test get_hooks returns hooks in lexicographical order."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        mock_hooks = {
            "z.func": MagicMock(),
            "a.func": MagicMock(),
            "m.func": MagicMock(),
        }

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", mock_hooks):
            result = get_hooks("")
            # Hooks must be returned in strict lexicographical order.
            assert result[0] == mock_hooks["a.func"]
            assert result[1] == mock_hooks["m.func"]
            assert result[2] == mock_hooks["z.func"]
    def test_get_hooks_with_single_match(self):
        """Test get_hooks returns single item list for one match."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        mock_func = MagicMock()
        mock_hooks = {
            "unique.prefix.func": mock_func,
            "other.prefix.func": MagicMock(),
        }

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", mock_hooks):
            result = get_hooks("unique")
            assert len(result) == 1
            assert result[0] == mock_func

    def test_get_hooks_does_not_modify_hooks(self):
        """Test get_hooks does not modify the HOOKS dictionary."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        mock_hooks = {
            "prefix.func": MagicMock(),
        }
        original_keys = list(mock_hooks.keys())

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", mock_hooks):
            get_hooks("prefix")
            assert list(mock_hooks.keys()) == original_keys

    def test_get_hooks_with_special_characters_in_prefix(self):
        """Test get_hooks handles special characters in prefix."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        mock_func = MagicMock()
        mock_hooks = {
            "prefix_123.func": mock_func,
            "prefix_456.func": MagicMock(),
        }

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", mock_hooks):
            result = get_hooks("prefix_123")
            assert len(result) == 1
            assert result[0] == mock_func

    def test_get_hooks_case_sensitive(self):
        """Test get_hooks is case sensitive."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        mock_hooks = {
            "Prefix.func": MagicMock(),
            "prefix.func": MagicMock(),
        }

        with patch("topsailai.workspace.agent.hooks.base.init.HOOKS", mock_hooks):
            result_lower = get_hooks("prefix")
            result_upper = get_hooks("Prefix")
            assert len(result_lower) == 1
            assert len(result_upper) == 1


class TestHooksConstant:
    """Tests for HOOKS constant."""

    def test_hooks_is_dict(self):
        """Test HOOKS is a dictionary."""
        from topsailai.workspace.agent.hooks.base.init import HOOKS

        assert isinstance(HOOKS, dict)

    def test_hooks_values_are_callable(self):
        """Test all values in HOOKS are callable functions."""
        from topsailai.workspace.agent.hooks.base.init import HOOKS

        for key, func in HOOKS.items():
            assert callable(func), f"HOOKS['{key}'] is not callable"

    def test_hooks_keys_are_strings(self):
        """Test all keys in HOOKS are strings."""
        from topsailai.workspace.agent.hooks.base.init import HOOKS

        for key in HOOKS.keys():
            assert isinstance(key, str), f"HOOKS key '{key}' is not a string"

    def test_hooks_contains_post_final_answer(self):
        """Test HOOKS contains post_final_answer hooks."""
        from topsailai.workspace.agent.hooks.base.init import HOOKS

        # The post_final_answer module should be discovered
        matching_keys = [k for k in HOOKS.keys() if k.startswith("post_final_answer")]
        assert len(matching_keys) > 0, "Expected post_final_answer hooks to be discovered"

    def test_hooks_contains_pre_run(self):
        """Test HOOKS contains pre_run hooks."""
        from topsailai.workspace.agent.hooks.base.init import HOOKS

        # The pre_run module should be discovered
        matching_keys = [k for k in HOOKS.keys() if k.startswith("pre_run")]
        assert len(matching_keys) > 0, "Expected pre_run hooks to be discovered"

    def test_hooks_not_empty(self):
        """Test HOOKS is not empty (hooks were discovered)."""
        from topsailai.workspace.agent.hooks.base.init import HOOKS

        assert len(HOOKS) > 0, "HOOKS should not be empty"


class TestGetHooksIntegration:
    """Integration tests for get_hooks with real HOOKS."""

    def test_get_hooks_with_real_post_final_answer(self):
        """Test get_hooks finds post_final_answer hooks."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks, HOOKS

        result = get_hooks("post_final_answer")
        assert len(result) > 0
        # Verify returned functions are from HOOKS
        for func in result:
            assert func in HOOKS.values()

    def test_get_hooks_with_real_pre_run(self):
        """Test get_hooks finds pre_run hooks."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks, HOOKS

        result = get_hooks("pre_run")
        assert len(result) > 0
        # Verify returned functions are from HOOKS
        for func in result:
            assert func in HOOKS.values()

    def test_get_hooks_returns_callable_items(self):
        """Test get_hooks returns only callable items."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        result = get_hooks("")
        for func in result:
            assert callable(func)

    def test_get_hooks_empty_prefix_returns_all_hooks(self):
        """Test get_hooks with empty prefix returns all discovered hooks."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks, HOOKS

        result = get_hooks("")
        assert len(result) == len(HOOKS)

    def test_get_hooks_no_match_returns_empty(self):
        """Test get_hooks with non-existent prefix returns empty list."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks

        result = get_hooks("this_prefix_definitely_does_not_exist_anywhere")
        assert result == []
