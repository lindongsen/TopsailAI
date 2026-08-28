"""Step definitions for remote-tool parameter-coercion behavior tests.

Covers ``sandbox_tool.call_sandbox``/``copy2sandbox``, ``ssh_tool.operate_ssh`` and
``skill_tool.call_skill``. Every step text is prefixed with ``remote``/``skill`` and
phrased around ``parameter`` so it cannot collide with the CLI suite in
``cli/tests/bdd/steps`` or with the cmd/git/file step module (pytest-bdd silently
lets identically-parsed steps override each other).

Safety contract
---------------
No scenario opens a socket. The transport symbol of the tool under test is replaced
by a recorder, which additionally lets scenarios assert that a rejected argument
produced *zero* side effects. Remote hosts use RFC 5737 TEST-NET-1 (``192.0.2.10``).

Value tokens understood in Examples tables
------------------------------------------
- ``empty``      -> the empty string
- ``null``       -> ``None``
- ``<sp>``       -> one literal space (Gherkin trims cell whitespace)
- ``int:5`` / ``float:2.5`` / ``raw:[..]`` -> native Python value
- ``{sandbox}`` / ``{payload}`` / ``{skill}`` / ``{srcdir}`` -> fixture values
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any

import pytest
from pytest_bdd import given, parsers, then, when

logger = logging.getLogger("tests.bdd.tool_param.remote")

from tests.bdd.tool_param_harness import (
    TEST_NET_HOST,
    call_plain_tool,
    call_remote_tool,
    expand_token,
    write_local_payload,
    write_skill_folder,
)

SANDBOX_CONFIG = f"tag=bdd,protocol=ssh,node={TEST_NET_HOST},port=22"
REMOTE_TARGET = "/remote/incoming/payload.txt"
PROBE_SCRIPT = "scripts/echo.sh"


@pytest.fixture
def remote_ctx():
    """Per-scenario state plus a temporary folder that is removed after the scenario."""
    context: dict[str, Any] = {"files": {}, "response": None}
    yield context
    folder = context["files"].get("folder")
    if folder and os.path.isdir(folder):
        shutil.rmtree(folder)
        logger.info("removed remote parameter test folder: [%s]", folder)


def _tmp_folder(ctx) -> str:
    """Return (creating on first use) the scenario-scoped temporary folder."""
    folder = ctx["files"].get("folder")
    if not folder:
        import tempfile

        folder = tempfile.mkdtemp(prefix="topsailai-bdd-remote-")
        ctx["files"]["folder"] = folder
    return folder


def _placeholders(ctx) -> dict:
    """Fixture substitutions available inside remote Examples tables."""
    return {
        "{sandbox}": ctx["files"].get("sandbox", SANDBOX_CONFIG),
        "{payload}": ctx["files"].get("payload", ""),
        "{skill}": ctx["files"].get("skill", ""),
        "{srcdir}": ctx["files"].get("srcdir", ""),
    }


def _expand(ctx, token: str) -> Any:
    """Resolve one Examples cell into the value an LLM would actually send."""
    return expand_token(ctx, token, _placeholders(ctx))


def _base_arguments(ctx, tool: str) -> dict:
    """Build the well-formed arguments of one remote tool call."""
    if tool == "call_sandbox":
        return {"sandbox": SANDBOX_CONFIG, "cmd": "echo hi"}
    if tool == "copy2sandbox":
        return {
            "sandbox": SANDBOX_CONFIG,
            "local_fpath": ctx["files"]["payload"],
            "sandbox_fpath": REMOTE_TARGET,
        }
    if tool == "operate_ssh":
        return {"action": "exec", "host": TEST_NET_HOST, "command": "echo hi"}
    if tool == "call_skill":
        return {"skill_folder": ctx["files"]["skill"], "script_path": PROBE_SCRIPT}
    if tool == "list_sandbox":
        return {}
    raise AssertionError(f"unknown remote tool: {tool}")


# --------------------------------------------------------------------------- given

@given(parsers.parse('a remote sandbox configuration for host {host}'))
def remote_sandbox(ctx, host):
    """The operator registered one sandbox that is reachable over SSH only."""
    ctx["files"]["sandbox"] = f"tag=bdd,protocol=ssh,node={host.strip()},port=22"


@given(parsers.parse('a local payload file named {name} for the copy operation'))
def local_payload(ctx, name):
    """A harmless local file acts as the copy source."""
    ctx["files"]["payload"] = write_local_payload(_tmp_folder(ctx), name)


@given(parsers.parse('a local folder named {name} for the rsync operation'))
def local_source_folder(ctx, name):
    """A harmless local directory acts as the rsync source."""
    path = os.path.join(_tmp_folder(ctx), name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "inner.txt"), "w", encoding="utf-8") as handler:
        handler.write("inner\n")
    ctx["files"]["srcdir"] = path


@given(parsers.parse('a skill folder holding the offline script {script}'))
def skill_folder(ctx, script):
    """A minimal skill whose script only echoes a marker, so nothing is downloaded."""
    ctx["files"]["skill"] = write_skill_folder(_tmp_folder(ctx), script)


# --------------------------------------------------------------------------- when


@when(parsers.parse('the remote tool {tool} is invoked with parameter {param} set to {value}'))
def invoke_remote_with_parameter(ctx, tool, param, value):
    """An LLM sends one stringified control argument to a remote tool."""
    arguments = _base_arguments(ctx, tool)
    arguments[param] = _expand(ctx, value)
    ctx["response"] = call_remote_tool(tool, **arguments)


@when(parsers.parse('the remote tool operate_ssh is invoked for rsync with parameter delete set to {value}'))
def invoke_rsync_with_delete(ctx, value):
    """The destructive rsync switch arrives as text from the model."""
    ctx["response"] = call_remote_tool(
        "operate_ssh",
        action="rsync",
        host=TEST_NET_HOST,
        source=ctx["files"]["srcdir"],
        target="/remote/mirror/",
        delete=_expand(ctx, value),
    )


@when(parsers.parse('the skill tool call_skill is really invoked with parameter {param} set to {value}'))
def invoke_skill_for_real(ctx, param, value):
    """The probe script actually runs, proving the coerced argument was used."""
    arguments = _base_arguments(ctx, "call_skill")
    arguments[param] = _expand(ctx, value)
    ctx["response"] = call_plain_tool("call_skill", **arguments)


# --------------------------------------------------------------------------- then


@then('the remote call is rejected as a parameter error before any connection')
def remote_parameter_error(ctx):
    """A bad argument must be answered locally, never reach the transport."""
    response = ctx["response"]
    assert response["kind"] == "dict", f"expected a dict, got {response}"
    assert response["status"] == "invalid_request", f"unexpected status: {response}"
    assert response["reason"], f"missing reason: {response}"
    assert response["transport_calls"] == 0, f"side effect happened: {response}"
    assert "unavailable" not in response["text"], f"business status leaked: {response}"
    assert "invalid literal for int()" not in response["text"], f"raw exception leaked: {response}"
    assert "Traceback" not in response["text"], f"raw exception leaked: {response}"


@then(parsers.parse('the parameter error names the {param} remote parameter'))
def remote_error_names_parameter(ctx, param):
    """The reason must tell the model which remote argument was rejected."""
    response = ctx["response"]
    reason = response.get("reason") or response.get("text", "")
    assert param in reason, f"{param!r} not mentioned in {reason!r}"


@then('the remote call is accepted and reaches the transport once')
def remote_call_accepted(ctx):
    """A coercible argument must reach normal remote execution exactly once."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"tool raised: {response}"
    assert response.get("status") != "invalid_request", f"unexpected parameter error: {response}"
    assert response["transport_calls"] == 1, f"expected one transport call: {response}"


