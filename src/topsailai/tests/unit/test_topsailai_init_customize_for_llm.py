import os
import subprocess
import sys
import tempfile

import pytest


class TestCustomizeForLLM:
    """Tests for topsailai.__init__.customize_for_llm() tool-call auto-enable logic."""

    @staticmethod
    def _run_customize(env):
        """Run customize_for_llm() in a fresh subprocess and return TOPSAILAI_USE_TOOL_CALLS."""
        script = (
            "import os; "
            "from topsailai import customize_for_llm; "
            "customize_for_llm(); "
            "print(os.environ.get('TOPSAILAI_USE_TOOL_CALLS', 'NOT_SET'))"
        )
        full_env = os.environ.copy()
        # Remove any inherited TOPSAILAI_USE_TOOL_CALLS so tests exercise the
        # auto-enable logic unless they explicitly set it themselves.
        full_env.pop("TOPSAILAI_USE_TOOL_CALLS", None)
        full_env.update(env)

        # Use a temporary TOPSAILAI_HOME so __load_env() does not pick up the
        # real ~/.topsailai/.env (which symlinks to env_template and sets
        # TOPSAILAI_USE_TOOL_CALLS=0).
        tmp_home = tempfile.mkdtemp(prefix="topsailai_test_home_")
        os.makedirs(os.path.join(tmp_home, "log"), exist_ok=True)
        full_env["TOPSAILAI_HOME"] = tmp_home

        try:
            proc = subprocess.run(
                [sys.executable, "-c", script],
                env=full_env,
                capture_output=True,
                text=True,
                cwd="/TopsailAI/src/topsailai",
            )
            assert proc.returncode == 0, f"subprocess failed: {proc.stderr}"
            return proc.stdout.strip()
        finally:
            import shutil
            shutil.rmtree(tmp_home, ignore_errors=True)

    def test_default_prefixes_enable_gpt(self):
        assert self._run_customize({"OPENAI_MODEL": "gpt-4o"}) == "1"

    def test_default_prefixes_enable_minimax(self):
        assert self._run_customize({"OPENAI_MODEL": "minimax-text-01"}) == "1"

    def test_default_prefixes_case_insensitive(self):
        assert self._run_customize({"OPENAI_MODEL": "GPT-4o"}) == "1"
        assert self._run_customize({"OPENAI_MODEL": "MiniMax-M2.5"}) == "1"

    def test_non_matching_model_does_not_enable(self):
        assert self._run_customize({"OPENAI_MODEL": "Kimi-K2.5"}) == "NOT_SET"

    def test_custom_prefixes_enable(self):
        env = {
            "OPENAI_MODEL": "claude-3-opus",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "claude,gemini",
        }
        assert self._run_customize(env) == "1"

    def test_custom_prefixes_whitespace_and_empty_entries_ignored(self):
        env = {
            "OPENAI_MODEL": "claude-3-opus",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": " gpt , , claude ,",
        }
        assert self._run_customize(env) == "1"

    def test_custom_prefixes_non_matching(self):
        env = {
            "OPENAI_MODEL": "gpt-4o",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "claude",
        }
        assert self._run_customize(env) == "NOT_SET"

    def test_explicit_use_tool_calls_is_respected(self):
        env = {
            "OPENAI_MODEL": "gpt-4o",
            "TOPSAILAI_USE_TOOL_CALLS": "0",
        }
        assert self._run_customize(env) == "0"

    def test_explicit_use_tool_calls_one_is_respected(self):
        env = {
            "OPENAI_MODEL": "Kimi-K2.5",
            "TOPSAILAI_USE_TOOL_CALLS": "1",
        }
        assert self._run_customize(env) == "1"

    def test_empty_model_does_not_enable(self):
        assert self._run_customize({"OPENAI_MODEL": ""}) == "NOT_SET"

    def test_empty_prefixes_does_not_enable(self):
        env = {
            "OPENAI_MODEL": "gpt-4o",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
        }
        assert self._run_customize(env) == "NOT_SET"
