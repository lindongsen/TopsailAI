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
from topsailai.utils.env_tool import resolve_python_interpreter


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
    assert [script.module_name for script in scripts] == [
        "p010_first",
        "p020_second",
        "p030_invalid",
        "p040_empty",
        "p050_timeout",
    ]
    assert all(script.kind == runner.SCRIPT_KIND_SOURCE for script in scripts)


def test_discover_scripts_missing_dir():
    """Verify discovery returns empty for a missing folder."""
    assert runner._discover_scripts("/nonexistent/path") == []


def test_discover_scripts_directory_failure_returns_empty(tmp_path, monkeypatch):
    """Verify directory enumeration failures remain fail-open."""
    script_dir = tmp_path / "hooks"
    script_dir.mkdir()
    monkeypatch.setattr(
        runner.pkgutil,
        "iter_modules",
        lambda paths: (_ for _ in ()).throw(RuntimeError("sensitive detail")),
    )
    warnings = []
    monkeypatch.setattr(runner.logger, "warning", lambda *args: warnings.append(args))

    assert runner._discover_scripts(str(script_dir)) == []
    assert warnings == [
        ("LLM mistake hook script directory discovery failed (%s)", "RuntimeError")
    ]


def test_discover_scripts_skips_failed_module_and_continues(tmp_path, monkeypatch):
    """Verify one finder failure does not discard later valid hook modules."""
    script_dir = tmp_path / "hooks"
    script_dir.mkdir()
    valid_path = script_dir / "p020_valid.py"
    valid_path.write_text("", encoding="utf-8")

    class FailingFinder:
        """Raise a loader-specific error while resolving one module."""

        @staticmethod
        def find_spec(name):
            raise ValueError("sensitive detail")

    class ValidFinder:
        """Return the later valid source module."""

        @staticmethod
        def find_spec(name):
            return type("Spec", (), {"origin": str(valid_path)})()

    modules = [
        runner.pkgutil.ModuleInfo(FailingFinder(), "p010_failed", False),
        runner.pkgutil.ModuleInfo(ValidFinder(), "p020_valid", False),
    ]
    monkeypatch.setattr(runner.pkgutil, "iter_modules", lambda paths: modules)
    warnings = []
    monkeypatch.setattr(runner.logger, "warning", lambda *args: warnings.append(args))

    assert runner._discover_scripts(str(script_dir)) == [
        runner.HookScript("p020_valid", str(valid_path), runner.SCRIPT_KIND_SOURCE)
    ]
    assert warnings == [
        (
            "LLM mistake hook module %s discovery failed (%s); skipped",
            "p010_failed",
            "ValueError",
        )
    ]


def test_discover_scripts_accepts_extension_suffix(tmp_path, monkeypatch):
    """Verify discovery accepts the platform extension suffix via its finder."""
    script_dir = tmp_path / "hooks"
    script_dir.mkdir()
    extension_path = script_dir / (
        "p010_compiled" + runner.importlib.machinery.EXTENSION_SUFFIXES[0]
    )
    extension_path.write_bytes(b"")

    class Finder:
        """Return the synthetic extension artifact spec."""

        @staticmethod
        def find_spec(name):
            return type("Spec", (), {"origin": str(extension_path)})()

    module = runner.pkgutil.ModuleInfo(Finder(), "p010_compiled", False)
    monkeypatch.setattr(runner.pkgutil, "iter_modules", lambda paths: [module])

    assert runner._discover_scripts(str(script_dir)) == [
        runner.HookScript(
            "p010_compiled", str(extension_path), runner.SCRIPT_KIND_EXTENSION
        )
    ]