@then(parsers.parse('the remote transport received {kwarg} equal to {expected}'))
def remote_transport_kwarg(ctx, kwarg, expected):
    """The coerced value is what the transport actually receives."""
    response = ctx["response"]
    assert response["transport_calls"] >= 1, f"transport unused: {response}"
    actual = response["transport_kwargs"].get(kwarg)
    assert str(actual) == expected.strip(), f"{kwarg}: expected {expected!r}, got {actual!r}"


@then(parsers.parse('the remote transport received {kwarg} as the mapping {expected}'))
def remote_transport_mapping_kwarg(ctx, kwarg, expected):
    """A JSON-encoded container argument reaches the transport as a real mapping."""
    response = ctx["response"]
    assert response["transport_calls"] >= 1, f"transport unused: {response}"
    actual = response["transport_kwargs"].get(kwarg)
    assert actual == json.loads(expected), f"{kwarg}: expected {expected!r}, got {actual!r}"


@then(parsers.parse('the remote command line contains {fragment}'))
def remote_command_contains(ctx, fragment):
    """The built remote command really carries the requested option."""
    response = ctx["response"]
    assert response["transport_calls"] >= 1, f"transport unused: {response}"
    assert fragment in response["transport_command"], f"{fragment!r} missing from {response['transport_command']!r}"


