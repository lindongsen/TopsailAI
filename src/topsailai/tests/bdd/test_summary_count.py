"""Real HTTP and SQLite summary accounting acceptance. Author: DawsonLin."""

from pytest_bdd import given, when, then, parsers, scenarios

from tests.bdd.test_summary_observation_recovery import recovery_resources, provider_state
from topsailai.context import ctx_manager
from topsailai.context.session_manager.__base import SessionData
from topsailai.context.session_manager.sql import SessionSQLAlchemy
from topsailai.workspace.context.summary_recovery import RecoveryConfig

scenarios("features/summary_count.feature")


@given(parsers.parse("a summary counter for {layer} with {policy} context using a private provider"), target_fixture="counter_case")
def counter_case(recovery_resources, monkeypatch, tmp_path, layer, policy):
    """Bind both persistence boundaries to one scenario-owned real database."""
    owner, server = recovery_resources
    storage = SessionSQLAlchemy(f"sqlite:///{tmp_path / 'summary.db'}")
    assert storage.create_session(SessionData("counted"))
    assert storage.create_session(SessionData("unrelated"))
    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: storage)
    monkeypatch.setattr(ctx_manager, "get_managers_by_env", lambda: [storage.chat_history])
    owner.session_id = "counted"
    owner.summary_recovery_config = RecoveryConfig(policy == "recovery")
    monkeypatch.setenv("TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES", "0")
    try:
        yield owner, server, storage, layer, policy
    finally:
        storage.chat_history.engine.dispose()
        storage.engine.dispose()


@when("two summaries are applied in successive work intervals")
def apply_twice(counter_case):
    """Run real layer methods with actual HTTP generation and stored history."""
    owner, _, storage, layer, policy = counter_case
    for interval in range(2):
        observation = {"role": "user", "content": {"step_name": "observation", "raw_text": "source constraints " * 50000}}
        task = {"role": "user", "content": {"step_name": "task", "raw_text": f"Continue work {interval}"}}
        messages = [observation, task] if policy == "recovery" else [task, {"role": "assistant", "content": "work details " * 500}, {"role": "user", "content": f"Next {interval}"}]
        for record in storage.get_messages_by_session("counted"):
            storage.chat_history.del_messages(record.msg_id, "counted")
        for message in messages:
            storage.chat_history.add_session_message(message, session_id="counted")
        messages = storage.retrieve_messages("counted")
        owner.messages = list(messages)
        owner.ai_agent.messages = list(messages)
        method = owner.summarize_messages_for_processed if layer == "user2agent" else owner.summarize_messages_for_processing
        assert method(messages=list(messages), force=True)
        assert owner.summary_count == interval + 1
        assert storage.get_session("counted").summary_count == interval + 1


@then("the session and runtime both record two summaries")
def check_totals(counter_case):
    """Prove exact additive persistence and isolation of the unrelated session."""
    owner, server, storage, _, _ = counter_case
    assert owner.summary_count == storage.get_session("counted").summary_count == 2
    assert storage.get_session("unrelated").summary_count == 0
    state = provider_state(server)
    assert state["total_requests"] == 2
    assert all(record["body"]["messages"] for record in state["request_bodies"])


@then("a skipped summary leaves the totals and provider requests unchanged")
def check_skip(counter_case):
    """Empty work must not generate or count a summary."""
    owner, server, storage, layer, _ = counter_case
    owner.messages = []
    owner.ai_agent.messages = []
    method = owner.summarize_messages_for_processed if layer == "user2agent" else owner.summarize_messages_for_processing
    # Disable session reload only for the explicit empty-input skip check.
    if layer == "user2agent":
        owner.session_id = ""
    assert method(force=True) is None
    assert owner.summary_count == storage.get_session("counted").summary_count == 2
    assert provider_state(server)["total_requests"] == 2