def test_retained_source_only_directory_discovers_and_executes_directly(
    tmp_path, monkeypatch
):
    """Verify compiled packages may retain directly executable source hooks."""
    script_dir = tmp_path / "hooks"
    script_dir.mkdir()
    source_path = script_dir / "p010_retained.py"
    source_path.write_text("", encoding="utf-8")
    scripts = runner._discover_scripts(str(script_dir))
    captured = {}
    original_popen = subprocess.Popen

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        return original_popen(
            [
                sys.executable,
                "-c",
                "import simplejson; print(simplejson.dumps([{'step_name': 'thought', 'raw_text': 'source'}]))",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)

    assert scripts == [
        runner.HookScript(
            "p010_retained", str(source_path), runner.SCRIPT_KIND_SOURCE
        )
    ]
    outcome, result = runner._run_single_script(
        scripts[0], str(script_dir), "deepseek-chat", "response", None
    )
    assert outcome == "handled"
    assert result == [{"step_name": "thought", "raw_text": "source"}]
    assert captured["argv"] == [resolve_python_interpreter(), str(source_path)]


def test_mixed_source_and_extension_discovery_and_execution_paths(
    tmp_path, monkeypatch
):
    """Verify mixed artifacts are ordered and use their matching execution paths."""
    script_dir = tmp_path / "hooks"
    script_dir.mkdir()
    source_path = script_dir / "p010_retained.py"
    source_path.write_text("", encoding="utf-8")
    extension_path = script_dir / (
        "p020_compiled" + runner.importlib.machinery.EXTENSION_SUFFIXES[0]
    )
    extension_path.write_bytes(b"")
    scripts = runner._discover_scripts(str(script_dir))
    commands = []
    original_popen = subprocess.Popen

    def fake_popen(argv, **kwargs):
        commands.append(argv)
        return original_popen(
            [
                sys.executable,
                "-c",
                "import simplejson; print(simplejson.dumps([{'step_name': 'thought', 'raw_text': 'ok'}]))",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    for script in scripts:
        outcome, _ = runner._run_single_script(
            script, str(script_dir), "deepseek-chat", "response", None
        )
        assert outcome == "handled"

    assert scripts == [
        runner.HookScript(
            "p010_retained", str(source_path), runner.SCRIPT_KIND_SOURCE
        ),
        runner.HookScript(
            "p020_compiled", str(extension_path), runner.SCRIPT_KIND_EXTENSION
        ),
    ]
    interpreter = resolve_python_interpreter()
    assert commands == [
        [interpreter, str(source_path)],
        [interpreter, "-c", runner.EXTENSION_BOOTSTRAP, "p020_compiled"],
    ]


def test_same_name_extension_takes_import_precedence_over_source(tmp_path):
    """Verify Python finder precedence selects one extension for a duplicate name."""
    script_dir = tmp_path / "hooks"
    script_dir.mkdir()
    source_path = script_dir / "p010_same.py"
    source_path.write_text("", encoding="utf-8")
    extension_path = script_dir / (
        "p010_same" + runner.importlib.machinery.EXTENSION_SUFFIXES[0]
    )
    extension_path.write_bytes(b"")

    assert runner._discover_scripts(str(script_dir)) == [
        runner.HookScript(
            "p010_same", str(extension_path), runner.SCRIPT_KIND_EXTENSION
        )
    ]


def test_run_single_extension_imports_module_by_separate_argument(tmp_path, monkeypatch):
    """Verify extension execution imports by name through the fixed bootstrap."""
    extension_path = tmp_path / (
        "p010_compiled" + runner.importlib.machinery.EXTENSION_SUFFIXES[0]
    )
    captured = {}
    original_popen = subprocess.Popen

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return original_popen(
            [
                sys.executable,
                "-c",
                "import simplejson; print(simplejson.dumps([{'step_name': 'thought', 'raw_text': 'ok'}]))",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    script = runner.HookScript(
        "p010_compiled", str(extension_path), runner.SCRIPT_KIND_EXTENSION
    )

    outcome, result = runner._run_single_script(
        script, str(tmp_path), "deepseek-chat", "response", None
    )

    assert outcome == "handled"
    assert result == [{"step_name": "thought", "raw_text": "ok"}]
    assert captured["argv"] == [
        resolve_python_interpreter(),
        "-c",
        runner.EXTENSION_BOOTSTRAP,
        "p010_compiled",
    ]
    assert str(extension_path) not in captured["argv"]
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["start_new_session"] is True


def test_run_single_extension_executes_imported_main(tmp_path):
    """Verify the extension bootstrap imports a module and calls its main."""
    module_path = tmp_path / "p010_compiled.py"
    module_path.write_text(
        textwrap.dedent(
            """\
            import simplejson

            def main():
                print(simplejson.dumps([{"step_name": "thought", "raw_text": "compiled"}]))
            """
        ),
        encoding="utf-8",
    )
    script = runner.HookScript(
        "p010_compiled", str(module_path), runner.SCRIPT_KIND_EXTENSION
    )

    outcome, result = runner._run_single_script(
        script, str(tmp_path), "deepseek-chat", "response", None
    )

    assert outcome == "handled"
    assert result == [{"step_name": "thought", "raw_text": "compiled"}]


@pytest.mark.parametrize(
    ("kind", "artifact_name"),
    [
        (runner.SCRIPT_KIND_SOURCE, "p010_source.py"),
        (
            runner.SCRIPT_KIND_EXTENSION,
            "p010_compiled" + runner.importlib.machinery.EXTENSION_SUFFIXES[0],
        ),
    ],
)
def test_interpreter_resolution_failure_preserves_public_fallback(
    tmp_path, monkeypatch, kind, artifact_name
):
    """Verify interpreter resolution failures fall back for both hook kinds."""
    script = runner.HookScript("p010_hook", str(tmp_path / artifact_name), kind)
    monkeypatch.setattr(runner, "_discover_scripts", lambda script_dir: [script])

    def fail_resolution():
        raise RuntimeError("no usable Python interpreter")

    def fail_popen(*args, **kwargs):
        pytest.fail("subprocess must not start when interpreter resolution fails")

    monkeypatch.setattr(runner, "resolve_python_interpreter", fail_resolution)
    monkeypatch.setattr(runner.subprocess, "Popen", fail_popen)

    assert runner.run_hook_scripts(str(tmp_path), "deepseek-chat", "response") is None


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
    assert captured["argv"][0] == resolve_python_interpreter()


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
