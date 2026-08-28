"""Step definitions for the human-decision reference suite and the str-only guard suite.

Both suites pin the same project rule ("tool parameters must assume string-typed LLM
output", see ``tools/readme.md``):

- ``human_tool.ask_decision`` is the designated reference implementation, so its
  coercion contract is locked here against future refactors.
- The str-only tools (memory, story, ctx, time, multimodal, sub-agent, file size)
  declare plain strings and therefore need no coercion, but they must not answer a
  badly typed argument with a raw Python exception, because ``exec_tool_func``
  stringifies exceptions straight back into the model's observation.

Step-text uniqueness contract
-----------------------------
pytest-bdd silently lets two step definitions with the same parsed pattern override
each other, and a single-field ``parsers.parse`` pattern greedily swallows the tail of
a longer step. Every step here therefore carries the ``human decision`` or
``guard tool`` marker, mirrors the ``parameter``/``parameters`` wording of the existing
modules, and never defines a three-field variant a two-field pattern could match.

Safety contract
---------------
No scenario can block on input: every ``ask_decision`` call runs in a daemon worker
thread with a hard ceiling, and no scenario reaches a real LLM, a real sub-agent, the
real memory workspace, or the network.

Value tokens understood in Examples tables
------------------------------------------
- ``empty``      -> the empty string
- ``null``       -> ``None``
- ``<sp>``       -> one literal space (Gherkin trims cell whitespace)
- ``int:5`` / ``float:2.5`` / ``bool:True`` / ``raw:[..]`` -> native Python value
- ``{mem}`` / ``{file}`` -> scenario fixture paths
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

logger = logging.getLogger("tests.bdd.tool_param.human_guard")

from tests.bdd.tool_param_harness import (  # noqa: E402
    HUMAN_BASE_QUESTION,
    MULTIMODAL_ANSWER,
    SUBAGENT_ANSWER,
    call_guard_tool,
    call_human_tool,
    expand_token,
    write_guard_workspace,
)

# Text markers that must never reach the model as the whole tool answer.
RAW_EXCEPTION_MARKERS = (
    "Traceback",
    "TypeError:",
    "ValueError:",
    "AttributeError:",
    "FileNotFoundError:",
    "OSError:",
    "AssertionError:",
    "invalid literal for int()",
)

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


@pytest.fixture
def human_guard_ctx():
    """Per-scenario state plus a sandbox workspace removed after the scenario."""
    context: dict[str, Any] = {"files": {}, "response": None}
    yield context
    folder = context["files"].get("folder")
    if folder and os.path.isdir(folder):
        shutil.rmtree(folder)
        logger.info("removed human/guard parameter test folder: [%s]", folder)


def _tmp_folder(ctx) -> str:
    """Return (creating on first use) the scenario-scoped sandbox workspace."""
    folder = ctx["files"].get("folder")
    if not folder:
        folder = tempfile.mkdtemp(prefix="topsailai-bdd-humanguard-")
        ctx["files"]["folder"] = folder
    return folder


def _placeholders(ctx) -> dict:
    """Fixture substitutions available inside Examples tables."""
    return {
        "{mem}": _tmp_folder(ctx),
        "{file}": ctx["files"].get("file", ""),
    }


def _expand(ctx, token: str) -> Any:
    """Resolve one Examples cell into the value an LLM would actually send."""
    return expand_token(ctx, token, _placeholders(ctx))


def _answer_text(response: dict) -> str:
    """Return the exact text a model would receive for this tool answer."""
    return response.get("text", "")


# --------------------------------------------------------------------------- given


@given(parsers.parse('a memory titled {title} holding the content {content}'))
def existing_memory(ctx, title, content):
    """One memory already exists inside the scenario sandbox workspace."""
    ctx["response"] = call_guard_tool(
        "write_memory",
        _tmp_folder(ctx),
        title=_expand(ctx, title),
        content=_expand(ctx, content),
    )
    assert ctx["response"]["kind"] != "raised", f"memory fixture failed: {ctx['response']}"


@given(parsers.parse('a guard file named {name} holding {size} bytes'))
def guard_file(ctx, name, size):
    """A real file of an exact size backs the file-size guard scenarios."""
    path = os.path.join(_tmp_folder(ctx), name)
    with open(path, "wb") as handler:
        handler.write(b"x" * int(size))
    ctx["files"]["file"] = path


@given(parsers.parse('a guard workspace folder'))
def guard_workspace(ctx):
    """The sandbox workspace exists before the scenario writes anything."""
    write_guard_workspace(_tmp_folder(ctx))
    assert os.path.isdir(os.path.join(_tmp_folder(ctx), "story"))


# --------------------------------------------------------------------------- when


def _human_kwargs(ctx, supplied: dict) -> dict:
    """Add the default question unless the scenario supplies its own.

    A plain ``question=...`` keyword alongside ``**{param: value}`` would either
    override the value under test or raise on the duplicate keyword, so the default is
    merged only when the scenario did not name ``question``.
    """
    arguments = {"question": HUMAN_BASE_QUESTION}
    arguments.update(supplied)
    return arguments


@when(parsers.parse('the human decision tool is asked with parameter {param} set to {value}'))
def ask_human_with_parameter(ctx, param, value):
    """The model sends one stringified argument to the reference implementation."""
    ctx["response"] = call_human_tool(
        **_human_kwargs(ctx, {param: _expand(ctx, value)})
    )


@when(parsers.parse('the human decision tool is asked with parameters {first_param} set to {first_value} and {second_param} set to {second_value}'))
def ask_human_with_two_parameters(ctx, first_param, first_value, second_param, second_value):
    """Two stringified arguments arrive together, as a real tool call would send them."""
    ctx["response"] = call_human_tool(**_human_kwargs(
        ctx,
        {first_param: _expand(ctx, first_value), second_param: _expand(ctx, second_value)},
    ))

@when(parsers.parse('the human decision tool is asked with a scripted answer {answer} and parameter {param} set to {value}'))
def ask_human_with_scripted_answer(ctx, answer, param, value):
    """An operator is reachable and replies with ``answer`` to the rendered prompt."""
    ctx["response"] = call_human_tool(
        answer=_expand(ctx, answer),
        **_human_kwargs(ctx, {param: _expand(ctx, value)}),
    )


@when(parsers.parse('the human decision tool is asked with a scripted answer {answer} and parameters {first_param} set to {first_value} and {second_param} set to {second_value}'))
def ask_human_with_scripted_answer_and_two_parameters(ctx, answer, first_param, first_value, second_param, second_value):
    """An operator replies while two stringified arguments shape the request."""
    ctx["response"] = call_human_tool(
        answer=_expand(ctx, answer),
        **_human_kwargs(
            ctx,
            {first_param: _expand(ctx, first_value), second_param: _expand(ctx, second_value)},
        ),
    )



@when(parsers.parse('the guard tool {tool} is called with parameter {param} set to {value}'))
def call_guard_with_parameter(ctx, tool, param, value):
    """One str-only tool receives one argument, possibly badly typed."""
    arguments = _guard_arguments(ctx, tool)
    arguments[param] = _expand(ctx, value)
    ctx["response"] = call_guard_tool(tool, _tmp_folder(ctx), **arguments)


@given(parsers.parse('the guard tool {tool} is called with parameters {first_param} set to {first_value} and {second_param} set to {second_value}'))
@when(parsers.parse('the guard tool {tool} is called with parameters {first_param} set to {first_value} and {second_param} set to {second_value}'))
def call_guard_with_two_parameters(ctx, tool, first_param, first_value, second_param, second_value):
    """One str-only tool receives two arguments, possibly badly typed."""
    arguments = _guard_arguments(ctx, tool)
    arguments[first_param] = _expand(ctx, first_value)
    arguments[second_param] = _expand(ctx, second_value)
    ctx["response"] = call_guard_tool(tool, _tmp_folder(ctx), **arguments)


@when(parsers.parse('the guard tool {tool} is called without any argument'))
def call_guard_without_arguments(ctx, tool):
    """A zero-argument tool must still answer normally."""
    ctx["response"] = call_guard_tool(tool, _tmp_folder(ctx))


@when(parsers.parse('the guard tool retrieve_stories searches for the keywords {keywords}'))
def call_guard_retrieve(ctx, keywords):
    """Keyword retrieval receives its pipe-separated keyword string."""
    ctx["response"] = call_guard_tool(
        "retrieve_stories", _tmp_folder(ctx), keywords=_expand(ctx, keywords)
    )


def _guard_arguments(ctx, tool: str) -> dict:
    """Build the well-formed arguments of one str-only tool call."""
    if tool == "write_memory":
        return {"title": "guard memory", "content": "hello memory"}
    if tool in ("read_memory", "delete_memory"):
        return {"title": "guard memory"}
    if tool == "write_story":
        return {"story_id": "guard-story", "story_content": "story body"}
    if tool in ("read_story", "delete_story"):
        return {"story_id": "guard-story"}
    if tool in ("list_stories", "list_memories"):
        return {}
    if tool == "retrieve_stories":
        return {"keywords": "guard"}
    if tool == "retrieve_msg":
        return {"msg_id": "msg-xyz"}
    if tool in ("get_local_date", "get_local_time"):
        return {}
    if tool == "recognize_image":
        return {"image_source": os.path.join(_tmp_folder(ctx), "pic.png"), "prompt": "describe", "model_name": "mock-model"}
    if tool == "recognize_voice":
        return {"audio_source": os.path.join(_tmp_folder(ctx), "clip.wav"), "prompt": "transcribe", "model_name": "mock-model"}
    if tool == "recognize_video":
        return {"video_source": os.path.join(_tmp_folder(ctx), "clip.mp4"), "prompt": "describe", "model_name": "mock-model"}
    if tool == "call_assistant":
        return {"task": "say hi"}
    if tool == "get_file_size":
        return {"file_path": ctx["files"].get("file", "")}
    raise AssertionError(f"unknown guard tool: {tool}")


# --------------------------------------------------------------------------- then: ask_decision


@then(parsers.parse('the human decision answer is a parameter error naming {param}'))
def human_parameter_error(ctx, param):
    """A bad argument is a parameter error, never an environment status."""
    response = ctx["response"]
    assert response["kind"] == "dict", f"expected a dict, got {response}"
    assert response["status"] == "invalid_request", f"unexpected status: {response}"
    assert response["reason"] == f"invalid_{param.strip()}", f"unexpected reason: {response}"
    assert "unavailable" not in _answer_text(response), f"environment status leaked: {response}"


@then(parsers.parse('the human decision answer is the status {status}'))
def human_status(ctx, status):
    """The whole status vocabulary is pinned, one literal at a time."""
    response = ctx["response"]
    assert response["kind"] == "dict", f"expected a dict, got {response}"
    assert response["status"] == status.strip(), f"unexpected status: {response}"


@then('the human decision answer is unavailable without rendering any prompt')
def human_unavailable_without_prompt(ctx):
    """A well-formed request in a non-interactive process degrades without prompting."""
    response = ctx["response"]
    assert response["kind"] == "dict", f"expected a dict, got {response}"
    assert response["status"] == "unavailable", f"unexpected status: {response}"
    assert response["prompts"] == [], f"a prompt was rendered: {response['prompts']}"


@then('the human decision answer is answered from the scripted reply')
def human_answered(ctx):
    """The scripted operator reply was parsed and returned."""
    response = ctx["response"]
    assert response["kind"] == "dict", f"expected a dict, got {response}"
    assert response["status"] == "answered", f"unexpected status: {response}"
    assert response["prompts"], "no prompt was rendered at all"


@then(parsers.parse('the human decision answer equals {expected}'))
def human_answer_equals(ctx, expected):
    """The ``answer`` field carries exactly the expected text."""
    response = ctx["response"]
    assert response["kind"] == "dict", f"expected a dict, got {response}"
    assert response.get("answer") == _expand(ctx, expected), f"unexpected answer: {response}"


@then(parsers.parse('the human decision answer selected option index {index}'))
def human_option_index(ctx, index):
    """The ``option_index`` field reports the chosen position."""
    response = ctx["response"]
    assert response.get("option_index") == int(index), f"unexpected index: {response}"


@then('the human decision answer keeps the default fallback')
def human_keeps_default_fallback(ctx):
    """A rejected request must still hand the caller's ``default`` back."""
    response = ctx["response"]
    assert response.get("answer") == "fallback", f"default lost: {response}"


