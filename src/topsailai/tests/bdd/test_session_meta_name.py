"""Author: DawsonLin. Real HTTP/SSE session-name metadata acceptance."""

from pytest_bdd import given, scenarios, then, when

from tests.bdd import session_name_startup_context_harness as harness

scenarios("features/session_meta_name.feature")


@given("an isolated metadata session with a real naming provider", target_fixture="metadata_scenario")
def metadata_scenario(monkeypatch, bdd_tmp_path):
    """Own a real loopback server and isolated child environment."""
    scenario = harness.SessionNameStartupScenario(monkeypatch, bdd_tmp_path,
                                                  agent_type="react", integrity=True)
    monkeypatch.setenv("TOPSAILAI_AUTO_SESSION_NAME_ENABLED", "1")
    monkeypatch.setattr(harness, "_CHILD_SCRIPT",
                        "from tests.bdd.session_meta_name_child import main; main()")
    try:
        yield scenario
    finally:
        scenario.close()
        assert not scenario.server_thread.is_alive()
        assert scenario.server.socket.fileno() == -1


@when("the Agent completes naming and resumes the same session")
def run(metadata_scenario):
    """Drive the public shell over the actual OpenAI SSE boundary."""
    metadata_scenario.run()


@then("the metadata retains the committed name and terminal timestamp")
def inspect_metadata(metadata_scenario):
    """Compare creation, projection, completion and restored startup."""
    report = metadata_scenario.integrity_report()
    assert report["created"]["session_name"] == ""
    assert report["created"]["status"] == "running"
    assert report["db_name"]
    for checkpoint in ("named", "completed", "resumed"):
        assert report[checkpoint]["session_name"] == report["db_name"]
        assert report[checkpoint]["pid"] == report["created"]["pid"]
    assert report["named"]["status"] == "running"
    assert report["named"]["end_ts"] is None
    assert report["completed"]["status"] == "completed"
    assert report["completed"]["end_ts"]
    assert report["resumed"]["status"] == "running"


@then("naming uses exactly one isolated provider request")
def inspect_requests(metadata_scenario):
    """Assert retained wire bodies and no rename-induced extra request."""
    state = metadata_scenario.state()
    assert state["total_requests"] == 2
    bodies = [item["body"] for item in state["request_bodies"]]
    naming = [body for body in bodies if any("You are a naming assistant" in
              str(message.get("content", "")) for message in body["messages"])]
    assert len(naming) == 1
    assert naming[0]["stream"] is True
    text = str(naming[0]["messages"])
    assert "Name this metadata regression task" in text
    assert harness.USER_MARKER not in text
    assert harness.EXPLICIT_MARKER not in text
    assert any(harness.USER_MARKER in str(body["messages"]) for body in bodies if body not in naming)
