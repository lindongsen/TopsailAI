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
from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.temp_storage import BDDTempStorage
from tests.bdd.tool_param_harness import (
    call_tool,
    read_raw,
    read_text,
    resolve_value,
    write_sample_file,
    write_short_file,
)

logger = logging.getLogger("tests.bdd.tool_param")

ALPHA_TEXT = "ABCDEFGHIJ"


@pytest.fixture
def ctx(bdd_temp_storage: BDDTempStorage):
    """Keep per-scenario state backed by owned workspace temporary storage."""
    return {
        "files": {},
        "args": {},
        "response": None,
        "temp_storage": bdd_temp_storage,
    }


_ESCAPES = {"r": "\r", "n": "\n", "t": "\t", "\\": "\\"}


def _decode_escapes(text: str) -> str:
    """Decode the small escape grammar used by raw-content Examples cells.

    ``unicode_escape`` is deliberately not used: it mangles non-ASCII text and
    would corrupt a CJK fixture. Only the escapes a fixture actually needs are
    recognised, and an unknown escape is kept verbatim so a typo stays visible
    instead of silently disappearing.
    """
    result: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\" or index + 1 >= len(text):
            result.append(char)
            index += 1
            continue
        marker = text[index + 1]
        if marker == "x" and index + 4 <= len(text):
            try:
                result.append(chr(int(text[index + 2:index + 4], 16)))
                index += 4
                continue
            except ValueError:
                pass
        if marker in _ESCAPES:
            result.append(_ESCAPES[marker])
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


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
    if value.startswith("esc:"):
        return _decode_escapes(value[len("esc:"):])
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
    """Return the lazily created scenario-owned temporary directory."""
    folder = ctx["files"].get("folder")
    if not folder:
        folder = str(ctx["temp_storage"].create_directory("topsailai-bdd-param-"))
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


@given(parsers.parse('a parameter test file named {name} with raw content {raw}'))
def raw_content_file(ctx, name, raw):
    """Create a fixture from an escaped literal so its endings stay exact.

    The content is written with ``newline=""`` so a ``\\r\\n`` reaches the file
    unchanged; a default ``open`` would translate it and the fixture itself
    would already be wrong before the tool under test ran.
    """
    path = os.path.join(_tmp_folder(ctx), name)
    with open(path, "w", encoding="utf-8", newline="") as handler:
        handler.write(_expand(ctx, raw))
    ctx["files"]["active"] = path
    ctx["files"]["numbered"] = path


@given(parsers.parse('a parameter test file named {name} with raw content {raw} and a second file named {second_name} with raw content {second_raw}'))
def raw_content_pair(ctx, name, raw, second_name, second_raw):
    """Create two fixtures whose endings must stay exact for a diff comparison.

    Both files are written with ``newline=""`` so a ``\\r\\n`` reaches the file
    unchanged. A default ``open`` would translate it, and a scenario that
    compares line endings would then compare two already-identical files.
    """
    folder = _tmp_folder(ctx)
    first_path = os.path.join(folder, name)
    second_path = os.path.join(folder, second_name)
    with open(first_path, "w", encoding="utf-8", newline="") as handler:
        handler.write(_expand(ctx, raw))
    with open(second_path, "w", encoding="utf-8", newline="") as handler:
        handler.write(_expand(ctx, second_raw))
    ctx["files"]["active"] = first_path
    ctx["files"]["numbered"] = first_path
    ctx["files"]["second"] = second_path


@given(parsers.parse('a parameter test file whose name is {name} with raw content {raw}'))
def raw_content_file_with_escaped_name(ctx, name, raw):
    """Create a fixture whose *name* also needs escape decoding.

    A path is not a trusted string: it can contain a newline, and the diff header
    prints the path verbatim. This fixture exists so a scenario can prove that a
    hostile path cannot forge a section boundary in the tool output.
    """
    path = os.path.join(_tmp_folder(ctx), _expand(ctx, name))
    with open(path, "w", encoding="utf-8", newline="") as handler:
        handler.write(_expand(ctx, raw))
    ctx["files"]["active"] = path
    ctx["files"]["numbered"] = path


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


@when('the tool read_file_lines is called on the test file without end_num')
def call_read_file_lines_without_end_num(ctx):
    """An LLM omits end_num entirely, which must read the whole file."""
    _invoke(ctx, "read_file_lines", file_path=ctx["files"]["active"])


@when(parsers.parse('the tool read_file_lines is called on the test file with start_num set to {start_value} only'))
def call_read_file_lines_without_end_num_with_start(ctx, start_value):
    """An LLM sends only start_num, which must read through the end."""
    _invoke(
        ctx,
        "read_file_lines",
        file_path=ctx["files"]["active"],
        start_num=_expand(ctx, start_value),
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
        content=_expand(ctx, content),
        start_num=_expand(ctx, start_value),
        end_num=_expand(ctx, end_value),
    )