@then('the human decision answer carries no raw exception text')
def human_no_raw_exception(ctx):
    """Reverse guard: no bare Python exception ever reaches the model."""
    response = ctx["response"]
    assert response["kind"] != "hang", f"call blocked: {response}"
    assert response["kind"] != "raised", f"tool raised: {response}"
    text = _answer_text(response)
    for marker in RAW_EXCEPTION_MARKERS:
        assert marker not in text, f"raw exception leaked: {text[:200]!r}"


@then('the human decision answer is not answered from an unlisted reply')
def human_not_answered_from_unlisted_reply(ctx):
    """Desired contract: a reply outside the option list is not an answer.

    With free text disabled the caller explicitly restricted the answer space, so
    echoing the unlisted text back as ``answered`` would tell the model the
    restriction was satisfied.
    """
    response = ctx["response"]
    assert response["kind"] != "hang", f"call blocked: {response}"
    echoed = response["kind"] == "dict" and response.get("status") == "answered" and (
        response.get("answer") == "zzz"
    )
    assert not echoed, f"unlisted reply accepted as an answer: {response}"


@then('the human decision answer reports no timeout')
def human_no_timeout(ctx):
    """A converted timeout must never surface as a timeout status."""
    response = ctx["response"]
    assert response.get("status") != "timeout", f"unexpected timeout: {response}"


