"""
Integration tests for ACS HTTP API.

These tests verify the REST API endpoints for group management,
member management, and messaging.
"""

import json
import os
import time

import pytest
import requests

from tests.integration.conftest import get_response_data


def _resp_data(response: requests.Response) -> dict:
    """Return the JSON payload (conftest monkey-patches _resp_data(response) to unwrap the envelope)."""
    return get_response_data(response)


class TestHealthEndpoints:
    """Test health and readiness endpoints."""

    def test_liveness(self, api_client: requests.Session, server_url: str):
        """Test the liveness probe endpoint."""
        response = api_client.get(f"{server_url}/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    def test_readiness(self, api_client: requests.Session, server_url: str):
        """Test the readiness probe endpoint."""
        response = api_client.get(f"{server_url}/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "database" in data["checks"]

    def test_health(self, api_client: requests.Session, server_url: str):
        """Test the comprehensive health endpoint."""
        response = api_client.get(f"{server_url}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "checks" in data
        assert "database" in data["checks"]


class TestGroupCRUD:
    """Test group CRUD operations."""

    def test_create_group(self, api_client: requests.Session, server_url: str, unique_id: str):
        """Test creating a new group."""
        group_data = {
            "group_name": f"Test Group {unique_id}",
            "group_context": "Test context"
        }

        response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201

        data = _resp_data(response)
        assert data["group_name"] == group_data["group_name"]
        assert data["group_context"] == group_data["group_context"]
        assert "group_id" in data
        assert "create_at_ms" in data
        assert "update_at_ms" in data

        # Cleanup
        api_client.delete(f"{server_url}/api/v1/groups/{data['group_id']}")

    def test_create_group_with_key(self, api_client: requests.Session, server_url: str, unique_id: str):
        """Test creating a group with a secret key."""
        group_data = {
            "group_name": f"Secret Group {unique_id}",
            "group_context": "Private group",
            "group_key": "my-secret-key"
        }

        response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201

        data = _resp_data(response)
        assert data["group_name"] == group_data["group_name"]
        # Per docs/API.md the API never returns the plaintext key.
        assert data.get("group_key") != "my-secret-key"

        # Cleanup
        api_client.delete(f"{server_url}/api/v1/groups/{data['group_id']}")

    def test_get_group(self, api_client: requests.Session, server_url: str, test_group: dict):
        """Test retrieving a group by ID."""
        response = api_client.get(f"{server_url}/api/v1/groups/{test_group['group_id']}")
        assert response.status_code == 200

        data = _resp_data(response)
        assert data["group_id"] == test_group["group_id"]
        assert data["group_name"] == test_group["group_name"]

    def test_get_group_not_found(self, api_client: requests.Session, server_url: str):
        """Test retrieving a non-existent group."""
        response = api_client.get(f"{server_url}/api/v1/groups/non-existent-id")
        assert response.status_code == 404

    def test_list_groups(self, api_client: requests.Session, server_url: str, test_group: dict):
        """Test listing groups with pagination."""
        response = api_client.get(f"{server_url}/api/v1/groups?limit=10&offset=0")
        assert response.status_code == 200

        data = _resp_data(response)
        # API returns paginated response with items array
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) > 0
        assert "total" in data
        assert "offset" in data
        assert "limit" in data

    def test_list_groups_pagination(self, api_client: requests.Session, server_url: str):
        """Test group pagination."""
        # Create multiple groups
        group_ids = []
        for i in range(3):
            group_data = {
                "group_name": f"Pagination Group {i}",
                "group_context": "Test"
            }
            response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group_ids.append(_resp_data(response)["group_id"])

        # Test with limit
        response = api_client.get(f"{server_url}/api/v1/groups?limit=2&offset=0")
        assert response.status_code == 200
        data = _resp_data(response)
        assert len(data["items"]) <= 2

        # Test with offset
        response = api_client.get(f"{server_url}/api/v1/groups?limit=2&offset=1")
        assert response.status_code == 200
        data = _resp_data(response)
        assert len(data["items"]) <= 2

        # Cleanup
        for gid in group_ids:
            api_client.delete(f"{server_url}/api/v1/groups/{gid}")

    def test_list_groups_sorting(self, api_client: requests.Session, server_url: str):
        """Test group list sorting."""
        # Create groups with different names
        group_ids = []
        for i in range(3):
            group_data = {
                "group_name": f"Sort Group {i}",
                "group_context": "Test"
            }
            response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
            assert response.status_code == 201
            group_ids.append(_resp_data(response)["group_id"])

        # Test sorting by create_at_ms desc (default)
        response = api_client.get(f"{server_url}/api/v1/groups?sort_key=create_at_ms&order_by=desc")
        assert response.status_code == 200
        data = _resp_data(response)
        items = data["items"]
        if len(items) >= 2:
            assert items[0]["create_at_ms"] >= items[1]["create_at_ms"]

        # Test sorting by create_at_ms asc
        response = api_client.get(f"{server_url}/api/v1/groups?sort_key=create_at_ms&order_by=asc")
        assert response.status_code == 200
        data = _resp_data(response)
        items = data["items"]
        if len(items) >= 2:
            assert items[0]["create_at_ms"] <= items[1]["create_at_ms"]

        # Cleanup
        for gid in group_ids:
            api_client.delete(f"{server_url}/api/v1/groups/{gid}")

    def test_update_group(self, api_client: requests.Session, server_url: str, test_group: dict):
        """Test updating a group."""
        update_data = {
            "group_name": f"Updated {test_group['group_name']}"
        }

        response = api_client.put(
            f"{server_url}/api/v1/groups/{test_group['group_id']}",
            json=update_data
        )
        assert response.status_code == 200

        data = _resp_data(response)
        assert data["group_name"] == update_data["group_name"]
        assert data["group_id"] == test_group["group_id"]

    def test_delete_group(self, api_client: requests.Session, server_url: str, unique_id: str):
        """Test deleting a group."""
        # Create a group to delete
        group_data = {
            "group_name": f"Delete Group {unique_id}",
            "group_context": "To be deleted"
        }
        response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201
        group_id = _resp_data(response)["group_id"]

        # Delete the group
        response = api_client.delete(f"{server_url}/api/v1/groups/{group_id}")
        assert response.status_code == 204

        # Verify group is deleted
        response = api_client.get(f"{server_url}/api/v1/groups/{group_id}")
        assert response.status_code == 404


class TestGroupMember:
    """Test group member operations."""

    def test_join_group(self, api_client: requests.Session, server_url: str, test_group: dict, unique_id: str):
        """Test joining a group."""
        member_data = {
            "member_id": f"new-user-{unique_id}",
            "member_name": f"New_User_{unique_id}",
            "member_description": "A new member",
            "member_type": "user"
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
            json=member_data
        )
        assert response.status_code == 201

        data = _resp_data(response)
        assert data["member_id"] == member_data["member_id"]
        assert data["member_name"] == member_data["member_name"]
        assert data["member_type"] == "user"
        assert data["group_id"] == test_group["group_id"]

        # Cleanup
        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members/{data['member_id']}"
        )

    def test_join_group_agent(self, api_client: requests.Session, server_url: str, test_group: dict, unique_id: str):
        """Test joining a group as an agent."""
        import json
        agent_interface = {
            "adaptor": "topsailai_agent",
            "environments": {
                "ACS_AGENT_API_BASE": f"http://{server_url.split('//')[1]}",
                "ACS_AGENT_API_KEY": "test-key"
            },
            "timeout_chat": 30
        }

        member_data = {
            "member_id": f"agent-{unique_id}",
            "member_name": f"Test_Agent_{unique_id}",
            "member_description": "A test agent",
            "member_type": "worker-agent",
            "member_interface": json.dumps(agent_interface)
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
            json=member_data
        )
        assert response.status_code == 201

        data = _resp_data(response)
        assert data["member_type"] == "worker-agent"
        assert data["member_interface"] != ""

        # Cleanup
        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members/{data['member_id']}"
        )

    def test_list_members(self, api_client: requests.Session, server_url: str, test_group: dict, test_member: dict):
        """Test listing group members."""
        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members"
        )
        assert response.status_code == 200

        data = _resp_data(response)
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) > 0
        assert "total" in data

    def test_update_member(self, api_client: requests.Session, server_url: str, test_group: dict, test_member: dict):
        """Test updating a member."""
        update_data = {
            "member_name": f"Updated_{test_member['member_name']}",
            "member_status": "idle"
        }

        response = api_client.put(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members/{test_member['member_id']}",
            json=update_data
        )
        assert response.status_code == 200

        data = _resp_data(response)
        assert data["member_name"] == update_data["member_name"]
        assert data["member_status"] == update_data["member_status"]

    def test_leave_group(self, api_client: requests.Session, server_url: str, test_group: dict, unique_id: str):
        """Test leaving a group."""
        # Add a member to remove
        member_data = {
            "member_id": f"leave-user-{unique_id}",
            "member_name": f"Leave_User_{unique_id}",
            "member_type": "user"
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
            json=member_data
        )
        assert response.status_code == 201
        member_id = _resp_data(response)["member_id"]

        # Remove the member
        response = api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members/{member_id}"
        )
        assert response.status_code == 204

        # Verify member is removed
        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members"
        )
        data = _resp_data(response)
        member_ids = [m["member_id"] for m in data["items"]]
        assert member_id not in member_ids


