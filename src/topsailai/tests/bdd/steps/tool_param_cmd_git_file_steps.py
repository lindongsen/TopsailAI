"""Step definitions for tool parameter-coercion behavior tests.

Every step text in this module is intentionally phrased with the words ``tool`` and
``parameter`` so it cannot collide with the CLI suite in ``cli/tests/bdd/steps``
(pytest-bdd silently lets identically-parsed steps override each other).

Value tokens understood in Examples tables
------------------------------------------
- ``empty``      -> the empty string
- ``null``       -> ``None``
- ``<sp>``       -> one literal space (Gherkin trims cell whitespace)
- ``int:5`` / ``float:2.5`` / ``bool:True`` -> native Python value
- ``{file}`` / ``{folder}`` / ``{alpha}`` / ``{short}`` -> fixture paths
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

logger = logging.getLogger("tests.bdd.tool_param")

ALPHA_TEXT = "ABCDEFGHIJ"

from tests.bdd.tool_param_harness import (
    PROJECT_WORKSPACE,
    call_tool,
    read_text,
    resolve_value,
    write_sample_file,
    write_short_file,
)


@pytest.fixture
def ctx():
    """Per-scenario state plus a temporary folder that is removed after the scenario."""
    context: dict[str, Any] = {"files": {}, "args": {}, "response": None}
    yield context
    folder = context["files"].get("folder")
    if folder and os.path.isdir(folder):
        shutil.rmtree(folder)
        logger.info("removed parameter test folder: [%s]", folder)


def _expand(context: dict[str, Any], token: str) -> Any:
    """Resolve one Examples cell into the value an LLM would actually send."""
    value = resolve_value(token)
    if isinstance(value, list):
        return [_expand(context, item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(context, item) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    value = value.replace("<sp>", " ")
    if value == "empty":
        return ""
    for placeholder, path in (
        ("{file}", context["files"].get("active", "")),
        ("{folder}", context["files"].get("folder", "")),
        ("{alpha}", context["files"].get("alpha", "")),
        ("{short}", context["files"].get("short", "")),
    ):
        value = value.replace(placeholder, path)
    return value


def _invoke(context: dict[str, Any], tool_name: str, **arguments: Any) -> None:
    """Call one tool through the harness and remember the normalized response."""
    context["response"] = call_tool(tool_name, **arguments)


# --------------------------------------------------------------------------- given


def _tmp_folder(ctx) -> str:
    """Return (creating on first use) the scenario-scoped temporary folder."""
    folder = ctx["files"].get("folder")
    if not folder:
        import tempfile

        folder = tempfile.mkdtemp(prefix="topsailai-bdd-param-")
        ctx["files"]["folder"] = folder
    return folder


@given(parsers.parse('a parameter test file named {name} containing lines LINE01 to LINE20'))
def sample_file(ctx, name):
    """Create the 20-line fixture used by the byte-offset and search tools."""
    ctx["files"]["active"] = write_sample_file(_tmp_folder(ctx), name)


@given(parsers.parse('a parameter test file named {name} containing lines L1 to L10'))
def numbered_file(ctx, name):
    """Create the 10-line fixture used by the line-oriented editing tools."""
    path = write_short_file(_tmp_folder(ctx), name)
    ctx["files"]["active"] = path
    ctx["files"]["short"] = path
    ctx["files"]["numbered"] = path


@given(parsers.parse('a parameter test file named {name} containing the text ABCDEFGHIJ'))
def literal_file(ctx, name):
    """Create the single-line fixture used by the byte-offset write tools."""
    path = os.path.join(_tmp_folder(ctx), name)
    with open(path, "w", encoding="utf-8") as handler:
        handler.write(ALPHA_TEXT)
    ctx["files"]["active"] = path
    ctx["files"]["alpha"] = path


# --------------------------------------------------------------------------- when


@when(parsers.parse('the tool {tool} is called with single parameter {param} set to {value}'))
def call_with_single_parameter(ctx, tool, param, value):
    """An LLM sends exactly one argument, serialized as text."""
    _invoke(ctx, tool, **{param: _expand(ctx, value)})


@when(parsers.parse('the tool {tool} is called with parameter {first_param} set to {first_value} and parameter {second_param} set to {second_value}'))
def call_with_two_parameters(ctx, tool, first_param, first_value, second_param, second_value):
    """An LLM sends two arguments, both serialized as text."""
    _invoke(
        ctx,
        tool,
        **{
            first_param: _expand(ctx, first_value),
            second_param: _expand(ctx, second_value),
        },
    )


@when(parsers.parse('the tool exec_cmd is called with plain command {command}'))
def call_exec_cmd_plain(ctx, command):
    """Baseline: a well-formed command without any numeric argument."""
    _invoke(ctx, "exec_cmd", cmd=_expand(ctx, command), cwd=_tmp_folder(ctx))


@when(parsers.parse('the tool exec_cmd is called with command {command} and parameter {param} set to {value}'))
def call_exec_cmd_with_parameter(ctx, command, param, value):
    """A command plus one stringified control argument such as timeout."""
    _invoke(
        ctx,
        "exec_cmd",
        cmd=_expand(ctx, command),
        cwd=_tmp_folder(ctx),
        **{param: _expand(ctx, value)},
    )


@when(parsers.parse('the tool exec_readonly is called with command {command} and parameter {param} set to {value}'))
def call_exec_readonly_with_parameter(ctx, command, param, value):
    """A read-only git command plus one stringified control argument."""
    _invoke(
        ctx,
        "exec_readonly",
        cmd=_expand(ctx, command),
        cwd=PROJECT_WORKSPACE,
        **{param: _expand(ctx, value)},
    )


@when(parsers.parse('the tool read_file is called on the test file with parameter {param} set to {value}'))
def call_read_file_single(ctx, param, value):
    """One stringified byte-offset argument against the active fixture."""
    _invoke(ctx, "read_file", file_path=ctx["files"]["active"], **{param: _expand(ctx, value)})


@when(parsers.parse('the tool read_file is called on the test file with parameters seek set to {seek_value} and size set to {size_value}'))
def call_read_file_seek_size(ctx, seek_value, size_value):
    """Both byte-offset arguments arrive as text."""
    _invoke(
        ctx,
        "read_file",
        file_path=ctx["files"]["active"],
        seek=_expand(ctx, seek_value),
        size=_expand(ctx, size_value),
    )


@when(parsers.parse('the tool write_file is called on the test file with content {content} and parameter {param} set to {value}'))
def call_write_file_single(ctx, content, param, value):
    """One stringified write-mode argument against the active fixture."""
    _invoke(
        ctx,
        "write_file",
        file_path=ctx["files"]["active"],
        content=content,
        **{param: _expand(ctx, value)},
    )


@when(parsers.parse('the tool write_file is called on the test file with content {content} and parameters seek set to {seek_value} and to_insert set to {to_insert_value}'))
def call_write_file_seek_insert(ctx, content, seek_value, to_insert_value):
    """Both write-mode arguments arrive as text."""
    _invoke(
        ctx,
        "write_file",
        file_path=ctx["files"]["active"],
        content=content,
        seek=_expand(ctx, seek_value),
        to_insert=_expand(ctx, to_insert_value),
    )


@when(parsers.parse('the tool insert_content_to_file is called on the test file with content {content} and parameter {param} set to {value}'))
def call_insert_content(ctx, content, param, value):
    """One stringified line number for the insert operation."""
    _invoke(
        ctx,
        "insert_content_to_file",
        file_path=ctx["files"]["active"],
        content=content,
        **{param: _expand(ctx, value)},
    )


@when(parsers.parse('the tool read_file_around_line is called on the test file with parameters line_number set to {line_value} and context_num set to {context_value}'))
def call_around_line(ctx, line_value, context_value):
    """Both line arguments arrive as text."""
    _invoke(
        ctx,
        "read_file_around_line",
        file_path=ctx["files"]["active"],
        line_number=_expand(ctx, line_value),
        context_num=_expand(ctx, context_value),
    )


@when(parsers.parse('the tool read_file_lines is called on the test file with parameters start_num set to {start_value} and end_num set to {end_value}'))
def call_read_file_lines(ctx, start_value, end_value):
    """Both range arguments arrive as text."""
    _invoke(
        ctx,
        "read_file_lines",
        file_path=ctx["files"]["active"],
        start_num=_expand(ctx, start_value),
        end_num=_expand(ctx, end_value),
    )


@when(parsers.parse('the tool read_file_with_context is called on the test file with pattern {pattern} and parameter {param} set to {value}'))
def call_with_context_single(ctx, pattern, param, value):
    """One stringified search option."""
    _invoke(
        ctx,
        "read_file_with_context",
        file_path=ctx["files"]["active"],
        pattern=pattern,
        **{param: _expand(ctx, value)},
    )


@when(parsers.parse('the tool read_file_with_context is called on the test file with pattern {pattern} and parameters {first_param} set to {first_value} and {second_param} set to {second_value}'))
def call_with_context_two(ctx, pattern, first_param, first_value, second_param, second_value):
    """Two stringified search options."""
    _invoke(
        ctx,
        "read_file_with_context",
        file_path=ctx["files"]["active"],
        pattern=pattern,
        **{
            first_param: _expand(ctx, first_value),
            second_param: _expand(ctx, second_value),
        },
    )


@when(parsers.parse('the tool overwrite_lines_in_file is called on the numbered test file with content {content} and parameters start_num set to {start_value} and end_num set to {end_value}'))
def call_overwrite_block(ctx, content, start_value, end_value):
    """A code-block replacement whose line numbers arrive as text."""
    _invoke(
        ctx,
        "overwrite_lines_in_file",
        file_path=ctx["files"].get("numbered") or ctx["files"]["active"],
        content=content,
        start_num=_expand(ctx, start_value),
        end_num=_expand(ctx, end_value),
    )


# --------------------------------------------------------------------------- then


@then('the tool returns a machine-readable parameter error')
def parameter_error(ctx):
    """A bad argument must be reported as invalid_request, never as a business state."""
    response = ctx["response"]
    assert response["kind"] == "dict", f"expected a dict, got {response}"
    assert response["status"] == "invalid_request", f"unexpected status: {response}"
    assert response["reason"], f"missing reason: {response}"
    assert "unavailable" not in response["text"], f"business status leaked: {response}"
    assert "invalid literal for int()" not in response["text"], f"raw exception leaked: {response}"
    assert "Traceback" not in response["text"], f"raw exception leaked: {response}"


@then(parsers.parse('the parameter error names the {param} parameter'))
def error_names_parameter(ctx, param):
    """The reason must tell the model which argument was rejected."""
    response = ctx["response"]
    reason = response.get("reason") or response.get("text", "")
    assert param in reason, f"{param!r} not mentioned in {reason!r}"


@then('the tool call is accepted and produces a result')
def call_accepted(ctx):
    """A coercible argument must reach normal tool execution."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    assert response.get("status") != "invalid_request", f"unexpected parameter error: {response}"


