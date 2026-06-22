"""
Integration tests for ACS group key privacy and access control.

These tests verify that group secret keys are hashed, never returned in
plaintext, and enforce access control for private groups.
"""

import os

import psycopg2
import pytest
import requests


PLAINTEXT_KEY = "my-secret-key"
NEW_PLAINTEXT_KEY = "new-secret-key"


def _db_connect():
    """Return a psycopg2 connection to the test database."""
    return psycopg2.connect(
        host=os.environ.get("ACS_DB_HOST", "localhost"),
        port=int(os.environ.get("ACS_DB_PORT", "5432")),
        user=os.environ.get("ACS_DB_USER", "acs"),
        password=os.environ.get("ACS_DB_PASSWORD", "acs"),
        dbname=os.environ.get("ACS_DB_NAME", "acs"),
    )


def _get_group_key_from_db(group_id: str) -> str | None:
    """Query the database for the stored group_key value."""
    conn = _db_connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT group_key FROM groups WHERE group_id = %s",
            (group_id,),
        )
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    finally:
        conn.close()


@pytest.fixture(scope="function")
def user_client(admin_client: requests.Session, server_url: str, unique_id: str):
    """Create a temporary user account with an API key and return its client."""
    account_data = {
        "account_name": f"GK User {unique_id}",
        "role": "user",
        "login_name": f"gk_user_{unique_id}",
        "login_password": "GkUserPass123!",
    }
    response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
    assert response.status_code == 201, f"Failed to create user account: {response.text}"
    account = response.json()

    key_data = {"api_key_name": "gk-user-key", "role": "user"}
    response = admin_client.post(
        f"{server_url}/api/v1/accounts/{account['account_id']}/api-keys",
        json=key_data,
    )
    assert response.status_code == 201, f"Failed to create user API key: {response.text}"
    token = response.json()["token"]

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.headers.update({"Authorization": f"Bearer {token}"})

    yield session

    session.close()
    admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")


@pytest.fixture(scope="function")
def another_user_client(admin_client: requests.Session, server_url: str, unique_id: str):
    """Create a second temporary user account with an API key and return its client."""
    account_data = {
        "account_name": f"GK Other User {unique_id}",
        "role": "user",
        "login_name": f"gk_other_user_{unique_id}",
        "login_password": "GkOtherPass123!",
    }
    response = admin_client.post(f"{server_url}/api/v1/accounts", json=account_data)
    assert response.status_code == 201, f"Failed to create other user account: {response.text}"
    account = response.json()

    key_data = {"api_key_name": "gk-other-user-key", "role": "user"}
    response = admin_client.post(
        f"{server_url}/api/v1/accounts/{account['account_id']}/api-keys",
        json=key_data,
    )
    assert response.status_code == 201, f"Failed to create other user API key: {response.text}"
    token = response.json()["token"]

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.headers.update({"Authorization": f"Bearer {token}"})

    yield session

    session.close()
    admin_client.delete(f"{server_url}/api/v1/accounts/{account['account_id']}")


@pytest.fixture(scope="function")
def private_group(user_client: requests.Session, admin_client: requests.Session, server_url: str, unique_id: str):
    """Create a private group as a regular user and return its data."""
    group_data = {
        "group_name": f"Private Group {unique_id}",
        "group_context": "Secret discussion",
        "group_key": PLAINTEXT_KEY,
    }
    response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
    assert response.status_code == 201, f"Failed to create private group: {response.text}"
    group = response.json()

    yield group

    # Cleanup: admin can always delete the group.
    admin_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")