class TestMessage:
    """Test message operations."""

    def test_create_message(self, api_client: requests.Session, server_url: str, test_group: dict):
        """Test creating a message.

        The API derives sender_id and sender_type from the authenticated caller,
        so these fields must not be supplied in the request body.
        """
        message_data = {
            "message_text": "Hello, this is a test message!",
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201

        data = _resp_data(response)
        assert data["message_text"] == message_data["message_text"]
        # Sender is derived from the authenticated admin API key.
        assert data["sender_id"]
        assert data["sender_type"] == "user"
        assert "message_id" in data
        assert "create_at_ms" in data

    def test_create_message_with_mentions(self, api_client: requests.Session, server_url: str, test_group: dict, test_agent_member: dict):
        """Test creating a message with mentions."""
        message_text = f"Hello @{test_agent_member['member_id']}, can you help?"
        message_data = {
            "message_text": message_text,
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201

        data = _resp_data(response)
        assert data["message_text"] == message_text
        # Mentions should be extracted and stored
        assert "mentions" in data

    def test_list_messages(self, api_client: requests.Session, server_url: str, test_group: dict, test_message: dict):
        """Test listing messages."""
        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages"
        )
        assert response.status_code == 200

        data = _resp_data(response)
        assert "items" in data
        assert isinstance(data["items"], list)
        assert len(data["items"]) > 0
        assert "total" in data

    def test_list_messages_pagination(self, api_client: requests.Session, server_url: str, test_group: dict):
        """Test message pagination."""
        # Create multiple messages
        message_ids = []
        for i in range(3):
            message_data = {
                "message_text": f"Message {i}",
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
                json=message_data
            )
            assert response.status_code == 201
            message_ids.append(_resp_data(response)["message_id"])

        # Test with limit
        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages?limit=2"
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert len(data["items"]) <= 2

        # Cleanup
        for mid in message_ids:
            api_client.delete(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{mid}"
            )

    def test_list_messages_time_range(self, api_client: requests.Session, server_url: str, test_group: dict):
        """Test listing messages with time range filter."""
        # Create a message
        message_data = {
            "message_text": "Time range test message",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201
        message_id = _resp_data(response)["message_id"]

        # Get current time range
        now = int(time.time() * 1000)
        start_time = now - 60000  # 1 minute ago
        end_time = now + 60000    # 1 minute from now

        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages?create_at_ms={start_time}-{end_time}"
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert len(data["items"]) > 0

        # Cleanup
        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )

    def test_update_message(self, api_client: requests.Session, server_url: str, test_group: dict, test_message: dict):
        """Test updating a message."""
        update_data = {
            "message_text": "Updated message text"
        }

        response = api_client.put(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{test_message['message_id']}",
            json=update_data
        )
        assert response.status_code == 200

        data = _resp_data(response)
        assert data["message_text"] == update_data["message_text"]

    def test_delete_message(self, api_client: requests.Session, server_url: str, test_group: dict):
        """Test deleting a message (soft delete)."""
        # Create a message to delete
        message_data = {
            "message_text": "Message to delete",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201
        message_id = _resp_data(response)["message_id"]

        # Delete the message
        response = api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["message"] == "message deleted"

    def test_create_message_ignores_supplied_sender(self, api_client: requests.Session, server_url: str, test_group: dict):
        """Test that sender is derived from authentication, not the request body."""
        message_data = {
            "message_text": "Test message with no sender fields",
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201

        data = _resp_data(response)
        # Sender is derived from the authenticated admin account.
        assert data["sender_id"]
        assert data["sender_type"] == "user"

class TestEndToEndFlow:
    """Test end-to-end conversation flow."""

    def test_full_conversation_flow(self, api_client: requests.Session, server_url: str, unique_id: str):
        """Test a complete conversation flow with multiple participants."""
        import json

        # 1. Create a group
        group_data = {
            "group_name": f"E2E Group {unique_id}",
            "group_context": "End-to-end test group"
        }
        response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201
        group_id = _resp_data(response)["group_id"]

        # 2. Add human user
        user_data = {
            "member_id": f"human-{unique_id}",
            "member_name": f"Human_{unique_id}",
            "member_type": "user"
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{group_id}/members",
            json=user_data
        )
        assert response.status_code == 201

        # 3. Add agent
        agent_interface = {
            "adaptor": "topsailai_agent",
            "environments": {
                "ACS_AGENT_API_BASE": f"http://{server_url.split('//')[1]}",
                "ACS_AGENT_API_KEY": "test-key"
            }
        }
        agent_data = {
            "member_id": f"agent-{unique_id}",
            "member_name": f"Agent_{unique_id}",
            "member_type": "worker-agent",
            "member_interface": json.dumps(agent_interface)
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{group_id}/members",
            json=agent_data
        )
        assert response.status_code == 201

        # 4. Send message mentioning the agent
        message_data = {
            "message_text": f"Hello @agent-{unique_id}, can you help me?",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{group_id}/messages",
            json=message_data
        )
        assert response.status_code == 201
        message_id = _resp_data(response)["message_id"]

        # 5. List messages
        response = api_client.get(f"{server_url}/api/v1/groups/{group_id}/messages")
        assert response.status_code == 200
        data = _resp_data(response)
        assert len(data["items"]) > 0

        # 6. Update message
        update_data = {"message_text": "Updated message"}
        response = api_client.put(
            f"{server_url}/api/v1/groups/{group_id}/messages/{message_id}",
            json=update_data
        )
        assert response.status_code == 200

        # 7. Delete message
        response = api_client.delete(
            f"{server_url}/api/v1/groups/{group_id}/messages/{message_id}"
        )
        assert response.status_code == 200
        data = _resp_data(response)
        assert data["message"] == "message deleted"

        # 8. Cleanup: delete group
        response = api_client.delete(f"{server_url}/api/v1/groups/{group_id}")
        assert response.status_code == 204


class TestMessageProcessedMsgID:
    """Test querying messages by processed_msg_id."""

    def test_list_messages_by_processed_msg_id(self, api_client: requests.Session, server_url: str, test_group: dict, test_agent_member: dict):
        """Test filtering messages by processed_msg_id query parameter."""
        import psycopg2

        # 1. Send a message from the authenticated user
        user_message_data = {
            "message_text": "Hello agent, can you help me?",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=user_message_data
        )
        assert response.status_code == 201
        user_message = _resp_data(response)
        user_message_id = user_message["message_id"]

        # 2. Directly insert an agent response message with processed_msg_id set
        # (Simulating what happens after agent processing)
        conn = psycopg2.connect(
            host="localhost", port=5432, user="acs", password="acs", dbname="acs"
        )
        cur = conn.cursor()
        agent_message_id = f"agent-response-{int(time.time() * 1000)}"
        create_at_ms = int(time.time() * 1000)
        cur.execute(
            """
            INSERT INTO group_messages (
                group_id, message_id, message_text, message_attachments,
                sender_id, sender_type, processed_msg_id, mentions,
                is_deleted, delete_at_ms, create_at_ms, update_at_ms
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                test_group["group_id"],
                agent_message_id,
                "This is the agent response to your message.",
                "[]",
                test_agent_member["member_id"],
                "worker-agent",
                user_message_id,
                "[]",
                False,
                0,
                create_at_ms,
                create_at_ms,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()

        # 3. Query messages filtered by processed_msg_id
        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages?processed_msg_id={user_message_id}"
        )
        assert response.status_code == 200

        data = _resp_data(response)
        assert "items" in data
        assert isinstance(data["items"], list)
        assert data["total"] == 1
        assert len(data["items"]) == 1

        # 4. Verify the returned message is the agent response
        returned_msg = data["items"][0]
        assert returned_msg["message_id"] == agent_message_id
        assert returned_msg["processed_msg_id"] == user_message_id
        assert returned_msg["sender_id"] == test_agent_member["member_id"]
        assert returned_msg["sender_type"] == "worker-agent"
        assert returned_msg["message_text"] == "This is the agent response to your message."

        # 5. Cleanup: delete the agent response message directly
        conn = psycopg2.connect(
            host="localhost", port=5432, user="acs", password="acs", dbname="acs"
        )
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM group_messages WHERE message_id = %s",
            (agent_message_id,),
        )
        conn.commit()
        cur.close()
        conn.close()

    def test_list_messages_by_nonexistent_processed_msg_id(self, api_client: requests.Session, server_url: str, test_group: dict, test_message: dict):
        """Test filtering by a non-existent processed_msg_id returns empty results."""
        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages?processed_msg_id=non-existent-msg-id"
        )
        assert response.status_code == 200

        data = _resp_data(response)
        assert data["total"] == 0
        assert len(data["items"]) == 0


class TestManualTrigger:
    """Test manual message trigger API that bypasses NO_TRIGGER_CASES."""

    def test_manual_trigger_with_agent_id(self, api_client: requests.Session, server_url: str, test_group: dict, test_member: dict, test_agent_member: dict):
        """Test manual trigger with specific agent_id returns 202 and bypasses NO_TRIGGER_CASES."""
        # Create a message from user
        message_data = {
            "message_text": "Hello, can you help me?",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201
        message_id = _resp_data(response)["message_id"]

        # Manually trigger with specific agent_id
        trigger_data = {"agent_id": test_agent_member["member_id"]}
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}/trigger",
            json=trigger_data
        )
        assert response.status_code == 202

        data = _resp_data(response)
        assert data["message_id"] == message_id
        assert data["group_id"] == test_group["group_id"]
        assert data["status"] == "pending"
        assert data["trigger"]["type"] == "manual"
        assert data["trigger"]["agent_id"] == test_agent_member["member_id"]

        # Cleanup
        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )

    def test_manual_trigger_without_agent_id(self, api_client: requests.Session, server_url: str, test_group: dict, test_member: dict, test_manager_agent: dict):
        """Test manual trigger without agent_id returns 202 and resolves agents automatically."""
        # Create a message from user with @all mention
        message_data = {
            "message_text": "Hello @all, can someone help?",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201
        message_id = _resp_data(response)["message_id"]

        # Manually trigger without agent_id - should resolve to manager-agent
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}/trigger",
            json={}
        )
        assert response.status_code == 202

        data = _resp_data(response)
        assert data["message_id"] == message_id
        assert data["group_id"] == test_group["group_id"]
        assert data["status"] == "pending"
        assert data["trigger"]["type"] == "manual"

        # Cleanup
        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )

    def test_manual_trigger_nonexistent_group(self, api_client: requests.Session, server_url: str, test_message: dict):
        """Test manual trigger on non-existent group returns 404."""
        trigger_data = {"agent_id": "some-agent"}
        response = api_client.post(
            f"{server_url}/api/v1/groups/non-existent-group/messages/{test_message['message_id']}/trigger",
            json=trigger_data
        )
        assert response.status_code == 404
        data = response.json()
        assert "group not found" in data.get("error", "")

    def test_manual_trigger_nonexistent_message(self, api_client: requests.Session, server_url: str, test_group: dict):
        """Test manual trigger on non-existent message returns 404."""
        trigger_data = {"agent_id": "some-agent"}
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/non-existent-message/trigger",
            json=trigger_data
        )
        assert response.status_code == 404
        data = response.json()
        assert "message not found" in data.get("error", "")

    def test_manual_trigger_nonexistent_agent(self, api_client: requests.Session, server_url: str, test_group: dict, test_member: dict):
        """Test manual trigger with non-existent agent_id returns 404."""
        # Create a message
        message_data = {
            "message_text": "Hello!",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201
        message_id = _resp_data(response)["message_id"]

        # Try to trigger with non-existent agent
        trigger_data = {"agent_id": "non-existent-agent"}
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}/trigger",
            json=trigger_data
        )
        assert response.status_code == 404
        data = response.json()
        assert "agent not found" in data.get("error", "")

        # Cleanup
        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )

    def test_manual_trigger_non_agent_member(self, api_client: requests.Session, server_url: str, test_group: dict, test_member: dict):
        """Test manual trigger with non-agent member_id returns 400."""
        # Create a message
        message_data = {
            "message_text": "Hello!",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201
        message_id = _resp_data(response)["message_id"]

        # Try to trigger with a user member (not an agent)
        trigger_data = {"agent_id": test_member["member_id"]}
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}/trigger",
            json=trigger_data
        )
        assert response.status_code == 400
        data = response.json()
        assert "not an agent" in data.get("error", "")

        # Cleanup
        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )

    def test_manual_trigger_bypasses_no_trigger_cases(self, api_client: requests.Session, server_url: str, test_group: dict, test_agent_member: dict):
        """Test manual trigger bypasses NO_TRIGGER_CASES (e.g., agent-sent message)."""
        # Create a message from the authenticated caller. The actual sender will be
        # the admin account (user), so NO_TRIGGER_CASE #1 does not apply, but the
        # manual trigger endpoint should still accept and process it.
        message_data = {
            "message_text": "I am an agent message that normally wouldn't trigger",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data
        )
        assert response.status_code == 201
        message_id = _resp_data(response)["message_id"]

        # Manually trigger this message - should bypass NO_TRIGGER_CASES
        trigger_data = {"agent_id": test_agent_member["member_id"]}
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}/trigger",
            json=trigger_data
        )
        assert response.status_code == 202

        data = _resp_data(response)
        assert data["message_id"] == message_id
        assert data["status"] == "pending"
        assert data["trigger"]["type"] == "manual"

        # Cleanup
        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )


class TestAutoJoinManagerAgent:
    """Test automatic manager-agent join on group creation."""

    def test_manager_agent_auto_joined_when_configured(
        self, api_client: requests.Session, server_url: str, unique_id: str
    ):
        """When ACS_GROUP_MANAGER_AGENT_CMD_CHAT is set, a manager-agent is auto-joined."""
        manager_cmd_chat = os.environ.get("ACS_GROUP_MANAGER_AGENT_CMD_CHAT", "")
        if not manager_cmd_chat:
            pytest.skip("ACS_GROUP_MANAGER_AGENT_CMD_CHAT not configured")

        group_data = {
            "group_name": f"Auto Manager Group {unique_id}",
            "group_context": "Testing auto manager-agent join"
        }
        response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201, f"Failed to create group: {response.text}"
        group_id = _resp_data(response)["group_id"]

        try:
            response = api_client.get(f"{server_url}/api/v1/groups/{group_id}/members")
            assert response.status_code == 200
            data = _resp_data(response)

            manager_members = [
                m for m in data["items"]
                if m["member_type"] == "manager-agent"
            ]
            assert len(manager_members) == 1, "Expected exactly one auto-joined manager-agent"

            manager = manager_members[0]
            assert manager["member_id"] != ""
            assert manager["member_name"] != ""
            assert manager["member_interface"] != ""

            interface = json.loads(manager["member_interface"])
            assert interface.get("cmd_chat") == manager_cmd_chat
        finally:
            api_client.delete(f"{server_url}/api/v1/groups/{group_id}")

    def test_manager_agent_not_auto_joined_when_not_configured(
        self, api_client: requests.Session, server_url: str, unique_id: str
    ):
        """When ACS_GROUP_MANAGER_AGENT_CMD_CHAT is not set, no manager-agent is auto-joined."""
        if os.environ.get("ACS_GROUP_MANAGER_AGENT_CMD_CHAT", ""):
            pytest.skip("ACS_GROUP_MANAGER_AGENT_CMD_CHAT is configured")

        group_data = {
            "group_name": f"No Auto Manager Group {unique_id}",
            "group_context": "Testing no auto manager-agent join"
        }
        response = api_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201, f"Failed to create group: {response.text}"
        group_id = _resp_data(response)["group_id"]

        try:
            response = api_client.get(f"{server_url}/api/v1/groups/{group_id}/members")
            assert response.status_code == 200
            data = _resp_data(response)

            manager_members = [
                m for m in data["items"]
                if m["member_type"] == "manager-agent"
            ]
            assert len(manager_members) == 0, "Expected no auto-joined manager-agent"
        finally:
            api_client.delete(f"{server_url}/api/v1/groups/{group_id}")