# --------------------------------------------------------------------------- then: guard tools


@then('the guard tool answer leaks no traceback text')
def guard_leaks_no_traceback(ctx):
    """Whatever the tool answers, a bare interpreter message must not be the answer.

    ``exec_tool_func`` stringifies an exception into the tool result, so the model
    receives ``str(exc)``; this step pins that text, not the internal control flow.
    """
    response = ctx["response"]
    assert response["kind"] != "hang", f"call blocked: {response}"
    text = _answer_text(response)
    assert text, f"empty answer: {response}"
    for marker in RAW_EXCEPTION_MARKERS:
        assert marker not in text, f"raw exception leaked: {text[:200]!r}"


@then('the guard tool answer is free of raw Python exception text')
def guard_free_of_exception(ctx):
    """Desired contract: the tool answers instead of raising."""
    response = ctx["response"]
    assert response["kind"] != "hang", f"call blocked: {response}"
    assert response["kind"] != "raised", (
        f"tool raised {response.get('exception')}: {response.get('text')!r}"
    )
    for marker in RAW_EXCEPTION_MARKERS:
        assert marker not in _answer_text(response), f"raw exception leaked: {response}"


@then('the guard tool answer is a machine-readable parameter error')
def guard_machine_readable_parameter_error(ctx):
    """A badly typed argument must be reported as ``invalid_request``."""
    response = ctx["response"]
    assert response["kind"] == "dict", f"expected a dict, got {response}"
    assert response["status"] == "invalid_request", f"unexpected status: {response}"
    assert response["reason"], f"missing reason: {response}"


