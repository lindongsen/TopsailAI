"""In-process call helpers for tool parameter-coercion behavior tests.

The tools under test are called directly (no CLI subprocess, no network), and every
return value is normalized into a small dictionary so that Gherkin steps can assert
on observable content instead of Python types.

Value tokens used by Gherkin Examples tables
--------------------------------------------
Gherkin table cells are always text, so a token grammar is needed to express the
values a real LLM might send:

- ``null``            -> ``None``
- ``int:5``           -> native ``int`` 5
- ``float:2.5``       -> native ``float`` 2.5
- ``bool:True``       -> native ``bool`` True
- ``raw:[1, 2]``      -> the JSON-decoded native container
- anything else       -> the literal string, quotes included in the message text
  (``" 1e2 "`` keeps its surrounding whitespace)
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

import topsailai
from topsailai.tools import cmd_tool, git_tool, file_tool
from topsailai.tools.file_tool_utils import file_read_line, file_write_code_block

# ``exec_cmd`` resolves its default working directory from the environment, which is
# empty under a bare pytest run; command scenarios therefore always pass an explicit
# cwd. The repository workspace is used for read-only git commands.
PROJECT_WORKSPACE = os.path.dirname(os.path.abspath(topsailai.__file__))

SAMPLE_LINE_COUNT = 20
SHORT_FILE_LINE_COUNT = 10


# Tool name -> callable. ``write_file`` intentionally points at the underlying
# implementation because the registered TOOLS entry maps the public name to
# ``write_file_simple``, which does not expose ``seek``/``to_insert`` at all.
TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "exec_cmd": cmd_tool.exec_cmd,
    "exec_readonly": git_tool.exec_readonly,
    "read_file": file_tool.read_file,
    "write_file": file_tool.write_file,
    "insert_content_to_file": file_tool.insert_content_to_file,
    "read_files": file_tool.read_files,
    "list_dirs": file_tool.list_dirs,
    "mkdirs": file_tool.mkdirs,
    "read_file_around_line": file_read_line.read_file_around_line,
    "read_file_lines": file_read_line.read_file_lines,
    "read_file_with_context": file_read_line.read_file_with_context,
    "overwrite_lines_in_file": file_write_code_block.overwrite_code_block,
}


def resolve_value(token: str) -> Any:
    """Translate one Examples-table token into the value an LLM would send."""
    if token == "null":
        return None
    if token.startswith("int:"):
        return int(token.split(":", 1)[1])
    if token.startswith("float:"):
        return float(token.split(":", 1)[1])
    if token.startswith("bool:"):
        return token.split(":", 1)[1].strip().lower() in ("true", "1")
    if token.startswith("raw:"):
        return json.loads(token.split(":", 1)[1])
    return token


def normalize_result(raw: Any) -> dict:
    """Normalize one tool return value into assertable content."""
    if isinstance(raw, dict):
        return {
            "kind": "dict",
            "status": raw.get("status"),
            "reason": raw.get("reason"),
            "keys": sorted(str(key) for key in raw),
            "text": str(raw),
        }
    if isinstance(raw, (tuple, list)):
        if len(raw) == 3 and isinstance(raw[0], int) and isinstance(raw[1], str):
            return {
                "kind": "command",
                "code": raw[0],
                "stdout": raw[1],
                "stderr": raw[2],
                "text": str(raw),
            }
        return {"kind": "sequence", "items": list(raw), "text": str(raw)}
    if isinstance(raw, str):
        return {"kind": "text", "text": raw}
    return {"kind": "value", "value": raw, "text": str(raw)}


def call_tool(tool_name: str, **kwargs: Any) -> dict:
    """Call one tool in-process and never let an exception escape to the scenario."""
    func = TOOL_FUNCS[tool_name]
    try:
        raw = func(**kwargs)
    except Exception as exc:  # noqa: BLE001 - the framework stringifies too
        return {
            "kind": "raised",
            "exception": type(exc).__name__,
            "text": str(exc),
            "status": None,
            "reason": None,
        }
    return normalize_result(raw)


def write_sample_file(folder: str, name: str = "sample.txt") -> str:
    """Create the standard 20-line fixture file and return its path."""
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handler:
        handler.write("".join(f"LINE{index:02d}\n" for index in range(1, SAMPLE_LINE_COUNT + 1)))
    return path


def write_short_file(folder: str, name: str = "short.txt") -> str:
    """Create the 10-line ``L1..L10`` fixture file and return its path."""
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handler:
        handler.write("".join(f"L{index}\n" for index in range(1, SHORT_FILE_LINE_COUNT + 1)))
    return path


def read_text(path: str) -> str:
    """Read one fixture file so scenarios can verify untouched content."""
    with open(path, "r", encoding="utf-8") as handler:
        return handler.read()


# --------------------------------------------------------------------------- remote tools
#
# Remote scenarios must never open a socket. The transport symbol of each remote
# tool is replaced by a recorder, which also makes it possible to assert that a
# rejected argument produced *zero* side effects.

from contextlib import ExitStack  # noqa: E402  (kept next to the helpers that use it)
from unittest.mock import MagicMock, patch  # noqa: E402

from topsailai.tools import sandbox_tool, skill_tool, ssh_tool  # noqa: E402

# RFC 5737 TEST-NET-1: guaranteed not to route, used for every remote host.
TEST_NET_HOST = "192.0.2.10"

# Value returned by every recorded transport call.
REMOTE_OK = (0, "REMOTE-OK", "")

# Skill script content used by the skill scenarios; harmless and offline.
SKILL_ECHO_BODY = "#!/bin/sh\necho skill-echo-ok\n"

REMOTE_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "call_sandbox": sandbox_tool.call_sandbox,
    "copy2sandbox": sandbox_tool.copy2sandbox,
    "list_sandbox": sandbox_tool.list_sandbox,
    "operate_ssh": ssh_tool.operate_ssh,
    "call_skill": skill_tool.call_skill,
}

# tool name -> [(module, attribute)] transport symbols to replace.
REMOTE_TRANSPORT: dict[str, list[tuple[Any, str]]] = {
    "call_sandbox": [(sandbox_tool, "exec_cmd_in_remote")],
    "copy2sandbox": [(sandbox_tool, "exec_cmd")],
    "list_sandbox": [],
    "operate_ssh": [(ssh_tool, "exec_cmd")],
    "call_skill": [(skill_tool, "exec_cmd")],
}


class TransportRecorder:
    """Record transport invocations and answer with a canned command result."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> tuple:
        self.calls.append((args, kwargs))
        return REMOTE_OK

    @property
    def count(self) -> int:
        return len(self.calls)

    def joined_command(self, index: int = 0) -> str:
        """Render one recorded command line as plain text for substring checks."""
        args = self.calls[index][0]
        parts: list[str] = []
        for arg in args:
            if isinstance(arg, (list, tuple)):
                parts.extend(str(item) for item in arg)
            else:
                parts.append(str(arg))
        return " ".join(parts)