@then(parsers.parse('the tool output contains {expected}'))
def output_contains(ctx, expected):
    """The tool produced real content, proving the coerced value was used."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    assert expected in response["text"], f"{expected!r} missing from {response['text'][:200]!r}"


@then(parsers.parse('the command succeeds and prints {expected}'))
def command_succeeds(ctx, expected):
    """The shell command ran with the coerced control arguments."""
    response = ctx["response"]
    assert response["kind"] == "command", f"expected command result, got {response}"
    assert response["code"] == 0, f"non-zero exit: {response}"
    assert expected in response["stdout"], f"{expected!r} missing from {response['stdout']!r}"


@then(parsers.parse('the tool reports a business problem instead of a parameter error'))
def business_problem(ctx):
    """A finite but out-of-range value is a domain answer, not a bad argument."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    assert response.get("status") != "invalid_request", f"misclassified as parameter error: {response}"


@then(parsers.parse('the test file still contains {expected}'))
def file_unchanged(ctx, expected):
    """A rejected call must not touch the file."""
    content = read_text(ctx["files"]["active"])
    assert content == expected, f"file was modified: {content!r}"


@then(parsers.parse('the test file now contains {expected}'))
def file_contains(ctx, expected):
    """An accepted call must have written the requested content."""
    content = read_text(ctx["files"]["active"])
    assert expected in content, f"{expected!r} missing from {content!r}"