@then('the guard tool answer does not reject the native string as a parameter error')
def guard_native_string_not_rejected(ctx):
    """JSON-looking text remains a string and must bypass the type guard."""
    response = ctx["response"]
    rejected = response.get("status") == "invalid_request"
    assert not rejected, f"native string was rejected: {response}"


@then('the guard tool answer does not report an unavailable environment')
def guard_no_unavailable_status(ctx):
    """``unavailable`` is reserved for a genuinely missing environment, not bad input."""
    response = ctx["response"]
    assert response.get("status") != "unavailable", f"status misused: {response}"


@then(parsers.parse('the guard tool answer is the string {expected}'))
def guard_answer_is_string(ctx, expected):
    """A plain string answer equals the expected text."""
    response = ctx["response"]
    assert response["kind"] == "text", f"expected a string, got {response}"
    assert response["text"] == _expand(ctx, expected), f"unexpected answer: {response['text']!r}"


@then(parsers.parse('the guard tool answer mentions {expected}'))
def guard_answer_mentions(ctx, expected):
    """A failure path must stay readable and mention what went wrong."""
    response = ctx["response"]
    assert _expand(ctx, expected) in _answer_text(response), f"missing in answer: {response}"


@then('the guard tool answer is an empty string')
def guard_answer_is_empty(ctx):
    """The documented short-circuit contract."""
    response = ctx["response"]
    assert response["kind"] == "text", f"expected a string, got {response}"
    assert response["text"] == "", f"expected an empty string: {response['text']!r}"


@then('the guard tool answer is None')
def guard_answer_is_none(ctx):
    """A missing record answers ``None`` rather than raising."""
    response = ctx["response"]
    assert response["kind"] == "value", f"expected None, got {response}"
    assert response["value"] is None, f"expected None, got {response}"