@then(parsers.parse('the remote command line does not contain {fragment}'))
def remote_command_excludes(ctx, fragment):
    """A rejected-looking flag spelling must not silently enable destructive behavior.

    A rejected argument never reaches the transport at all, and "no command line was
    built" is the strongest possible guarantee that the destructive option is absent.
    """
    response = ctx["response"]
    assert fragment not in response["transport_command"], f"{fragment!r} present in {response['transport_command']!r}"


@then('the remote response carries no raw conversion exception')
def remote_no_raw_exception(ctx):
    """Reverse guard: the model never sees a bare Python conversion message."""
    response = ctx["response"]
    text = response.get("text", "")
    for marker in ("invalid literal for int()", "Traceback", "SkillToolError", "TypeError:", "ValueError:"):
        assert marker not in text, f"raw exception leaked: {text[:200]!r}"
    assert response.get("status") != "unavailable", f"business status used: {response}"


@then('the offline skill script prints its marker')
def skill_marker(ctx):
    """The skill actually executed with the coerced arguments."""
    response = ctx["response"]
    assert response["kind"] == "command", f"expected command result, got {response}"
    assert response["code"] == 0, f"non-zero exit: {response}"
    assert "skill-echo-ok" in response["stdout"], f"marker missing: {response['stdout']!r}"


@then(parsers.parse('the remote tool raises {exception} instead of reporting a parameter error'))
def remote_tool_raises(ctx, exception):
    """Pins a known defect: the argument escapes as an exception (wip scenarios)."""
    response = ctx["response"]
    assert response["kind"] == "raised", f"expected a raise, got {response}"
    assert response["exception"] == exception, f"unexpected exception: {response}"


@then('the copy operation reports success')
def copy_reports_success(ctx):
    """A coercible copy must be reported as done, not swallowed silently."""
    response = ctx["response"]
    assert response["kind"] != "raised", f"copy raised: {response}"
    assert response.get("status") != "invalid_request", f"unexpected parameter error: {response}"
    assert response["text"] in ("True", "REMOTE-OK"), f"unexpected copy answer: {response}"


@then('the remote tool reports that sandbox configuration is unavailable')
def remote_reports_unavailable_sandbox_configuration(ctx):
    """An absent sandbox configuration is an environment status, not a parameter error."""
    response = ctx["response"]
    assert response["kind"] == "dict", f"expected a structured answer, got {response}"
    assert response["status"] == "unavailable", f"unexpected status: {response}"
    assert "sandbox" in response["text"].lower(), f"missing sandbox reason: {response}"