@then(parsers.parse('the numbered test file now contains {expected}'))
def numbered_file_contains(ctx, expected):
    """The replacement landed in the multi-line fixture."""
    content = read_text(ctx["files"]["numbered"])
    assert expected in content, f"{expected!r} missing from {content!r}"


@then('the tool response carries no raw conversion exception')
def no_raw_exception(ctx):
    """Reverse guard: the model never sees a bare Python conversion message."""
    response = ctx["response"]
    text = response.get("text", "")
    assert "invalid literal for int()" not in text, f"raw exception leaked: {text[:200]!r}"
    assert "must be a string" not in text, f"raw exception leaked: {text[:200]!r}"
    assert response.get("status") != "unavailable", f"business status used: {response}"


@then('the tool reports a parameter error inside its text result')
def parameter_error_in_text(ctx):
    """Some tools answer with plain text; the parameter status must still be readable."""
    response = ctx["response"]
    assert response["kind"] == "text", f"expected a text answer, got {response}"
    assert "invalid_request" in response["text"], f"status missing: {response['text'][:200]!r}"
    assert "unavailable" not in response["text"], f"business status leaked: {response}"
    assert "invalid literal for int()" not in response["text"], f"raw exception leaked: {response}"


@then(parsers.parse('the tool raises {exception} instead of reporting a parameter error'))
def tool_raises(ctx, exception):
    """Pins a known defect: the argument escapes as an exception (wip scenarios)."""
    response = ctx["response"]
    assert response["kind"] == "raised", f"expected a raise, got {response}"
    assert response["exception"] == exception, f"unexpected exception: {response}"