@then('the guard tool answer is a non-empty list')
def guard_answer_is_non_empty_list(ctx):
    """A listing answers with at least one entry."""
    response = ctx["response"]
    assert response["kind"] == "sequence", f"expected a list, got {response}"
    assert response["items"], f"expected a non-empty list: {response}"


@then('the guard tool answer is an empty list')
def guard_answer_is_empty_list(ctx):
    """A listing with nothing left answers with an empty list."""
    response = ctx["response"]
    assert response["kind"] == "sequence", f"expected a list, got {response}"
    assert response["items"] == [], f"expected an empty list: {response}"


@then(parsers.parse('the guard tool answer lists a record titled {expected}'))
def guard_answer_lists_record(ctx, expected):
    """A listing contains the record created by the scenario."""
    response = ctx["response"]
    assert response["kind"] == "sequence", f"expected a list, got {response}"
    wanted = _expand(ctx, expected)
    titles = []
    for item in response["items"]:
        titles.append(str(item.get("title")) if isinstance(item, dict) else str(item))
    assert any(t == wanted or t.endswith(wanted) or t.endswith(wanted + ".md") for t in titles), (
        f"{wanted!r} not listed in {titles!r}"
    )


@then(parsers.parse('the guard tool answer is the integer {expected}'))
def guard_answer_is_integer(ctx, expected):
    """A numeric answer equals the expected integer."""
    response = ctx["response"]
    assert response["kind"] == "value", f"expected an int, got {response}"
    assert response["value"] == int(expected), f"unexpected value: {response}"


@then('the guard tool answer is an integer')
def guard_answer_is_any_integer(ctx):
    """A timestamp-style answer stays an integer."""
    response = ctx["response"]
    assert response["kind"] == "value", f"expected an int, got {response}"
    assert isinstance(response["value"], int), f"not an int: {response}"


@then('the guard tool answer matches the ISO-8601 date pattern')
def guard_answer_is_iso_date(ctx):
    """A date answer is ISO-8601 formatted."""
    response = ctx["response"]
    assert response["kind"] == "text", f"expected a string, got {response}"
    assert ISO_DATE_RE.match(response["text"]), f"not ISO-8601: {response['text']!r}"


@then(parsers.parse('the guard tool answer escapes as the {exception} exception'))
def guard_answer_escapes(ctx, exception):
    """Pins a known defect: the badly typed argument escapes as an exception."""
    response = ctx["response"]
    assert response["kind"] == "raised", f"expected a raise, got {response}"
    assert response["exception"] == exception.strip(), f"unexpected exception: {response}"


@then('the guard tool answer is the mocked multimodal description')
def guard_answer_is_multimodal(ctx):
    """The multimodal tool used its mocked LLM layer and returned its description."""
    response = ctx["response"]
    assert response["kind"] == "text", f"expected a string, got {response}"
    assert response["text"] == MULTIMODAL_ANSWER, f"unexpected answer: {response['text']!r}"


@then('the guard tool answer is the mocked sub-agent answer')
def guard_answer_is_subagent(ctx):
    """The delegation tool used its mocked sub-agent and returned its answer."""
    response = ctx["response"]
    assert response["kind"] == "text", f"expected a string, got {response}"
    assert response["text"] == SUBAGENT_ANSWER, f"unexpected answer: {response['text']!r}"


@then(parsers.parse('the guard tool answer is a path holding {expected}'))
def guard_answer_is_path(ctx, expected):
    """A write operation answers with the file path it created."""
    response = ctx["response"]
    assert response["kind"] == "text", f"expected a path string, got {response}"
    assert _expand(ctx, expected) in response["text"], f"missing in path: {response['text']!r}"
    assert response["text"].startswith("/"), f"not an absolute path: {response['text']!r}"


@then(parsers.parse('the memory titled {title} no longer exists'))
def memory_gone(ctx, title):
    """The deleted memory can no longer be read back."""
    ctx["response"] = call_guard_tool("read_memory", _tmp_folder(ctx), title=_expand(ctx, title))
    response = ctx["response"]
    assert response["kind"] == "value" and response["value"] is None, f"still readable: {response}"


@then('the guard workspace holds no story record')
def guard_workspace_empty(ctx):
    """A rejected write must not leave a record behind."""
    story_folder = os.path.join(_tmp_folder(ctx), "story")
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(story_folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        found.extend(filenames)
    assert not found, f"unexpected records left: {found!r}"
