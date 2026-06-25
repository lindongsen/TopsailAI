"""
Integration tests for ACS message attachments API.

These tests verify creation, retrieval, update, and deletion of messages
that include file/image attachments.

The server accepts message_attachments as either a JSON array (canonical) or a
JSON-encoded string containing an array (backward compatibility), and always
returns it as a parsed JSON array in responses. See docs/API.md and
issues/issue-message-attachments-type-mismatch.md.
"""

import base64
import json
import os
import time

import pytest
import requests
from .conftest import get_response_data


def _resp_data(response: requests.Response) -> dict:
    """Return the JSON payload (conftest monkey-patches get_response_data(response) to unwrap the envelope)."""
    return get_response_data(response)


def _make_attachment(data: str, size: int, fmt: str) -> dict:
    """Build a single attachment payload."""
    return {"data": data, "size": size, "format": fmt}


def _attachment_string(attachments: list[dict]) -> str:
    """Encode attachments as a JSON string for backward-compatibility tests."""
    return json.dumps(attachments)


def _png_pixel() -> str:
    """Return a tiny valid base64-encoded 1x1 PNG."""
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )


class TestCreateMessageAttachments:
    """Test creating messages with attachments."""

    def test_create_message_with_single_attachment(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-001: A message can be created with one attachment using a JSON array."""
        attachment = _make_attachment(_png_pixel(), 67, "image/png")
        message_data = {
            "message_text": "See this image",
            "message_attachments": [attachment],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201, f"Failed to create message: {response.text}"

        data = get_response_data(response)
        assert data["message_text"] == message_data["message_text"]
        assert "message_attachments" in data
        stored = data["message_attachments"]
        assert isinstance(stored, list)
        assert len(stored) == 1
        assert stored[0]["data"] == attachment["data"]
        assert stored[0]["size"] == attachment["size"]
        assert stored[0]["format"] == attachment["format"]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{data['message_id']}"
        )

    def test_create_message_with_multiple_attachments(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-002: A message can include multiple attachments as a JSON array."""
        attachments = [
            _make_attachment(_png_pixel(), 1024, "image/png"),
            _make_attachment("JVBERi0xLjQKJcOkw7zDtsO8CjIgMCBvYmoKPDwKL0xlbmd0aCAzIDAgUgovRmlsdGVyIC9GbGF0ZURlY29kZQo+PgpzdHJlYW0KeJzLSMxLLUmNzNFLzs8rzi9KycxLt4IDAIvJBw4KZW5kc3RyZWFtCmVuZG9iago=", 2048, "application/pdf"),
        ]
        message_data = {
            "message_text": "Here are two files",
            "message_attachments": attachments,
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201, f"Failed to create message: {response.text}"

        data = get_response_data(response)
        stored = data["message_attachments"]
        assert isinstance(stored, list)
        assert len(stored) == 2
        for idx, att in enumerate(attachments):
            assert stored[idx]["data"] == att["data"]
            assert stored[idx]["size"] == att["size"]
            assert stored[idx]["format"] == att["format"]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{data['message_id']}"
        )

    def test_create_message_with_s3_url_attachment(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-008: Attachment data can be an S3 URL."""
        attachment = _make_attachment("s3://bucket/path/object.png", 1024, "image/png")
        message_data = {
            "message_text": "See this S3 file",
            "message_attachments": [attachment],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201, f"Failed to create message: {response.text}"

        data = get_response_data(response)
        stored = data["message_attachments"]
        assert stored[0]["data"] == "s3://bucket/path/object.png"

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{data['message_id']}"
        )

    def test_create_message_with_empty_attachments_array(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-011: Empty attachments array is accepted."""
        message_data = {
            "message_text": "No attachments",
            "message_attachments": [],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201, f"Failed to create message: {response.text}"

        data = get_response_data(response)
        assert data["message_attachments"] == []

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{data['message_id']}"
        )

    def test_create_message_with_invalid_attachment_format(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-010: Invalid attachment structure is stored as-is (no schema validation)."""
        message_data = {
            "message_text": "Bad attachment",
            "message_attachments": [{"data": "missing-size-and-format"}],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201, f"Unexpected response: {response.text}"

        data = get_response_data(response)
        stored = data["message_attachments"]
        assert stored == [{"data": "missing-size-and-format"}]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{data['message_id']}"
        )

    def test_create_message_with_large_attachment(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-009: Reasonably large base64 attachments are accepted."""
        # ~1 MB of raw data -> ~1.33 MB base64 string
        raw = os.urandom(1024 * 1024)
        b64 = base64.b64encode(raw).decode("utf-8")
        attachment = _make_attachment(b64, len(raw), "application/octet-stream")

        message_data = {
            "message_text": "Large attachment",
            "message_attachments": [attachment],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201, f"Failed to create large message: {response.text}"

        data = get_response_data(response)
        stored = data["message_attachments"]
        assert len(stored) == 1
        assert stored[0]["size"] == attachment["size"]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{data['message_id']}"
        )

    def test_create_message_with_stringified_array_backward_compatible(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-013: Stringified JSON array input remains accepted for backward compatibility."""
        attachment = _make_attachment(_png_pixel(), 67, "image/png")
        message_data = {
            "message_text": "Backward compatible attachment",
            "message_attachments": _attachment_string([attachment]),
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201, f"Failed to create message: {response.text}"

        data = get_response_data(response)
        stored = data["message_attachments"]
        assert isinstance(stored, list)
        assert len(stored) == 1
        assert stored[0]["data"] == attachment["data"]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{data['message_id']}"
        )

    def test_create_message_with_invalid_attachments_rejected(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-014: Non-array or invalid JSON attachments are rejected."""
        for bad_value in ("not-json", {"data": "object-not-allowed"}):
            message_data = {
                "message_text": "Bad attachment",
                "message_attachments": bad_value,
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 400, (
                f"Expected 400 for {bad_value!r}, got {response.status_code}: {response.text}"
            )


class TestRetrieveMessageAttachments:
    """Test retrieving messages with attachments."""

    def test_list_messages_includes_attachments(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-003: Listing messages returns attachments as arrays."""
        attachment = _make_attachment(_png_pixel(), 67, "image/png")
        message_data = {
            "message_text": "See this image",
            "message_attachments": [attachment],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201
        message_id = get_response_data(response)["message_id"]

        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages"
        )
        assert response.status_code == 200

        data = _resp_data(response)
        found = [m for m in data["items"] if m["message_id"] == message_id]
        assert len(found) == 1
        stored = found[0]["message_attachments"]
        assert isinstance(stored, list)
        assert len(stored) == 1
        assert stored[0]["data"] == attachment["data"]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )

    def test_get_message_includes_attachments(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-004: Getting a single message returns attachments as arrays.

        Note: ACS does not expose a dedicated GET /messages/{message_id} endpoint,
        so we verify via the list endpoint.
        """
        attachment = _make_attachment(_png_pixel(), 67, "image/png")
        message_data = {
            "message_text": "See this image",
            "message_attachments": [attachment],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201
        message_id = get_response_data(response)["message_id"]

        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages"
        )
        data = _resp_data(response)
        found = [m for m in data["items"] if m["message_id"] == message_id]
        assert len(found) == 1
        stored = found[0]["message_attachments"]
        assert isinstance(stored, list)
        assert stored[0]["data"] == attachment["data"]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )


class TestUpdateMessageAttachments:
    """Test updating messages with attachments."""

    def test_update_message_text_preserves_attachments(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-005: Updating only message_text preserves attachments."""
        attachment = _make_attachment(_png_pixel(), 67, "image/png")
        message_data = {
            "message_text": "Original text",
            "message_attachments": [attachment],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201
        message_id = get_response_data(response)["message_id"]

        update_data = {"message_text": "Updated text"}
        response = api_client.put(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}",
            json=update_data,
        )
        assert response.status_code == 200

        data = get_response_data(response)
        assert data["message_text"] == "Updated text"
        stored = data["message_attachments"]
        assert isinstance(stored, list)
        assert len(stored) == 1
        assert stored[0]["data"] == attachment["data"]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )

    def test_update_message_attachments_replaces_list(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-006: Updating message_attachments replaces the list."""
        old_attachment = _make_attachment(_png_pixel(), 67, "image/png")
        message_data = {
            "message_text": "Original",
            "message_attachments": [old_attachment],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201
        message_id = get_response_data(response)["message_id"]

        new_attachment = _make_attachment("new-base64-data", 512, "image/jpeg")
        update_data = {"message_attachments": [new_attachment]}
        response = api_client.put(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}",
            json=update_data,
        )
        assert response.status_code == 200

        data = get_response_data(response)
        stored = data["message_attachments"]
        assert isinstance(stored, list)
        assert len(stored) == 1
        assert stored[0]["data"] == new_attachment["data"]
        assert stored[0]["size"] == new_attachment["size"]
        assert stored[0]["format"] == new_attachment["format"]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )

    def test_update_message_removes_attachments(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """Updating message_attachments to an empty list removes attachments."""
        message_data = {
            "message_text": "With attachment",
            "message_attachments": [_make_attachment(_png_pixel(), 67, "image/png")],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201
        message_id = get_response_data(response)["message_id"]

        response = api_client.put(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}",
            json={"message_attachments": []},
        )
        assert response.status_code == 200

        data = get_response_data(response)
        assert data["message_attachments"] == []

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )


class TestDeleteMessageAttachments:
    """Test deleting messages with attachments."""

    def test_delete_message_with_attachments_clears_content(
        self, api_client: requests.Session, server_url: str, test_group: dict
    ):
        """TC-INT-ATT-007: Soft-deleting a message clears content and attachments."""
        message_data = {
            "message_text": "Will be deleted",
            "message_attachments": [_make_attachment(_png_pixel(), 67, "image/png")],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201
        message_id = get_response_data(response)["message_id"]

        response = api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )
        assert response.status_code in (200, 204)

        response = api_client.get(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            params={"include_deleted": "true"},
        )
        assert response.status_code == 200

        data = _resp_data(response)
        found = [m for m in data["items"] if m["message_id"] == message_id]
        assert len(found) == 1
        assert found[0]["is_deleted"] is True
        assert found[0]["message_text"] == ""
        assert found[0]["message_attachments"] == []


class TestAttachmentOwnership:
    """Test ownership rules for messages with attachments."""

    def test_non_sender_cannot_update_message_with_attachments(
        self,
        api_client: requests.Session,
        admin_client: requests.Session,
        server_url: str,
        test_group: dict,
        test_account_with_api_key: tuple,
    ):
        """TC-INT-ATT-009: Only sender or admin can update a message with attachments."""
        account, token = test_account_with_api_key

        member_data = {
            "member_id": account["account_id"],
            "member_name": account["account_name"].replace(" ", "_"),
            "member_description": "Test user",
            "member_type": "user",
        }
        response = admin_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
            json=member_data,
        )
        assert response.status_code == 201

        user_session = requests.Session()
        user_session.headers.update({"Content-Type": "application/json"})
        user_session.headers.update({"Authorization": f"Bearer {token}"})

        message_data = {
            "message_text": "User message",
            "message_attachments": [_make_attachment(_png_pixel(), 67, "image/png")],
        }
        response = user_session.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201
        message_id = get_response_data(response)["message_id"]

        # Admin can update
        response = admin_client.put(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}",
            json={"message_text": "Admin updated"},
        )
        assert response.status_code == 200

        # Create another user account and try to update the message
        other_account_data = {
            "account_name": f"Other User {int(time.time() * 1000)}",
            "account_description": "Another test user",
            "role": "user",
            "login_name": f"other_user_{int(time.time() * 1000)}",
            "login_password": "TestPass123!",
        }
        response = admin_client.post(
            f"{server_url}/api/v1/accounts", json=other_account_data
        )
        assert response.status_code == 201
        other_account = get_response_data(response)

        key_data = {"api_key_name": "other-key", "role": "user"}
        response = admin_client.post(
            f"{server_url}/api/v1/accounts/{other_account['account_id']}/api-keys",
            json=key_data,
        )
        assert response.status_code == 201
        other_token = get_response_data(response)["token"]

        other_member_data = {
            "member_id": other_account["account_id"],
            "member_name": other_account["account_name"].replace(" ", "_"),
            "member_description": "Other test user",
            "member_type": "user",
        }
        response = admin_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
            json=other_member_data,
        )
        assert response.status_code == 201

        other_session = requests.Session()
        other_session.headers.update({"Content-Type": "application/json"})
        other_session.headers.update({"Authorization": f"Bearer {other_token}"})

        response = other_session.put(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}",
            json={"message_text": "Other user updated"},
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"

        user_session.close()
        other_session.close()
        admin_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{message_id}"
        )
        admin_client.delete(
            f"{server_url}/api/v1/accounts/{other_account['account_id']}"
        )


class TestMentionsWithAttachments:
    """Test mentions and attachments together."""

    def test_mentions_and_attachments_together(
        self,
        api_client: requests.Session,
        server_url: str,
        test_group: dict,
        test_agent_member: dict,
    ):
        """TC-INT-ATT-012: A message can include both mentions and attachments."""
        attachment = _make_attachment(_png_pixel(), 67, "image/png")
        message_text = f"@{test_agent_member['member_id']} please analyze this image"
        message_data = {
            "message_text": message_text,
            "message_attachments": [attachment],
        }

        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201, f"Failed to create message: {response.text}"

        data = get_response_data(response)
        assert data["message_text"] == message_text
        assert "mentions" in data
        mentions = data["mentions"]
        assert len(mentions) >= 1
        assert any(m["member_id"] == test_agent_member["member_id"] for m in mentions)
        stored = data["message_attachments"]
        assert isinstance(stored, list)
        assert len(stored) == 1
        assert stored[0]["data"] == attachment["data"]

        api_client.delete(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/messages/{data['message_id']}"
        )
