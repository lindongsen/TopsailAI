"""Verify plugin instructions return display content without writing stdout.

Author: DawsonLin
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from topsailai.utils.instruction_tool import HookInstruction
from topsailai.workspace.plugin_instruction import skill


def test_skill_show_returns_filtered_content(monkeypatch, capsys):
    """Return only matching skills and their folders without direct output."""
    skills = [
        SimpleNamespace(name="alpha", folder="/skills/alpha", __str__=lambda self: "Alpha"),
        SimpleNamespace(name="beta", folder="/skills/beta", __str__=lambda self: "Beta"),
    ]
    monkeypatch.setattr(skill.skill_tool, "get_skills_from_cache", lambda: skills)

    result = skill.show_skills("alpha")

    assert "alpha" in result
    assert "/skills/alpha" in result
    assert "/skills/beta" not in result
    assert capsys.readouterr().out == ""


def test_skill_load_and_unload_return_status(monkeypatch, capsys):
    """Return mutation status while preserving active-agent refresh behavior."""
    agent = MagicMock()
    monkeypatch.setattr(skill, "get_ai_agent", lambda: agent)
    monkeypatch.setattr(skill.skill_tool, "load_skill", lambda folder: None)
    monkeypatch.setattr(skill.skill_tool, "unload_skill", lambda folder: None)
    monkeypatch.setattr(skill.skill_tool, "exists_skill", lambda folder: True)
    monkeypatch.setattr(skill.skill_tool, "get_skills_from_cache", lambda: [])

    assert skill.load_skill("/skills/alpha") == "OK"
    assert skill.unload_skill("/skills/alpha") == "OK"
    agent.add_tools_by_module.assert_called_once_with("topsailai.tools.skill_tool")
    agent.remove_tools.assert_called_once_with("skill_tool")
    assert agent.reload_tool_prompt.call_count == 2
    assert capsys.readouterr().out == ""


def test_skill_hooks_returns_sorted_names(monkeypatch, capsys):
    """Return stable hook-name display text without direct output."""
    monkeypatch.setattr(skill.skill_hook, "get_hooks", lambda: {"z": object(), "a": object()})

    assert skill.show_hooks() == "['a', 'z']"
    assert capsys.readouterr().out == ""


def test_interactive_plugin_result_is_printed_once(tmp_path, capsys):
    """Keep stdout ownership in call_hook for return-based plugin handlers."""
    hooks = HookInstruction(str(tmp_path / "completions.json"), {"/skill.hooks": skill.show_hooks})
    original = skill.skill_hook.get_hooks
    skill.skill_hook.get_hooks = lambda: {"alpha": object()}
    try:
        hooks.call_hook("/skill.hooks")
    finally:
        skill.skill_hook.get_hooks = original

    assert capsys.readouterr().out == "['alpha']\n"