@when(parsers.parse('the tool overwrite_lines_in_file is called on the numbered test file with a two-line content and parameters start_num set to {start_value} and end_num set to {end_value}'))
def call_overwrite_block_two_lines(ctx, start_value, end_value):
    """A replacement that adds a line, so the range end must be recomputed."""
    _invoke(
        ctx,
        "overwrite_lines_in_file",
        file_path=ctx["files"].get("numbered") or ctx["files"]["active"],
        content="FIRST\nSECOND\n",
        start_num=_expand(ctx, start_value),
        end_num=_expand(ctx, end_value),
    )


@when(parsers.parse('the tool overwrite_lines_in_file is called on the numbered test file with empty content and parameters start_num set to {start_value} and end_num set to {end_value}'))
def call_overwrite_block_empty(ctx, start_value, end_value):
    """An empty replacement deletes the whole range, so no line survives."""
    _invoke(
        ctx,
        "overwrite_lines_in_file",
        file_path=ctx["files"].get("numbered") or ctx["files"]["active"],
        content="",
        start_num=_expand(ctx, start_value),
        end_num=_expand(ctx, end_value),
    )


@when(parsers.parse('the tool replace_lines_in_file is called on the numbered test file with line {line_number} set to {content}'))
def call_replace_lines(ctx, line_number, content):
    """A single-line replacement through the line-oriented write tool."""
    _invoke(
        ctx,
        "replace_lines_in_file",
        file_path=ctx["files"].get("numbered") or ctx["files"]["active"],
        lines=[(int(_expand(ctx, line_number)), _expand(ctx, content))],
    )


@when(parsers.parse('the tool replace_lines_in_file is called on the numbered test file with line {line_number} set to {content} with a trailing newline'))
def call_replace_lines_with_newline(ctx, line_number, content):
    """A single-line replacement whose content already carries an LF ending."""
    _invoke(
        ctx,
        "replace_lines_in_file",
        file_path=ctx["files"].get("numbered") or ctx["files"]["active"],
        lines=[(int(_expand(ctx, line_number)), _expand(ctx, content) + "\n")],
    )


@when(parsers.parse('the tool replace_lines_in_file is called on the numbered test file with raw content {content} on line {line_number}'))
def call_replace_lines_raw(ctx, content, line_number):
    """A single-line replacement whose content is given as an escaped literal.

    The wording deliberately puts ``raw content`` before ``on line`` so the
    generic ``set to {content}`` step cannot match this text first and swallow
    the ``esc:`` prefix as literal content.
    """
    _invoke(
        ctx,
        "replace_lines_in_file",
        file_path=ctx["files"].get("numbered") or ctx["files"]["active"],
        lines=[(int(_expand(ctx, line_number)), _expand(ctx, content))],
    )


@when(parsers.parse('the tool insert_content_to_file is called on the numbered test file with content {content} and parameter line_num set to {line_number}'))
def call_insert_numbered(ctx, content, line_number):
    """Insert into the numbered fixture so its raw endings can be asserted.

    The wording names ``the numbered test file`` so the generic
    ``on the test file`` step cannot match this text first.
    """
    _invoke(
        ctx,
        "insert_content_to_file",
        file_path=ctx["files"].get("numbered") or ctx["files"]["active"],
        content=_expand(ctx, content),
        line_num=_expand(ctx, line_number),
    )


@when(parsers.parse('the tool insert_content_to_file is called on the numbered test file with raw content {content} and parameter line_num set to {line_number}'))
def call_insert_numbered_raw(ctx, content, line_number):
    """Insert content given as an escaped literal, so its ending stays exact."""
    _invoke(
        ctx,
        "insert_content_to_file",
        file_path=ctx["files"].get("numbered") or ctx["files"]["active"],
        content=_expand(ctx, content),
        line_num=_expand(ctx, line_number),
    )


@when('the tool compare_files is called on the numbered test file and the second test file')
def call_compare_files(ctx):
    """Compare the two fixtures byte for byte, without newline translation."""
    _invoke(
        ctx,
        "compare_files",
        file1_path=ctx["files"].get("numbered") or ctx["files"]["active"],
        file2_path=ctx["files"]["second"],
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


@then(parsers.parse('the tool output does not contain {unexpected}'))
def output_does_not_contain(ctx, unexpected):
    """A bounded range must not leak lines outside the requested window."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    assert unexpected not in response["text"], (
        f"{unexpected!r} unexpectedly present in {response['text'][:200]!r}"
    )


@then(parsers.parse('the tool output starts with {expected}'))
def output_starts_with(ctx, expected):
    """The first section must be labelled, so no section is an unlabelled block."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    assert response["text"].startswith(expected), (
        f"output does not start with {expected!r}: {response['text'][:200]!r}"
    )


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