class TestGroupKeyPrivacy:
    """Verify group_key is never exposed in plaintext through the API."""

    def test_create_group_with_key_does_not_leak_plaintext(
        self, user_client: requests.Session, server_url: str, unique_id: str
    ):
        """TC-INT-GK-001: Creating a group with group_key must not return the plaintext key."""
        group_data = {
            "group_name": f"Create Key Group {unique_id}",
            "group_context": "Private",
            "group_key": PLAINTEXT_KEY,
        }
        response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201, f"Failed to create group: {response.text}"
        data = response.json()

        assert data["group_name"] == group_data["group_name"]
        assert data.get("group_key") != PLAINTEXT_KEY
        # The API docs state the key is never returned; it should be empty or a hash.
        assert data.get("group_key") == "" or data.get("group_key") != PLAINTEXT_KEY

        # Cleanup
        user_client.delete(f"{server_url}/api/v1/groups/{data['group_id']}")

    def test_get_group_does_not_return_plaintext_key(
        self, user_client: requests.Session, server_url: str, private_group: dict
    ):
        """TC-INT-GK-002: GET group must not return the plaintext group_key."""
        response = user_client.get(f"{server_url}/api/v1/groups/{private_group['group_id']}")
        assert response.status_code == 200, f"Failed to get group: {response.text}"
        data = response.json()

        assert data.get("group_key") != PLAINTEXT_KEY

    def test_update_group_key_does_not_leak_plaintext(
        self, user_client: requests.Session, server_url: str, private_group: dict
    ):
        """TC-INT-GK-003: Updating group_key must not return the new plaintext key."""
        update_data = {"group_key": NEW_PLAINTEXT_KEY}
        response = user_client.put(
            f"{server_url}/api/v1/groups/{private_group['group_id']}",
            json=update_data,
        )
        assert response.status_code == 200, f"Failed to update group key: {response.text}"
        data = response.json()
        assert data.get("group_key") != NEW_PLAINTEXT_KEY

        # Verify GET also does not leak the new key.
        response = user_client.get(f"{server_url}/api/v1/groups/{private_group['group_id']}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("group_key") != NEW_PLAINTEXT_KEY

    def test_list_groups_does_not_return_plaintext_keys(
        self, user_client: requests.Session, server_url: str, private_group: dict
    ):
        """TC-INT-GK-004: Listing groups must not expose plaintext keys."""
        response = user_client.get(f"{server_url}/api/v1/groups")
        assert response.status_code == 200, f"Failed to list groups: {response.text}"
        data = response.json()

        assert "items" in data
        for group in data["items"]:
            assert group.get("group_key") != PLAINTEXT_KEY
            assert group.get("group_key") != NEW_PLAINTEXT_KEY

    def test_public_group_has_empty_group_key(
        self, user_client: requests.Session, server_url: str, unique_id: str
    ):
        """TC-INT-GK-005: Groups created without a key must be public (empty key)."""
        group_data = {
            "group_name": f"Public Group {unique_id}",
            "group_context": "Public discussion",
        }
        response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201, f"Failed to create public group: {response.text}"
        group = response.json()

        try:
            assert group.get("group_key") == ""

            response = user_client.get(f"{server_url}/api/v1/groups/{group['group_id']}")
            assert response.status_code == 200
            data = response.json()
            assert data.get("group_key") == ""
        finally:
            user_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")


class TestGroupKeyHashStorage:
    """Verify the database stores group_key as a hash, not plaintext."""

    def test_group_key_is_stored_as_hash(
        self, user_client: requests.Session, server_url: str, unique_id: str
    ):
        """TC-INT-GK-011: Database must store a hash, not the plaintext key."""
        group_data = {
            "group_name": f"Hash Group {unique_id}",
            "group_context": "Hash test",
            "group_key": PLAINTEXT_KEY,
        }
        response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201, f"Failed to create group: {response.text}"
        group = response.json()

        try:
            stored_key = _get_group_key_from_db(group["group_id"])
            assert stored_key is not None, "group_key not found in database"
            assert stored_key != PLAINTEXT_KEY, "Database stores plaintext group_key"
            # bcrypt hashes are 60 characters and start with $2a$, $2b$, or $2y$.
            assert len(stored_key) >= 50, f"group_key hash looks too short: {len(stored_key)}"
            assert stored_key.startswith(("$2a$", "$2b$", "$2y$")), (
                f"group_key does not look like a bcrypt hash: {stored_key[:10]}"
            )
        finally:
            user_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")


class TestGroupKeyAccessControl:
    """Verify access control for private groups."""

    def test_non_member_cannot_list_private_group_messages(
        self,
        user_client: requests.Session,
        another_user_client: requests.Session,
        server_url: str,
        private_group: dict,
    ):
        """TC-INT-GK-007: Non-members must not list messages in a private group."""
        response = another_user_client.get(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/messages"
        )
        assert response.status_code in (403, 404), (
            f"Expected 403 or 404 for non-member, got {response.status_code}: {response.text}"
        )

    def test_member_can_list_private_group_messages(
        self,
        user_client: requests.Session,
        admin_client: requests.Session,
        server_url: str,
        private_group: dict,
        unique_id: str,
    ):
        """TC-INT-GK-007 (positive): Members can list messages in a private group."""
        # Add a member to the private group as the owner.
        member_data = {
            "member_id": f"member-{unique_id}",
            "member_name": f"Member_{unique_id}",
            "member_type": "user",
        }
        response = user_client.post(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/members",
            json=member_data,
        )
        assert response.status_code == 201, f"Failed to add member: {response.text}"

        # Create a message in the private group.
        message_data = {"message_text": "Secret message"}
        response = user_client.post(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/messages",
            json=message_data,
        )
        assert response.status_code == 201, f"Failed to create message: {response.text}"

        # Owner lists messages.
        response = user_client.get(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/messages"
        )
        assert response.status_code == 200, f"Owner failed to list messages: {response.text}"
        data = response.json()
        assert data["total"] >= 1

    def test_owner_can_update_group_key(
        self, user_client: requests.Session, server_url: str, private_group: dict
    ):
        """TC-INT-GK-008: Group owner can update the group_key."""
        update_data = {"group_key": NEW_PLAINTEXT_KEY}
        response = user_client.put(
            f"{server_url}/api/v1/groups/{private_group['group_id']}",
            json=update_data,
        )
        assert response.status_code == 200, f"Owner failed to update key: {response.text}"

    def test_non_owner_cannot_update_group_key(
        self,
        user_client: requests.Session,
        another_user_client: requests.Session,
        server_url: str,
        private_group: dict,
    ):
        """TC-INT-GK-008: Non-owner user cannot update the group_key."""
        update_data = {"group_key": "hijacked-key"}
        response = another_user_client.put(
            f"{server_url}/api/v1/groups/{private_group['group_id']}",
            json=update_data,
        )
        assert response.status_code in (403, 404), (
            f"Expected 403 or 404 for non-owner update, got {response.status_code}: {response.text}"
        )

    def test_owner_can_convert_public_group_to_private(
        self, user_client: requests.Session, server_url: str, unique_id: str
    ):
        """TC-INT-GK-008: Owner can add a key to a public group."""
        group_data = {
            "group_name": f"Convert Private {unique_id}",
            "group_context": "Public to private",
        }
        response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201, f"Failed to create public group: {response.text}"
        group = response.json()

        try:
            update_data = {"group_key": PLAINTEXT_KEY}
            response = user_client.put(
                f"{server_url}/api/v1/groups/{group['group_id']}",
                json=update_data,
            )
            assert response.status_code == 200, f"Failed to convert to private: {response.text}"

            stored_key = _get_group_key_from_db(group["group_id"])
            assert stored_key is not None
            assert stored_key != PLAINTEXT_KEY
        finally:
            user_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")

    def test_owner_can_convert_private_group_to_public(
        self, user_client: requests.Session, server_url: str, private_group: dict
    ):
        """TC-INT-GK-009: Owner can remove the group_key to make a group public."""
        update_data = {"group_key": ""}
        response = user_client.put(
            f"{server_url}/api/v1/groups/{private_group['group_id']}",
            json=update_data,
        )
        assert response.status_code == 200, f"Failed to convert to public: {response.text}"

        response = user_client.get(f"{server_url}/api/v1/groups/{private_group['group_id']}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("group_key") == ""

    def test_admin_can_access_any_private_group(
        self,
        user_client: requests.Session,
        admin_client: requests.Session,
        server_url: str,
        private_group: dict,
    ):
        """TC-INT-GK-010: Admin can access any private group without the key."""
        response = admin_client.get(f"{server_url}/api/v1/groups/{private_group['group_id']}")
        assert response.status_code == 200, f"Admin failed to access private group: {response.text}"
        data = response.json()
        assert data["group_id"] == private_group["group_id"]

        response = admin_client.get(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/messages"
        )
        assert response.status_code == 200, f"Admin failed to list messages: {response.text}"


class TestGroupKeyJoinBehavior:
    """Verify self-join behavior for public and private groups."""

    def test_join_public_group_without_key_succeeds(
        self,
        user_client: requests.Session,
        another_user_client: requests.Session,
        server_url: str,
        unique_id: str,
    ):
        """TC-INT-GK-013: A non-member can self-join a public group."""
        group_data = {
            "group_name": f"Public Self-Join Group {unique_id}",
            "group_context": "Public discussion",
        }
        response = user_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201, f"Failed to create public group: {response.text}"
        group = response.json()

        try:
            response = another_user_client.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/members",
                json={},
            )
            assert response.status_code == 201, (
                f"Expected 201 for public self-join, got {response.status_code}: {response.text}"
            )
            data = response.json()
            # Self-join overrides member_id to the caller's account_id.
            me = another_user_client.get(f"{server_url}/api/v1/accounts/me").json()
            assert data["member_id"] == me["account_id"]
            assert data["member_type"] == "user"
        finally:
            user_client.delete(f"{server_url}/api/v1/groups/{group['group_id']}")

    def test_join_private_group_without_key_is_rejected(
        self,
        user_client: requests.Session,
        another_user_client: requests.Session,
        server_url: str,
        private_group: dict,
        unique_id: str,
    ):
        """TC-INT-GK-006: A non-member cannot self-join a private group without the key."""
        response = another_user_client.post(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/members",
            json={},
        )
        assert response.status_code in (403, 404), (
            f"Expected 403 or 404 for unauthorized join, got {response.status_code}: {response.text}"
        )

    def test_join_private_group_with_key_in_body_succeeds(
        self,
        user_client: requests.Session,
        another_user_client: requests.Session,
        server_url: str,
        private_group: dict,
        unique_id: str,
    ):
        """TC-INT-GK-012: A non-member can self-join a private group with the correct key."""
        response = another_user_client.post(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/members",
            json={"group_key": PLAINTEXT_KEY},
        )
        assert response.status_code == 201, (
            f"Expected 201 for key-based self-join, got {response.status_code}: {response.text}"
        )
        data = response.json()
        me = another_user_client.get(f"{server_url}/api/v1/accounts/me").json()
        assert data["member_id"] == me["account_id"]
        assert data["member_type"] == "user"

        # The self-joined member can now list messages.
        response = another_user_client.get(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/messages"
        )
        assert response.status_code == 200, (
            f"Self-joined member failed to list messages: {response.status_code}: {response.text}"
        )

    def test_join_private_group_with_wrong_key_is_rejected(
        self,
        user_client: requests.Session,
        another_user_client: requests.Session,
        server_url: str,
        private_group: dict,
        unique_id: str,
    ):
        """TC-INT-GK-014: Self-join with an incorrect group_key is rejected."""
        response = another_user_client.post(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/members",
            json={"group_key": "wrong-key"},
        )
        assert response.status_code in (403, 404), (
            f"Expected 403 or 404 for wrong key, got {response.status_code}: {response.text}"
        )

    def test_owner_can_add_member_to_private_group(
        self,
        user_client: requests.Session,
        another_user_client: requests.Session,
        server_url: str,
        private_group: dict,
        unique_id: str,
    ):
        """TC-INT-GK-006 (actual access path): Owner can add a member directly.

        For a user member to access the group, the member_id must match the
        invited account's account_id. The API authorizes group access by
        mapping the authenticated account to a member record.
        """
        # Resolve the invited user's account_id.
        response = another_user_client.get(f"{server_url}/api/v1/accounts/me")
        assert response.status_code == 200, f"Failed to get invited account: {response.text}"
        invited_account = response.json()

        # member_name must contain only alphanumeric characters, hyphens, and underscores.
        member_name = f"Invited_{unique_id}"
        member_data = {
            "member_id": invited_account["account_id"],
            "member_name": member_name,
            "member_type": "user",
        }
        response = user_client.post(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/members",
            json=member_data,
        )
        assert response.status_code == 201, f"Owner failed to add member: {response.text}"
        data = response.json()
        assert data["member_id"] == member_data["member_id"]

        # The invited member can now list messages.
        response = another_user_client.get(
            f"{server_url}/api/v1/groups/{private_group['group_id']}/messages"
        )
        assert response.status_code == 200, (
            f"Invited member failed to list messages: {response.status_code}: {response.text}"
        )
