"""
NATS message event tests for ACS.

Validates that message create/modify/delete events are published to the
group event subject and can be consumed by NATS subscribers.

These tests cover the real-time chat behavior described in the manual CLI
test plan (CLI-CHAT-002 through CLI-CHAT-008) at the API/NATS level.
"""

import asyncio
import json
import time
from typing import Any

import nats
import pytest
import pytest_asyncio

from .conftest import get_response_data


SUBJECT_PREFIX = "acs.group.message"


@pytest.fixture(scope="function")
def event_subject(test_group: dict) -> str:
    """Return the NATS subject for the test group's events."""
    return f"{SUBJECT_PREFIX}.{test_group['group_id']}"


@pytest_asyncio.fixture(scope="function")
async def event_subscriber(nats_client: nats.NATS, event_subject: str):
    """Create a NATS subscriber that collects events for the test group."""
    events: list[dict[str, Any]] = []

    async def handler(msg: nats.aio.msg.Msg):
        payload = json.loads(msg.data.decode("utf-8"))
        events.append(payload)
        await msg.ack()

    sub = await nats_client.subscribe(event_subject, cb=handler)
    # Allow subscription to propagate.
    await asyncio.sleep(0.2)

    yield events

    await sub.unsubscribe()


@pytest.fixture(scope="function")
def current_account_id(api_client, server_url: str) -> str:
    """Return the account_id of the authenticated API client."""
    response = api_client.get(f"{server_url}/api/v1/accounts/me")
    assert response.status_code == 200, f"Failed to get current account: {response.text}"
    data = get_response_data(response)
    return data["account_id"]


class TestMessageCreateEvents:
    """Verify message create events are published to NATS."""

    @pytest.mark.asyncio
    async def test_message_create_event_published(
        self,
        api_client,
        server_url: str,
        test_group: dict,
        current_account_id: str,
        event_subscriber: list,
    ):
        """CLI-CHAT-002: sending a message publishes a create event."""
        text = f"Hello from event test {time.time_ns()}"
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json={"message_text": text},
        )
        assert response.status_code == 201
        msg = get_response_data(response)

        # The API derives sender_id from the authenticated account, not from
        # any member_id supplied in the request body.
        assert msg["sender_id"] == current_account_id
        assert msg["sender_type"] == "user"

        # Wait for the event to arrive.
        await asyncio.sleep(0.5)

        create_events = [
            e for e in event_subscriber
            if e.get("type") == "message" and e.get("action") == "create"
        ]
        assert len(create_events) >= 1, f"No create event received: {event_subscriber}"

        data = create_events[-1].get("data", {})
        assert data.get("message_id") == msg["message_id"]
        assert data.get("message_text") == text
        assert data.get("sender_id") == current_account_id


class TestMessageEditEvents:
    """Verify message modify events are published to NATS."""

    @pytest.mark.asyncio
    async def test_message_edit_event_published(
        self,
        api_client,
        server_url: str,
        test_group: dict,
        test_message: dict,
        event_subscriber: list,
    ):
        """CLI-CHAT-003: editing a message publishes a modify event."""
        new_text = f"Edited text {time.time_ns()}"
        response = api_client.put(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{test_message['message_id']}",
            json={"message_text": new_text},
        )
        assert response.status_code == 200

        await asyncio.sleep(0.5)

        modify_events = [
            e for e in event_subscriber
            if e.get("type") == "message" and e.get("action") == "modify"
        ]
        assert len(modify_events) >= 1, f"No modify event received: {event_subscriber}"

        data = modify_events[-1].get("data", {})
        assert data.get("message_id") == test_message["message_id"]


class TestMessageDeleteEvents:
    """Verify message delete events are published to NATS."""

    @pytest.mark.asyncio
    async def test_message_delete_event_published(
        self,
        api_client,
        server_url: str,
        test_group: dict,
        test_message: dict,
        event_subscriber: list,
    ):
        """CLI-CHAT-004: deleting a message publishes a delete event."""
        response = api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{test_message['message_id']}"
        )
        assert response.status_code == 200

        await asyncio.sleep(0.5)

        delete_events = [
            e for e in event_subscriber
            if e.get("type") == "message" and e.get("action") == "delete"
        ]
        assert len(delete_events) >= 1, f"No delete event received: {event_subscriber}"

        data = delete_events[-1].get("data", {})
        assert data.get("message_id") == test_message["message_id"]


class TestMemberJoinLeaveEvents:
    """Verify group_member events are published to NATS."""

    @pytest.mark.asyncio
    async def test_member_join_event_published(
        self,
        api_client,
        server_url: str,
        test_group: dict,
        unique_id: str,
        event_subscriber: list,
    ):
        """CLI-CHAT-005: member join publishes a group_member create event."""
        member_id = f"user-event-{unique_id}"
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
            json={
                "member_id": member_id,
                "member_name": f"EventUser_{unique_id}",
                "member_type": "user",
            },
        )
        assert response.status_code == 201

        await asyncio.sleep(0.5)

        join_events = [
            e for e in event_subscriber
            if e.get("type") == "group_member" and e.get("action") == "create"
        ]
        assert len(join_events) >= 1, f"No join event received: {event_subscriber}"

        data = join_events[-1].get("data", {})
        assert data.get("member_id") == member_id

    @pytest.mark.asyncio
    async def test_member_leave_event_published(
        self,
        api_client,
        server_url: str,
        test_group: dict,
        test_member: dict,
        event_subscriber: list,
    ):
        """CLI-CHAT-006: member leave publishes a group_member delete event."""
        response = api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members/{test_member['member_id']}"
        )
        assert response.status_code == 204

        await asyncio.sleep(0.5)

        leave_events = [
            e for e in event_subscriber
            if e.get("type") == "group_member" and e.get("action") == "delete"
        ]
        assert len(leave_events) >= 1, f"No leave event received: {event_subscriber}"

        data = leave_events[-1].get("data", {})
        assert data.get("member_id") == test_member["member_id"]