@then(parsers.parse('the numbered test file no longer contains {absent}'))
def numbered_file_absent(ctx, absent):
    """A destructive range must actually remove the tail it claims to replace."""
    content = read_text(ctx["files"]["numbered"])
    assert absent not in content, f"{absent!r} still present in {content!r}"

@then(parsers.parse('the numbered test file raw content is {expected}'))
def numbered_file_raw_equals(ctx, expected):
    """Compare the fixture byte for byte, without newline translation.

    ``read_text`` would translate ``\\r\\n`` to ``\\n`` and make a line-ending
    regression invisible, so this step reads with ``newline=""``.
    """
    content = read_raw(ctx["files"]["numbered"])
    wanted = _expand(ctx, expected)
    assert content == wanted, f"expected {wanted!r}, got {content!r}"


@then(parsers.parse('the numbered test file raw content still starts with {expected}'))
def numbered_file_raw_starts_with(ctx, expected):
    """The untouched prefix must keep its original line endings."""
    content = read_raw(ctx["files"]["numbered"])
    wanted = _expand(ctx, expected)
    assert content.startswith(wanted), f"{wanted!r} missing from {content!r}"


@then(parsers.parse('the numbered test file raw content still ends with {expected}'))
def numbered_file_raw_ends_with(ctx, expected):
    """The untouched suffix must keep its original line endings."""
    content = read_raw(ctx["files"]["numbered"])
    wanted = _expand(ctx, expected)
    assert content.endswith(wanted), f"{wanted!r} missing from {content!r}"


@then('the numbered test file raw content contains no carriage return')
def numbered_file_raw_has_no_cr(ctx):
    """A stray carriage return is the fingerprint of a half-stripped ending."""
    content = read_raw(ctx["files"]["numbered"])
    assert "\r" not in content, f"stray carriage return in {content!r}"



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


@then('the tool output is empty')
def output_is_empty(ctx):
    """An empty diff is the only correct answer for two identical files."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    assert response["text"] == "", f"expected an empty diff, got {response['text'][:200]!r}"


@then(parsers.parse('the tool output has a removed line {text}'))
def output_has_removed_line(ctx, text):
    """Match a whole diff line, so a path containing the text cannot satisfy it.

    A substring check on ``-a`` would also match a file path such as
    ``/tmp/...-abc``, so the assertion anchors on the line boundaries.
    """
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    wanted = f"\n-{text}\n"
    body = "\n" + response["text"]
    assert wanted in body, f"no removed line {text!r} in {response['text'][:300]!r}"


@then(parsers.parse('the tool output has an added line {text}'))
def output_has_added_line(ctx, text):
    """Match a whole added diff line, anchored on the line boundaries."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    wanted = f"\n+{text}\n"
    body = "\n" + response["text"]
    assert wanted in body, f"no added line {text!r} in {response['text'][:300]!r}"


@then(parsers.parse('the tool output has no removed line {text}'))
def output_has_no_removed_line(ctx, text):
    """An untouched line must appear as context, never as a removal."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    unwanted = f"\n-{text}\n"
    body = "\n" + response["text"]
    assert unwanted not in body, f"unexpected removed line {text!r} in {response['text'][:300]!r}"


def _parse_fenced_sections(text: str) -> list[tuple[str, str]]:
    """Split tool output into ``(title, body)`` pairs using the fences.

    A heading string cannot be used as a boundary: the diff body can contain the
    same text, because a file whose own content holds a heading line, or a path
    containing a newline, injects lines the tool never wrote. The fence is the
    boundary, so this parser fails loudly when a section is not fenced or when a
    body line closes its own fence.
    """
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("## "):
            index += 1
            continue
        title = lines[index]
        index += 1
        assert index < len(lines), f"section {title!r} has no fence"
        fence = lines[index]
        assert fence and set(fence) == {"`"}, (
            f"section {title!r} is not followed by a fence: {fence!r}"
        )
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index] != fence:
            body.append(lines[index])
            index += 1
        assert index < len(lines), f"section {title!r} has no closing fence"
        index += 1
        sections.append((title, "\n".join(body)))
    return sections


@then(parsers.parse('the tool output has exactly {count} fenced sections'))
def output_has_fenced_section_count(ctx, count):
    """Content or a path must not be able to add a section to the output."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    sections = _parse_fenced_sections(response["text"])
    titles = [title for title, _ in sections]
    assert len(sections) == int(count), (
        f"expected {count} fenced sections, got {len(sections)}: {titles}"
    )


@then(parsers.parse('the section titled {title} contains {text}'))
def section_contains(ctx, title, text):
    """The injected text must sit inside the section body, not outside it."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    matches = [body for name, body in _parse_fenced_sections(response["text"]) if name.startswith(title)]
    assert len(matches) == 1, f"expected one {title!r} section, got {len(matches)}"
    assert text in matches[0], f"{text!r} missing from the {title!r} body: {matches[0][:300]!r}"