def call_remote_tool(tool_name: str, **kwargs: Any) -> dict:
    """Call one remote tool with its transport mocked, then normalize the answer."""
    func = REMOTE_TOOL_FUNCS[tool_name]
    recorder = TransportRecorder()
    with ExitStack() as stack:
        for module, attribute in REMOTE_TRANSPORT[tool_name]:
            stack.enter_context(patch.object(module, attribute, side_effect=recorder))
        if tool_name == "call_skill":
            # Keep the recorded timeout deterministic instead of inheriting the
            # environment-configured skill timeout.
            stack.enter_context(
                patch.object(skill_tool, "get_call_skill_timeout", return_value=1)
            )
        try:
            raw = func(**kwargs)
        except Exception as exc:  # noqa: BLE001 - the framework stringifies too
            return {
                "kind": "raised",
                "exception": type(exc).__name__,
                "text": str(exc),
                "status": None,
                "reason": None,
                "transport_calls": recorder.count,
                "transport_command": recorder.joined_command() if recorder.count else "",
                "transport_kwargs": recorder.calls[0][1] if recorder.count else {},
            }
    result = normalize_result(raw)
    result["transport_calls"] = recorder.count
    result["transport_command"] = recorder.joined_command() if recorder.count else ""
    result["transport_kwargs"] = recorder.calls[0][1] if recorder.count else {}
    return result


def call_plain_tool(tool_name: str, **kwargs: Any) -> dict:
    """Call one remote tool for real (used only for offline, harmless scripts)."""
    func = REMOTE_TOOL_FUNCS[tool_name]
    try:
        raw = func(**kwargs)
    except Exception as exc:  # noqa: BLE001 - the framework stringifies too
        return {
            "kind": "raised",
            "exception": type(exc).__name__,
            "text": str(exc),
            "status": None,
            "reason": None,
        }
    return normalize_result(raw)


def write_local_payload(folder: str, name: str = "payload.txt") -> str:
    """Create a harmless local file used as the copy source."""
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handler:
        handler.write("payload\n")
    return path


