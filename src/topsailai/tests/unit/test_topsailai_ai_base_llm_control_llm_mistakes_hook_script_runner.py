"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-10
Purpose: Unit tests for the subprocess-based LLM mistake hook script runner.
"""

import os
import subprocess
import sys
import textwrap

import pytest

from topsailai.ai_base.llm_control.llm_mistakes import hook_script_runner as runner


@pytest.fixture()
def script_dir(tmp_path):
    """Create a temporary model script folder with helper and case scripts."""
    d = tmp_path / "deepseek_hook_scripts"
    d.mkdir()
    (d / "__init__.py").write_text("", encoding="utf-8")
    (d / "_helper.py").write_text("", encoding="utf-8")
    (d / "p010_first.py").write_text(
        textwrap.dedent(
            """\
            import os
            import sys
            import simplejson
            sys.path.insert(0, os.path.dirname(__file__))
            import _helper
            def main():
                resp = os.environ.get("TOPSAILAI_LLM_MISTAKE_RESPONSE")
                if resp is None:
                    f = os.environ.get("TOPSAILAI_LLM_MISTAKE_RESPONSE_FILE")
                    if f:
                        with open(f, "r", encoding="utf-8") as fh:
                            resp = fh.read()
                if resp and "first" in resp:
                    print(simplejson.dumps([{"step_name": "action", "tool_call": "t1", "tool_args": {"k": "v"}}]))
            if __name__ == "__main__":
                main()
            """
        ),
        encoding="utf-8",
    )
    (d / "p020_second.py").write_text(
        textwrap.dedent(
            """\
            import os
            import simplejson
            def main():
                resp = os.environ.get("TOPSAILAI_LLM_MISTAKE_RESPONSE")
                if resp and "second" in resp:
                    print(simplejson.dumps([{"step_name": "action", "tool_call": "t2", "tool_args": {}}]))
            if __name__ == "__main__":
                main()
            """
        ),
        encoding="utf-8",
    )
    (d / "p030_invalid.py").write_text(
        "print('not json')\n",
        encoding="utf-8",
    )
    (d / "p040_empty.py").write_text(
        "print('   ')\n",
        encoding="utf-8",
    )
    (d / "p050_timeout.py").write_text(
        "import time; time.sleep(30)\n",
        encoding="utf-8",
    )
    (d / "ignore.tmp").write_text("print('x')\n", encoding="utf-8")
    return str(d)


def test_discover_scripts_orders_and_filters(script_dir):
    """Verify discovery sorts by name and ignores helpers/temp files."""
    scripts = runner._discover_scripts(script_dir)
    names = [os.path.basename(s) for s in scripts]
    assert names == [
        "p010_first.py",
        "p020_second.py",
        "p030_invalid.py",
        "p040_empty.py",
        "p050_timeout.py",
    ]


def test_discover_scripts_missing_dir():
    """Verify discovery returns empty for a missing folder."""
    assert runner._discover_scripts("/nonexistent/path") == []


def test_run_hook_scripts_first_match_short_circuits(script_dir):
    """Verify the first script that handles the response short-circuits."""
    result = runner.run_hook_scripts(script_dir, "deepseek-chat", "first")
    assert result == [{"step_name": "action", "tool_call": "t1", "tool_args": {"k": "v"}}]


def test_run_hook_scripts_second_match(script_dir):
    """Verify a later script handles when earlier ones do not."""
    result = runner.run_hook_scripts(script_dir, "deepseek-chat", "second")
    assert result == [{"step_name": "action", "tool_call": "t2", "tool_args": {}}]


def test_run_hook_scripts_no_match_returns_none(script_dir):
    """Verify None is returned when no script handles the response."""
    assert runner.run_hook_scripts(script_dir, "deepseek-chat", "nothing-matches") is None


def test_run_hook_scripts_invalid_json_continues(script_dir):
    """Verify invalid JSON output is treated as failure and skipped."""
    # p030 prints invalid JSON; p040 prints whitespace; none handle "invalid"
    assert runner.run_hook_scripts(script_dir, "deepseek-chat", "invalid") is None


def test_run_hook_scripts_timeout_returns_none(script_dir, monkeypatch):
    """Verify a timeout does not hang and returns None."""
    monkeypatch.setenv("TOPSAILAI_LLM_MISTAKE_SCRIPT_TIMEOUT", "1")
    # p050 sleeps 30s; with 1s timeout it must be killed and skipped.
    assert runner.run_hook_scripts(script_dir, "deepseek-chat", "timeout-case") is None


def test_run_hook_scripts_non_string_returns_none(script_dir):
    """Verify non-string responses are rejected."""
    assert runner.run_hook_scripts(script_dir, "deepseek-chat", None) is None
    assert runner.run_hook_scripts(script_dir, "deepseek-chat", "") is None


def test_run_hook_scripts_empty_dir(tmp_path):
    """Verify an empty script folder returns None."""
    d = tmp_path / "empty"
    d.mkdir()
    assert runner.run_hook_scripts(str(d), "deepseek-chat", "anything") is None


def test_env_contract_passes_model_and_response(script_dir, monkeypatch):
    """Verify the child env contains the model name and response."""
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["env"] = kwargs["env"]
        captured["argv"] = argv
        captured["cwd"] = kwargs["cwd"]
        captured["start_new_session"] = kwargs["start_new_session"]
        proc = orig_popen(
            [sys.executable, "-c", "import simplejson; print(simplejson.dumps([{'step_name': 'action', 'tool_call': 't', 'tool_args': {}}]))"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return proc

    orig_popen = subprocess.Popen
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    runner.run_hook_scripts(script_dir, "deepseek-chat", "first")
    assert captured["env"]["TOPSAILAI_LLM_MISTAKE_MODEL"] == "deepseek-chat"
    assert captured["env"]["TOPSAILAI_LLM_MISTAKE_RESPONSE"] == "first"
    assert captured["env"]["TOPSAILAI_LLM_MISTAKE_SCRIPT"].endswith("p010_first.py")
    assert captured["env"]["TOPSAILAI_LLM_MISTAKE_SCRIPT_DIR"] == script_dir
    assert captured["cwd"] == script_dir
    assert captured["start_new_session"] is True
    assert captured["argv"][0] == sys.executable


def test_env_contract_minimal_curated(script_dir, monkeypatch):
    """Verify the child env is minimal and does not leak parent secrets."""
    monkeypatch.setenv("SECRET_TOKEN", "super-secret")
    captured = {}

    def fake_popen(argv, **kwargs):
        captured["env"] = kwargs["env"]
        proc = orig_popen(
            [sys.executable, "-c", "import simplejson; print(simplejson.dumps([{'step_name': 'action', 'tool_call': 't', 'tool_args': {}}]))"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return proc

    orig_popen = subprocess.Popen
    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    runner.run_hook_scripts(script_dir, "deepseek-chat", "first")
    assert "SECRET_TOKEN" not in captured["env"]
    assert "TOPSAILAI_LLM_MISTAKE_MODEL" in captured["env"]


def test_validate_result_accepts_single_dict():
    """Verify a top-level dict is wrapped into a list."""
    result = runner._validate_result({"step_name": "action", "tool_call": "t", "tool_args": {}})
    assert result == [{"step_name": "action", "tool_call": "t", "tool_args": {}}]


def test_validate_result_rejects_invalid():
    """Verify invalid step structures are rejected."""
    assert runner._validate_result([]) is None
    assert runner._validate_result(["not-a-dict"]) is None
    assert runner._validate_result([{"step_name": ""}]) is None
    assert runner._validate_result([{"step_name": "action", "tool_call": "", "tool_args": {}}]) is None
    assert runner._validate_result([{"step_name": "action", "tool_call": "t", "tool_args": "x"}]) is None
    assert runner._validate_result([{"step_name": "thought"}]) is None


def test_output_max_treated_as_failure(script_dir, monkeypatch):
    """Verify oversized stdout is treated as failure."""
    monkeypatch.setenv("TOPSAILAI_LLM_MISTAKE_OUTPUT_MAX", "10")
    # p010 prints a JSON larger than 10 bytes; must be treated as failure.
    assert runner.run_hook_scripts(script_dir, "deepseek-chat", "first") is None


def test_response_file_tier(script_dir, monkeypatch):
    """Verify oversized responses use the temp-file tier."""
    monkeypatch.setenv("TOPSAILAI_LLM_MISTAKE_RESPONSE_MAX_ENV", "10")
    monkeypatch.setenv("TOPSAILAI_LLM_MISTAKE_RESPONSE_MAX_FILE", "1000000")
    big = "first" + "x" * 100
    result = runner.run_hook_scripts(script_dir, "deepseek-chat", big)
    # p010 checks "first" in resp; with temp file tier the script reads the file.
    assert result == [{"step_name": "action", "tool_call": "t1", "tool_args": {"k": "v"}}]


def test_response_too_large_fail_open(script_dir, monkeypatch):
    """Verify responses above the hard cap skip scripts and return None."""
    monkeypatch.setenv("TOPSAILAI_LLM_MISTAKE_RESPONSE_MAX_ENV", "10")
    monkeypatch.setenv("TOPSAILAI_LLM_MISTAKE_RESPONSE_MAX_FILE", "20")
    big = "first" + "x" * 100
    assert runner.run_hook_scripts(script_dir, "deepseek-chat", big) is None


def test_get_model_script_dir_resolves():
    """Verify the model script folder resolves via importlib.resources."""
    pkg = "topsailai.ai_base.llm_control.llm_mistakes.deepseek_hook_scripts"
    folder = runner.get_model_script_dir(pkg, "deepseek_hook_scripts")
    assert folder
    assert os.path.isdir(folder)


def test_get_model_script_dir_invalid_package():
    """Verify an invalid package returns an empty string."""
    assert runner.get_model_script_dir("no.such.package", "x") == ""
