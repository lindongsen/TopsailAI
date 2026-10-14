"""Real tmux CLI BDD against the shared OpenAI-compatible SSE mock.

Author: DawsonLin
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.bdd.instruction_message_integrity_assertions import (
    parse_agent_messages,
    parse_history_roles_and_content,
)
from tests.bdd.two_layer_message_harness import EOF_HINT, TwoLayerCLI
from tests.mock.llm_mock_server import MockServerConfig, create_server

scenarios("features/two_layer_message_verification.feature")


def final(marker: str) -> str:
    """Encode a real formatted final step for the CLI response parser."""
    return f"topsailai.final_answer\n{marker}"


def delegation(task: str) -> str:
    """Encode a real plan execution step calling the registered subagent tool."""
    return "topsailai.action\n" + json.dumps({
        "tool_call": "subagent_tool-call_assistant", "tool_args": {"task": task},
    })


def agent_report(output: str) -> list[dict]:
    """Extract the newest complete report rather than stale scrollback text."""
    footer = list(re.finditer(r"---\s*\nTotalCount: \d+", output))[-1]
    prefix = output[:footer.start()]
    for match in reversed(list(re.finditer(r"(?m)^\[", prefix))):
        try:
            return parse_agent_messages(output[match.start():footer.end()])
        except AssertionError:
            continue
    raise AssertionError(f"no valid fresh agent report: {output}")


def history_report(output: str) -> list[tuple[str, str]]:
    """Extract the latest numbered session report including its final block."""
    start = list(re.finditer(r"(?m)^#1 - Role:", output))[-1].start()
    report = output[start:]
    report = report.split(">>> Your Turn", 1)[0]
    return parse_history_roles_and_content(report)


@pytest.fixture
def layer_session(bdd_tmp_path):
    """Own the CLI and mock from first allocation through unconditional teardown."""
    state = {"directory": bdd_tmp_path, "snapshots": []}
    try:
        yield state
    finally:
        try:
            if "cli" in state:
                state["cli"].stop()
                result = state["cli"].session
                assert subprocess.run(
                    ["tmux", "has-session", "-t", result],
                    capture_output=True, check=False,
                ).returncode != 0
        finally:
            if "server" in state:
                if state.get("thread") and state["thread"].is_alive():
                    state["server"].shutdown()
                    state["thread"].join(timeout=5)
                    assert not state["thread"].is_alive()
                state["server"].server_close()


@given(parsers.parse('an isolated "{cli_name}" CLI with scripted {kind} replies'))
def isolated_cli(layer_session, cli_name, kind):
    """Start a private SSE endpoint and the actual interactive entry point."""
    if not shutil.which("tmux"):
        pytest.skip("two-layer interactive BDD requires tmux")
    replies = [final(f"DIRECT_REPLY_{i}") for i in range(1, 4)]
    if kind == "delegation":
        replies = []
        for i in range(1, 3):
            replies.extend((delegation(f"MEMBER_TASK_{i}"),
                            final(f"MEMBER_REPLY_{i}"), final(f"MANAGER_REPLY_{i}")))
    server = create_server(MockServerConfig(
        stream_response_chunks=tuple((reply,) for reply in replies),
        stream_chunks=(final("UNEXPECTED_EXTRA_REQUEST"),),
    ))
    layer_session["server"] = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    layer_session["thread"] = thread
    thread.start()
    cli = TwoLayerCLI(cli_name, f"http://127.0.0.1:{server.server_port}/v1",
                      layer_session["directory"])
    layer_session["cli"] = cli
    layer_session["startup"] = cli.start()


@then(parsers.parse('the CLI advertises "{mode}" input'))
def input_mode(layer_session, mode):
    """Verify real startup input hints match the selected entry point."""
    assert (EOF_HINT in layer_session["startup"]) == (mode == "multiline")


def snapshot(state):
    """Run slash instructions and parse each newly emitted layer report."""
    cli = state["cli"]
    agent = agent_report(cli.send("/agent.messages", expected="TotalCount:"))
    history = history_report(cli.send("/ctx.history", expected="#1 - Role:"))
    state["snapshots"].append((agent, history))


@when("I complete three direct exchanges")
def direct_exchanges(layer_session):
    """Submit three business turns with EOF only for the multi-line CLI."""
    cli = layer_session["cli"]
    for i in range(1, 4):
        cli.send(f"DIRECT_TASK_{i}", multiline=cli.cli_name == "agent_chats",
                 expected=f"DIRECT_REPLY_{i}")
        snapshot(layer_session)


@then("both message layers contain the ordered direct exchanges")
def direct_layers(layer_session):
    """Check persisted cardinality/roles and actual runtime message markers."""
    for i, (agent, history) in enumerate(layer_session["snapshots"], 1):
        assert len(history) == i * 2, history
        assert [role for role, _ in history] == ["user", "assistant"] * i
        for j in range(1, i + 1):
            assert f"DIRECT_TASK_{j}" in history[2 * j - 2][1]
            assert f"DIRECT_REPLY_{j}" in history[2 * j - 1][1]
        current = [(m["role"], str(m.get("content", ""))) for m in agent]
        assert any(role == "user" and f"DIRECT_TASK_{i}" in text for role, text in current)
        assert any(role == "assistant" and f"DIRECT_REPLY_{i}" in text for role, text in current)
        assert all(text.strip() != "EOF" for _, text in current)


@when("I complete two delegated exchanges")
def delegated_exchanges(layer_session):
    """Execute two real manager-to-subagent exchanges via scripted SSE steps."""
    for i in range(1, 3):
        layer_session["cli"].send(f"DELEGATE_TASK_{i}", expected=f"MANAGER_REPLY_{i}")
        snapshot(layer_session)


@then("both layers preserve ordered delegation results with four-message growth")
def delegated_layers(layer_session):
    """Require ordered dispatch/result/final blocks and exact persisted growth."""
    for i, (agent, history) in enumerate(layer_session["snapshots"], 1):
        assert len(history) == 4 * i, history
        group = history[-4:]
        assert [role for role, _ in group] == ["user", "user", "assistant", "assistant"]
        for (_, content), marker in zip(group, (
            f"DELEGATE_TASK_{i}", f"MEMBER_TASK_{i}",
            f"MEMBER_REPLY_{i}", f"MANAGER_REPLY_{i}",
        )):
            assert marker in content, group
        runtime = "\n".join(json.dumps(m, ensure_ascii=False) for m in agent)
        for marker in (f"DELEGATE_TASK_{i}", f"MEMBER_TASK_{i}", f"MEMBER_REPLY_{i}", f"MANAGER_REPLY_{i}"):
            assert marker in runtime, (marker, agent)
        positions = [runtime.index(marker) for marker in (
            f"DELEGATE_TASK_{i}", f"MEMBER_TASK_{i}",
            f"MEMBER_REPLY_{i}", f"MANAGER_REPLY_{i}",
        )]
        assert positions == sorted(positions)


@then(parsers.parse("only {number} HTTP completions were requested"))
def http_requests(layer_session, number):
    """Verify exact transport cardinality and business markers on the wire."""
    records = layer_session["server"].request_body_capture.state()["request_bodies"]
    assert len(records) == {"three": 3, "six": 6}[number], records
    for record in records:
        body = record["body"]
        assert record["parsed"] and body["stream"] is True
        assert body["model"] == "bdd-agent"
        assert all(str(m.get("content", "")).strip() != "EOF" for m in body["messages"])
    if number == "six":
        for i, index in enumerate((1, 4), 1):
            assert f"MEMBER_TASK_{i}" in json.dumps(records[index]["body"]["messages"])
    else:
        for i, record in enumerate(records, 1):
            assert f"DIRECT_TASK_{i}" in json.dumps(record["body"]["messages"])
