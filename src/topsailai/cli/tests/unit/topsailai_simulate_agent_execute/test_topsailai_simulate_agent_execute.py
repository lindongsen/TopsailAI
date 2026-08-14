"""Unit tests for topsailai_simulate_agent_execute.py."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

# Make ``cli`` (this test lives 3 levels below it) and the project source root
# (one level above ``cli``) importable without relying on _import_topsailai.
_CLI_DIR = Path(__file__).resolve().parents[3]
_SRC_ROOT = Path(__file__).resolve().parents[4]
for _p in (_CLI_DIR, _SRC_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest

import topsailai_simulate_agent_execute as cli


class TestArgParsing:
    """Tests for argument parsing and usage errors."""


    def test_defaults(self):
        args = cli.parse_args(["--text", "x"])
        assert args.max_steps == 50
        assert args.interactive is False
        assert args.show_tools is False
        assert args.output_format == "transcript"
        assert args.quiet is False

    def test_text_and_file_mutually_exclusive(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.parse_args(["--text", "a", "--file", "b"])
        assert exc.value.code == 2

    def test_invalid_output_format(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.parse_args(["--output-format", "nope"])
        assert exc.value.code == 2


class TestInputReading:
    """Tests for reading input from text/file/stdin."""

    def test_read_from_file(self, tmp_path):
        path = tmp_path / "response.txt"
        path.write_text("topsailai.final_answer\nhi")
        assert cli.read_input(str(path)) == "topsailai.final_answer\nhi"

    def test_read_from_stdin(self):
        with mock.patch("sys.stdin", io.StringIO("stdin text")):
            assert cli.read_input("-") == "stdin text"


class TestToolMapFiltering:
    """Tests for tool-map building and prefix filtering."""

    def test_build_all_tools(self):
        tool_map = cli.build_tool_map()
        assert isinstance(tool_map, dict)
        assert len(tool_map) > 0

    def test_only_prefix_filter(self):
        tool_map = cli.build_tool_map(only="time_tool")
        assert all(k.startswith("time_tool") for k in tool_map)

    def test_exclude_prefix_filter(self):
        full = cli.build_tool_map()
        filtered = cli.build_tool_map(exclude="cmd_tool;file_tool")
        assert not any(
            k.startswith("cmd_tool") or k.startswith("file_tool") for k in filtered
        )
        assert set(full).issuperset(set(filtered))


class TestPendingFinalExtraction:
    """Tests for extracting a candidate final answer before mistake-fixing."""

    def test_extract_topsailai_final(self):
        text = "topsailai.action\n{\"tool_call\": \"t\"}\ntopsailai.final_answer\ndone"
        assert cli.extract_pending_final(text) == "done"

    def test_extract_json_list_final(self):
        steps = [
            {"step_name": "action", "raw_text": '{"tool_call":"t"}'},
            {"step_name": "final_answer", "raw_text": "result"},
        ]
        assert cli.extract_pending_final(json.dumps(steps)) == "result"

    def test_extract_none_for_empty(self):
        assert cli.extract_pending_final("") is None
        assert cli.extract_pending_final(None) is None


class TestSimulateDriver:
    """Tests for the headless execution engine."""

    def test_final_answer_reached(self):
        records, result = cli.simulate("topsailai.final_answer\nhello world")
        assert result == "hello world"
        assert records[-1]["step_name"] == "final_answer"

    def test_action_dispatch_with_real_tool(self):
        text = (
            "topsailai.action\n"
            '{"tool_call": "time_tool-get_local_time"}'
        )
        records, result = cli.simulate(text)
        action_records = [r for r in records if r["step_name"] == "action"]
        assert action_records
        obs = action_records[0].get("observation")
        assert obs is not None

    def test_max_steps_enforced(self):
        # Two-step response (action + trailing final converted to thought).
        text = (
            "topsailai.action\n"
            '{"tool_call": "time_tool-get_local_time"}\n'
            "topsailai.final_answer\ndone"
        )
        with pytest.raises(cli.MaxStepsExceeded):
            cli.simulate(text, max_steps=1)

    def test_unknown_tool_graceful(self):
        text = "topsailai.action\n{\"tool_call\": \"no-such-tool\", \"tool_args\": {}}"
        records, result = cli.simulate(text)
        assert result is None
        assert records[0]["step_name"] == "action"

    def test_non_interactive_thought_only(self):
        text = "topsailai.thought\njust thinking"
        records, result = cli.simulate(text)
        assert result is None
        assert records[0]["step_name"] == "thought"

    def test_show_tools_flag(self, capsys):
        cli.simulate("topsailai.final_answer\nok", show_tools=True)
        captured = capsys.readouterr()
        assert "[available_tools]" in captured.out


class TestRendering:
    """Tests for output rendering modes."""

    def test_transcript_mode(self):
        out = cli.render_output(
            [{"index": 0, "step_name": "final_answer", "raw_text": "hi"}],
            "hi",
            "transcript",
            2,
            False,
            False,
        )
        assert "final_answer" in out
        assert "hi" in out

    def test_json_mode(self):
        out = cli.render_output(
            [{"index": 0, "step_name": "final_answer", "raw_text": "hi"}],
            "hi",
            "json",
            2,
            False,
            False,
        )
        payload = json.loads(out)
        assert payload["result"] == "hi"

    def test_topsailai_mode(self):
        out = cli.render_output(
            [{"index": 0, "step_name": "final_answer", "raw_text": "hi"}],
            "hi",
            "topsailai",
            2,
            False,
            False,
        )
        assert "topsailai.final_answer" in out

    def test_quiet_mode(self):
        out = cli.render_output(
            [{"index": 0, "step_name": "final_answer", "raw_text": "hi"}],
            "hi",
            "transcript",
            2,
            False,
            True,
        )
        assert out == "hi"


class TestMainEntry:
    """Tests for the main() entry point and exit codes."""

    def test_main_no_input(self):
        assert cli.main([]) == cli.EXIT_USAGE

    def test_main_text_final(self, capsys):
        code = cli.main(["--text", "topsailai.final_answer\nhi"])
        captured = capsys.readouterr()
        assert code == cli.EXIT_OK
        assert "hi" in captured.out

    def test_main_file_not_found(self, capsys):
        code = cli.main(["--file", "/nonexistent/xyz.txt"])
        assert code == cli.EXIT_ERROR
    def test_main_max_steps_exit_code(self, capsys):
        code = cli.main(
            [
                "--max-steps",
                "1",
                "--text",
                "topsailai.action\n{\"tool_call\": \"time_tool-get_local_time\"}\n"
                "topsailai.final_answer\ndone",
            ]
        )
        assert code == cli.EXIT_MAX_STEPS

    def test_main_stdin(self, capsys):
        with mock.patch(
            "sys.stdin", io.StringIO("topsailai.final_answer\nstdin-result")
        ):
            code = cli.main(["-"])
        captured = capsys.readouterr()
        assert code == cli.EXIT_OK
        assert "stdin-result" in captured.out

class TestPathResolution:
    """Tests for PWD-aware path resolution."""

    def test_resolve_relative(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_PWD", "/tmp/base")
        assert cli.resolve_path("a.txt") == "/tmp/base/a.txt"

    def test_resolve_absolute_unaffected(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_PWD", "/tmp/base")
        assert cli.resolve_path("/abs/x.txt") == "/abs/x.txt"


class TestStepRecordAndFlatten:
    """Tests for structured record building and topsailai flattening."""

    def test_step_record_full_fields(self):
        rec = {"index": 0, "step_name": "action", "raw_text": '{"t":"x"}',
               "tool_call": "time_tool-get_local_time", "tool_args": {}}
        ret = type("R", (), {
            "user_msg": "u", "tool_msg": "obs", "result": "r",
            "CODE_TASK_FINAL": 3, "code": 2,
        })()
        out = cli._step_record(0, rec, ret)
        assert out["observation"] == "obs"
        assert out["user_msg"] == "u"
        assert out["result"] == "r"

    def test_flatten_with_observation_and_no_raw(self):
        records = [
            {"index": 0, "step_name": "action", "tool_call": "time_tool-x",
             "tool_args": {}, "observation": "the obs"},
        ]
        flat = cli.flatten_for_topsailai(records)
        names = [s.get("step_name") for s in flat]
        assert "action" in names
        assert "observation" in names


class TestRenderDetail:
    """Tests for detailed transcript rendering branches."""

    def _rec(self, **kw):
        base = {"index": 0, "step_name": "action"}
        base.update(kw)
        return base

    def test_transcript_action_detail(self):
        rec = self._rec(raw_text='{"t":"x"}', tool_call="time_tool-a",
                        tool_args={"k": 1}, observation="o", user_msg="um",
                        error=None, result=None)
        out = cli.render_transcript([rec])
        assert "-> tool:" in out
        assert "-> observation:" in out
        assert "-> user_msg:" in out

    def test_transcript_error_line(self):
        rec = self._rec(error="boom")
        out = cli.render_transcript([rec])
        assert "-> error: boom" in out

    def test_render_json_compact(self):
        out = cli.render_output(
            [{"index": 0, "step_name": "final_answer", "raw_text": "hi"}],
            "hi", "json", 2, True, False,
        )
        payload = json.loads(out)
        assert payload["result"] == "hi"


class TestMainEntryExtended:
    """Additional main() entry-point branch coverage."""

    def test_main_file_success(self, tmp_path, capsys):
        p = tmp_path / "resp.txt"
        p.write_text("topsailai.final_answer\nfrom-file")
        code = cli.main(["--file", str(p)])
        assert code == cli.EXIT_OK
        assert "from-file" in capsys.readouterr().out

    def test_main_positional_single_file(self, tmp_path, capsys):
        p = tmp_path / "pos.txt"
        p.write_text("topsailai.final_answer\npositional")
        code = cli.main([str(p)])
        assert code == cli.EXIT_OK
        assert "positional" in capsys.readouterr().out

    def test_main_text_with_files_usage(self, capsys):
        code = cli.main(["--text", "x", "extra"])
        assert code == cli.EXIT_USAGE

    def test_main_multiple_positional_usage(self, capsys):
        code = cli.main(["a.txt", "b.txt"])
        assert code == cli.EXIT_USAGE

    def test_main_positional_not_found(self, capsys):
        code = cli.main(["/nonexistent/nope.txt"])
        assert code == cli.EXIT_ERROR

    def test_main_result_none_is_error(self, capsys):
        code = cli.main(["--text", "topsailai.thought\njust thinking"])
        assert code == cli.EXIT_ERROR

    def test_main_generic_exception(self, capsys, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("sim-boom")
        monkeypatch.setattr(cli, "build_tool_map", boom)
        code = cli.main(["--text", "topsailai.final_answer\nx"])
        assert code == cli.EXIT_ERROR

    def test_main_read_error(self, tmp_path, capsys, monkeypatch):
        p = tmp_path / "bad.txt"
        p.write_text("x")

        def raiser(path):
            raise OSError("read fail")
        monkeypatch.setattr(cli, "read_file", raiser)
        code = cli.main(["--file", str(p)])
        assert code == cli.EXIT_ERROR
class TestCoverageBranches:
    """Targeted tests for uncovered branches in the simulator module."""

    def test_extract_pending_final_parse_error(self, monkeypatch):
        # parse_topsailai_format raising must fall back to JSON and then None.
        def boom(text):
            raise ValueError("bad format")
        monkeypatch.setattr(cli, "parse_topsailai_format", boom)
        assert cli.extract_pending_final("topsailai.final_answer\nx") is None

    def test_extract_pending_final_json_non_dict_and_empty_value(self):
        # Non-dict step skips; final with empty raw_text falls through to None.
        assert cli.extract_pending_final('[{"step_name":"action","raw_text":"go"}, ["x"]]') is None
        assert cli.extract_pending_final('[{"step_name":"final_answer","raw_text":""}]') is None

    def test_step_call_exception_recorded_gracefully(self):
        text = 'topsailai.action\n{"tool_call": "no-such-tool", "tool_args": {}}'
        with mock.patch(
            "topsailai.ai_base.agent_types.react.AgentStepCall",
            return_value=mock.MagicMock(side_effect=RuntimeError("boom")),
        ):
            records, result = cli.simulate(text, tool_map={})
        assert result is None
        assert records[0]["error"] and "boom" in records[0]["error"]

    def test_result_uses_pending_final_when_no_live_final(self):
        # Action + trailing final: mistake-fixer converts final into a thought,
        # so no live CODE_TASK_FINAL fires; pending_final supplies the answer.
        text = (
            "topsailai.action\n"
            '{"tool_call": "time_tool-get_local_time"}\n'
            "topsailai.final_answer\ndone"
        )
        _, result = cli.simulate(text)
        assert result == "done"

    def test_interactive_env_restored_to_previous(self, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_CHAT_INTERACTIVE_MODE", "1")
        cli.simulate("topsailai.final_answer\nx")
        assert os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE") == "1"

    def test_flatten_toolcall_without_stepname_and_observation(self):
        flat = cli.flatten_for_topsailai([
            {"tool_call": "t1", "tool_args": {"a": 1}, "observation": "o1"},
            {},
        ])
        expected_raw = json.dumps({"tool_call": "t1", "tool_args": {"a": 1}}, ensure_ascii=False)
        assert flat == [
            {"raw_text": expected_raw},
            {"step_name": "observation", "raw_text": "o1"},
        ]

    def test_main_file_with_positional_usage(self, tmp_path, capsys):
        p = tmp_path / "f.txt"
        p.write_text("x")
        code = cli.main(["--file", str(p), "extra.txt"])
        assert code == cli.EXIT_USAGE

    def test_main_positional_read_error(self, tmp_path, capsys, monkeypatch):
        p = tmp_path / "ok.txt"
        p.write_text("x")

        def raiser(path):
            raise OSError("read fail")
        monkeypatch.setattr(cli, "read_file", raiser)
        code = cli.main([str(p)])
        assert code == cli.EXIT_ERROR


class TestModuleEntryPoint:
    """Subprocess-level coverage for top-level import/entry behavior."""

    def test_chdir_on_pwd_set(self):
        target = tempfile.mkdtemp()
        env = dict(os.environ)
        env["TOPSAILAI_PWD"] = target
        snippet = (
            "import os,sys; "
            f"sys.path.insert(0,{json.dumps(str(_CLI_DIR))}); "
            "import topsailai_simulate_agent_execute as m; print(m.PWD)"
        )
        r = subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True, text=True, env=env, cwd="/tmp",
        )
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == target

    def test_module_runs_as_script(self):
        src = Path(cli.__file__).resolve()
        r = subprocess.run(
            [sys.executable, str(src), "--text", "topsailai.final_answer\nhi"],
            capture_output=True, text=True, cwd=str(src.parent),
        )
        assert r.returncode == 0, r.stderr
        assert "hi" in r.stdout