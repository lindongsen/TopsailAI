"""BDD steps for real first-byte response ownership."""

import pytest
from pytest_bdd import given, then, when, parsers

from tests.bdd.llm_first_byte_timeout_harness import (
    FirstByteOwnershipScenario,
    SharedPoolOwnershipScenario,
)


@pytest.fixture
def first_byte_ownership_ctx(monkeypatch, _pytest_bdd_example):
    """Create the scenario-selected real HTTP ownership harness."""
    context = FirstByteOwnershipScenario(monkeypatch, _pytest_bdd_example["phase"])
    yield context
    context.close()


@pytest.fixture
def shared_pool_ownership_ctx(monkeypatch, _pytest_bdd_example):
    """Create the scenario-selected shared-pool harness."""
    context = SharedPoolOwnershipScenario(monkeypatch, _pytest_bdd_example["phase"])
    yield context
    context.close()

@given(parsers.parse("a real first-byte ownership server delays request 1 in the {phase} phase"))
def given_first_byte_ownership_server(first_byte_ownership_ctx, phase):
    """Start the real delay-configured mock server."""
    assert first_byte_ownership_ctx.phase == phase
    assert first_byte_ownership_ctx.server_thread.is_alive()


@when("the production streaming chat retries after the first-byte timeout")
def when_first_byte_retry(first_byte_ownership_ctx):
    """Run the production model chat method without internal transport stubs."""
    first_byte_ownership_ctx.result = first_byte_ownership_ctx.run_retry()


@then("request 2 succeeds with FRESH_SECOND and exactly two request bodies were captured")
def then_fresh_second(first_byte_ownership_ctx):
    """Assert replacement request success and exact server request evidence."""
    state = first_byte_ownership_ctx.state()
    assert first_byte_ownership_ctx.result == "FRESH_SECOND"
    assert state["total_requests"] == 2, state
    assert len(state["request_bodies"]) == 2, state


@then("a mismatched request body is rejected")
def then_body_mismatch_rejected(first_byte_ownership_ctx):
    """Require the harness body contract to reject altered content."""
    first_byte_ownership_ctx.assert_body_mismatch_rejected()


@then("stale content is absent from senders usage and response events")
def then_no_stale(first_byte_ownership_ctx):
    """Assert stale content never crossed publication boundaries."""
    assert first_byte_ownership_ctx.sent == ["FRESH_SECOND"]
    assert all("STALE_OLD" not in str(value) for value in first_byte_ownership_ctx.usage)
    assert all("STALE_OLD" not in str(value) for value in first_byte_ownership_ctx.events)


@when("request 1 is released")
def when_old_released(first_byte_ownership_ctx):
    """Release the delayed old server request."""
    first_byte_ownership_ctx.release_old()


@then("the old response is closed and its exact handler thread exits")
def then_old_settled(first_byte_ownership_ctx):
    """Assert raw close and exact mock handler settlement."""
    if first_byte_ownership_ctx.phase == "first_item":
        first_byte_ownership_ctx.assert_first_item_settled()
        return
    old = first_byte_ownership_ctx.server.lifecycle_capture.request_handle(1)
    assert old.response_finished.wait(5)
    assert old.connection_closed.wait(5)
    assert old.wait_for_thread_exit(5)
    if 1 in first_byte_ownership_ctx.raw_ready_events:
        assert first_byte_ownership_ctx.raw_ready_events[1].wait(5)
        old_raw = first_byte_ownership_ctx.raw_by_request[1]
        assert first_byte_ownership_ctx.raw_close_events[1].wait(5)
        assert old_raw.is_closed
        assert any(
            raw_id == id(old_raw) and is_closed
            for raw_id, is_closed, _ in first_byte_ownership_ctx.closed_raw
        )


@given(parsers.parse("a real shared-pool ownership server delays request 1 and request 3 in the {phase} phase"))
def given_shared_pool_server(shared_pool_ownership_ctx, phase):
    """Start the real shared-pool delay server."""
    assert shared_pool_ownership_ctx.phase == phase
    assert shared_pool_ownership_ctx.server_thread.is_alive()


@when("the retry and an in-flight sibling request use the same pooled client")
def when_shared_pool_flow(shared_pool_ownership_ctx):
    """Run the retry and sibling flow through real HTTP/SSE requests."""
    shared_pool_ownership_ctx.result = shared_pool_ownership_ctx.run_sibling_flow()


@then("request 2 succeeds while request 3 remains in flight")
def then_sibling_in_flight(shared_pool_ownership_ctx):
    """Verify request 3 was accepted and held before cleanup."""
    assert shared_pool_ownership_ctx.result[0] == "FRESH_SECOND"
    handle = shared_pool_ownership_ctx.server.lifecycle_capture.request_handle(3)
    assert handle.record["waiting_phase"] in {"headers", "first_item"}


@when("request 1 is released while request 3 remains held")
def when_old_released_shared(shared_pool_ownership_ctx):
    """Release only the old request and prove sibling isolation."""
    shared_pool_ownership_ctx.release_old_and_prove_isolation()


@then("the old response is closed while the sibling remains held")
def then_old_closed_sibling_held(shared_pool_ownership_ctx):
    """Require old settlement before allowing sibling release."""
    shared_pool_ownership_ctx.assert_sibling_held()


@when("a follow-up request runs while request 3 remains held")
def when_follow_up_held(shared_pool_ownership_ctx):
    """Run the follow-up while the sibling transport remains held."""
    shared_pool_ownership_ctx.follow_up = shared_pool_ownership_ctx.run_follow_up_while_sibling_held()


@then("the follow-up succeeds without closing the shared root client")
def then_follow_up_reusable(shared_pool_ownership_ctx):
    """Assert follow-up output and continued sibling ownership."""
    assert shared_pool_ownership_ctx.follow_up == "FOLLOW_UP"
    shared_pool_ownership_ctx.assert_sibling_held()


@when("request 3 is released")
def when_sibling_released(shared_pool_ownership_ctx):
    """Release and join the exact sibling worker."""
    shared_pool_ownership_ctx.release_sibling_and_follow_up()


@then("the sibling succeeds and exact client workers settle")
def then_sibling_settled(shared_pool_ownership_ctx):
    """Assert sibling result and exact thread settlement."""
    assert shared_pool_ownership_ctx._sibling_result == ["SIBLING"]
    assert not shared_pool_ownership_ctx._sibling_thread.is_alive()
    assert shared_pool_ownership_ctx.state()["total_requests"] == 4


@then("stale content remains absent after settlement")
def then_stale_absent_after_settlement(first_byte_ownership_ctx):
    """Repeat stale checks after exact server settlement."""
    first_byte_ownership_ctx.assert_settled("FRESH_SECOND")
    assert first_byte_ownership_ctx.sent == ["FRESH_SECOND"]
    assert all("STALE_OLD" not in str(value) for value in first_byte_ownership_ctx.events)