def write_skill_folder(folder: str, script_relpath: str = "scripts/echo.sh") -> str:
    """Create a minimal skill folder whose script only echoes a marker."""
    script_path = os.path.join(folder, script_relpath)
    os.makedirs(os.path.dirname(script_path), exist_ok=True)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as handler:
        handler.write("---\nname: bdd-remote-probe\ndescription: offline probe skill\n---\n# probe\n")
    with open(script_path, "w", encoding="utf-8") as handler:
        handler.write(SKILL_ECHO_BODY)
    os.chmod(script_path, os.stat(script_path).st_mode | 0o111)
    return folder


def expand_token(context: dict, token: str, placeholders: dict | None = None) -> Any:
    """Resolve one Examples cell into the value an LLM would actually send.

    Shared by every step module so that the token grammar lives in one place:
    ``resolve_value`` for native types, ``<sp>`` for a literal space, ``empty``
    for the empty string, and caller-supplied ``{placeholder}`` substitutions.
    """
    if not isinstance(token, str):
        # A ``raw:`` cell may already contain native JSON members; they are sent
        # to the tool exactly as written and must not be re-interpreted.
        return token
    value = resolve_value(token)
    if isinstance(value, list):
        return [expand_token(context, item, placeholders) for item in value]
    if isinstance(value, dict):
        return {key: expand_token(context, item, placeholders) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    value = value.replace("<sp>", " ")
    if value == "empty":
        return ""
    for placeholder, replacement in (placeholders or {}).items():
        value = value.replace(placeholder, replacement)
    return value


# --------------------------------------------------------------------------- human decision tool
#
# ``human_tool.ask_decision`` is the project-designated reference implementation of
# string-first parameter handling, so its contract is pinned here as well. Every call
# runs inside a daemon worker thread guarded by a hard ceiling: a scenario must never
# block waiting for input, even if a future change accidentally re-enables prompting.

import threading  # noqa: E402

from topsailai.tools import human_tool  # noqa: E402
from topsailai.utils import thread_local_tool  # noqa: E402

# Absolute ceiling for one ask_decision call inside a scenario.
HUMAN_CALL_CEILING_SECONDS = 5.0

# Question text used whenever a scenario only exercises another argument.
HUMAN_BASE_QUESTION = "Should the scenario continue?"


def call_human_tool(answer: Any = None, **kwargs: Any) -> dict:
    """Call ``ask_decision`` without an input channel, or with a scripted answer.

    ``answer`` registers a thread-local runtime input function *inside* the worker
    thread, which is what a real agent run does; leaving it as ``None`` reproduces a
    non-interactive process, where a well-formed request must degrade to
    ``unavailable`` while a malformed one must still answer ``invalid_request``.
    """
    box: dict[str, Any] = {}
    prompts: list[str] = []

    def runner() -> None:
        if answer is not None:
            def scripted_read(prompt: str, timeout: float | None = None) -> str:
                prompts.append(prompt)
                return answer

            thread_local_tool.set_agent_runtime_input_with_timeout(scripted_read)
        try:
            box["raw"] = human_tool.ask_decision(**kwargs)
        except Exception as exc:  # noqa: BLE001 - the framework stringifies too
            box["raised"] = exc

    with patch.dict(
        os.environ,
        {"TOPSAILAI_INTERACTIVE_MODE": "0", "TOPSAILAI_HUMAN_DECISION_TIMEOUT": "0"},
    ):
        worker = threading.Thread(target=runner, daemon=True)
        worker.start()
        worker.join(HUMAN_CALL_CEILING_SECONDS)

    if worker.is_alive():
        return {
            "kind": "hang",
            "status": None,
            "reason": None,
            "text": f"ask_decision did not return within {HUMAN_CALL_CEILING_SECONDS}s",
            "prompts": prompts,
        }
    if "raised" in box:
        exc = box["raised"]
        return {
            "kind": "raised",
            "exception": type(exc).__name__,
            "text": str(exc),
            "status": None,
            "reason": None,
            "prompts": prompts,
        }
    result = normalize_result(box.get("raw"))
    result["prompts"] = prompts
    raw = box.get("raw")
    if isinstance(raw, dict):
        # ``ask_decision`` always answers a dict carrying these two fields, so they are
        # exposed directly instead of being re-parsed out of the rendered text.
        result["answer"] = raw.get("answer")
        result["option_index"] = raw.get("option_index")
    return result


# --------------------------------------------------------------------------- str-only guard tools
#
# These tools declare string-only arguments, so no coercion is expected. The guard
# suite still exercises them because a raw Python exception would otherwise be
# stringified by ``exec_tool_func`` and handed straight back to the model.
# Nothing here touches a real LLM, a real sub-agent or the real memory workspace.

from topsailai.tools import ctx_tool, story_memory_tool, story_tool, subagent_tool, time_tool  # noqa: E402
from topsailai.tools import multimodal_readonly_tool  # noqa: E402
from topsailai.tools.file_tool_utils import file_stat  # noqa: E402

# Canned answers returned by the mocked multimodal / sub-agent layers.
MULTIMODAL_ANSWER = "MOCK-MULTIMODAL-DESCRIPTION"
SUBAGENT_ANSWER = "MOCK-SUBAGENT-ANSWER"

GUARD_TOOL_FUNCS: dict[str, Callable[..., Any]] = {
    "write_memory": story_memory_tool.write_memory,
    "read_memory": story_memory_tool.read_memory,
    "list_memories": story_memory_tool.list_memories,
    "delete_memory": story_memory_tool.delete_memory,
    "write_story": story_tool.StoryFileInstance.write_story,
    "read_story": story_tool.StoryFileInstance.read_story,
    "list_stories": story_tool.StoryFileInstance.list_stories,
    "retrieve_stories": story_tool.StoryFileInstance.retrieve_stories,
    "delete_story": story_tool.StoryFileInstance.delete_story,
    "retrieve_msg": ctx_tool.retrieve_msg,
    "get_local_date": time_tool.get_local_date,
    "get_local_time": time_tool.get_local_time,
    "recognize_image": multimodal_readonly_tool.recognize_image,
    "recognize_voice": multimodal_readonly_tool.recognize_voice,
    "recognize_video": multimodal_readonly_tool.recognize_video,
    "call_assistant": subagent_tool.call_assistant,
    "get_file_size": file_stat.get_file_size,
}

# Tools whose module-level WORKSPACE must point at the scenario sandbox.
MEMORY_TOOLS = ("write_memory", "read_memory", "list_memories", "delete_memory")

# Tools that read their sandbox folder from the first positional argument.
STORY_TOOLS = ("write_story", "read_story", "list_stories", "retrieve_stories", "delete_story")

# Tools that would otherwise reach an LLM or spawn a sub-agent.
MULTIMODAL_TOOLS = ("recognize_image", "recognize_voice", "recognize_video")


def _mocked_multimodal_chat() -> Any:
    """Build the multimodal chat double used instead of any real LLM call."""
    chat = MagicMock()
    chat.chat_with_image.return_value = MULTIMODAL_ANSWER
    chat.chat_with_audio.return_value = MULTIMODAL_ANSWER
    chat.chat_with_video.return_value = MULTIMODAL_ANSWER
    return chat


def call_guard_tool(tool_name: str, workspace: str, **kwargs: Any) -> dict:
    """Call one str-only tool with every external side effect mocked out."""
    func = GUARD_TOOL_FUNCS[tool_name]
    arguments = dict(kwargs)
    with ExitStack() as stack:
        if tool_name in MEMORY_TOOLS:
            stack.enter_context(patch.object(story_memory_tool, "WORKSPACE", workspace))
        if tool_name in STORY_TOOLS:
            arguments["workspace"] = workspace
        if tool_name in MULTIMODAL_TOOLS:
            stack.enter_context(
                patch.object(
                    multimodal_readonly_tool,
                    "get_multimodal_llm_chat",
                    return_value=_mocked_multimodal_chat(),
                )
            )
        if tool_name == "call_assistant":
            # ``call_assistant`` imports the factory at call time, so the patch has to
            # target the module it is defined in rather than the import site.
            from topsailai.workspace import agent_shell

            sub_agent = MagicMock()
            sub_agent._run.return_value = SUBAGENT_ANSWER
            stack.enter_context(patch.object(agent_shell, "get_agent_chat", return_value=sub_agent))
        try:
            raw = func(**arguments)
        except Exception as exc:  # noqa: BLE001 - the framework stringifies too
            return {
                "kind": "raised",
                "exception": type(exc).__name__,
                "text": str(exc),
                "status": None,
                "reason": None,
            }
    return normalize_result(raw)


def write_guard_workspace(folder: str) -> str:
    """Create the ``story`` layout a str-only guard scenario writes into."""
    story_folder = os.path.join(folder, "story")
    os.makedirs(story_folder, exist_ok=True)
    return folder
