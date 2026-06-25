"""
CLI smoke tests for ACS.

These tests verify that the compiled `acs-cli` binary starts, accepts commands
via stdin, and produces the expected output. They are not a replacement for the
full manual CLI test plan, but they provide automated coverage for the most
common CLI paths.

The CLI reads commands from stdin when not running in a TTY. Commands can be
passed in non-interactive form, e.g.:

    /group:create name=MyGroup context=hello
"""

import os
import subprocess
import time
from pathlib import Path

import pytest
import requests
from .conftest import get_response_data


# The integration tests live in tests/integration/, so two levels up is the
# project root where the compiled binary is located at bin/acs-cli.
CLI_BINARY = Path(__file__).parents[2] / "bin" / "acs-cli"


def _run_cli(stdin: str, extra_args: list[str] | None = None, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run the CLI with the given stdin and return the completed process."""
    args = [str(CLI_BINARY), "-no-color"]
    if extra_args:
        args.extend(extra_args)

    env = os.environ.copy()
    # Ensure the CLI talks to the test server, not a hard-coded default.
    env.setdefault("ACS_SERVER_API_BASE", "http://localhost:7370")
    env.setdefault("ACS_NATS_SERVERS", "nats://localhost:4222")

    return subprocess.run(
        args,
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )


@pytest.fixture(scope="function")
def admin_account_id(server_url: str, admin_token: str) -> str:
    """Return the account_id of the admin API key."""
    response = requests.get(
        f"{server_url}/api/v1/accounts/me",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200, f"Failed to get admin account: {response.text}"
    return get_response_data(response)["account_id"]


class TestCLIBinary:
    """Basic binary sanity checks."""

    def test_cli_binary_exists(self):
        """CLI-SETUP-001: the CLI binary must exist."""
        assert CLI_BINARY.exists(), f"CLI binary not found at {CLI_BINARY}"
        assert os.access(CLI_BINARY, os.X_OK), f"CLI binary is not executable: {CLI_BINARY}"

    def test_cli_help_flag(self):
        """CLI-SETUP-002: --help prints Go flag usage."""
        result = subprocess.run(
            [str(CLI_BINARY), "--help"],
            text=True,
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, f"CLI --help failed: {result.stderr}"
        help_text = result.stdout + result.stderr
        assert "-api-key" in help_text, "Expected -api-key flag in help output"
        assert "-api-base" in help_text, "Expected -api-base flag in help output"


class TestCLIAnonymousCommands:
    """Smoke tests for anonymous CLI commands."""

    def test_cli_help_command(self):
        """CLI-SETUP-003: /help via stdin prints the command list."""
        result = _run_cli("/help\n/exit\n")
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "Available commands:" in result.stdout, "Expected command list in /help output"
        assert "/group:create" in result.stdout, "Expected /group:create in help"
        assert "/account:me" in result.stdout, "Expected /account:me in help"

    def test_cli_exit_command(self):
        """CLI-SETUP-004: /exit via stdin terminates the CLI cleanly."""
        result = _run_cli("/exit\n")
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "Goodbye!" in result.stdout, "Expected Goodbye! message"


class TestCLIAuthenticatedCommands:
    """Smoke tests for authenticated CLI commands."""

    def test_cli_account_me(self, admin_token: str):
        """CLI-AUTH-001: /account:me shows the authenticated admin account."""
        result = _run_cli(
            "/account:me\n/exit\n",
            extra_args=["-api-key", admin_token],
        )
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "System Admin" in result.stdout or "Role: admin" in result.stdout, (
            f"Expected admin account info, got: {result.stdout}"
        )

    def test_cli_login_with_password(self, test_account: dict):
        """CLI-AUTH-003: login with login_name and password via CLI."""
        stdin = (
            f"/login login-name={test_account['login_name']} "
            f"login-password=TestPass123!\n"
            "/account:me\n"
            "/exit\n"
        )
        result = _run_cli(stdin)
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "Logged in as" in result.stdout, f"Expected login success, got: {result.stdout}"
        assert test_account["account_name"] in result.stdout, (
            f"Expected account name after login, got: {result.stdout}"
        )

    def test_cli_login_with_session_key(self, test_account: dict, admin_client: requests.Session, server_url: str):
        """CLI-AUTH-004: login with session key via CLI."""
        response = admin_client.post(f"{server_url}/api/v1/accounts/{test_account['account_id']}/session")
        assert response.status_code == 200, f"Failed to create session: {response.text}"
        session_key = get_response_data(response)["session_key"]

        stdin = (
            f"/login session-key={session_key}\n"
            "/account:me\n"
            "/exit\n"
        )
        result = _run_cli(stdin)
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "Logged in as" in result.stdout or test_account["account_name"] in result.stdout, (
            f"Expected session login success, got: {result.stdout}"
        )

    def test_cli_logout(self, admin_token: str):
        """CLI-AUTH-006: /logout clears current credentials."""
        stdin = "/logout\n/exit\n"
        result = _run_cli(stdin, extra_args=["-api-key", admin_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "Logged out" in result.stdout or "Goodbye" in result.stdout, (
            f"Expected logout message, got: {result.stdout}"
        )

    def test_cli_group_create_and_list(self, admin_token: str):
        """CLI-GRP-001/002: create a group and list groups via CLI."""
        group_name = f"SmokeGroup_{int(time.time() * 1000)}"
        stdin = (
            f"/group:create name={group_name} context=smoke-test\n"
            "/group:list\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", admin_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "Group created:" in result.stdout, f"Expected group creation, got: {result.stdout}"
        assert group_name in result.stdout, f"Expected group name in list, got: {result.stdout}"

    def test_cli_group_join_public(self, test_account_with_api_key: tuple, test_group: dict):
        """CLI-GRP-005: self-join a public group via CLI."""
        _, user_token = test_account_with_api_key
        stdin = (
            f"/group:join group-id={test_group['group_id']}\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", user_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "Joined group" in result.stdout or "added to group" in result.stdout.lower(), (
            f"Expected join success, got: {result.stdout}"
        )

    def test_cli_group_join_private_with_key(self, test_account_with_api_key: tuple, admin_client: requests.Session, server_url: str):
        """CLI-GRP-006: self-join a private group with group_key via CLI."""
        _, user_token = test_account_with_api_key
        secret_key = f"secret-key-{int(time.time() * 1000)}"
        group_data = {
            "group_name": f"Private Smoke Group {int(time.time() * 1000)}",
            "group_context": "private group for CLI test",
            "group_key": secret_key,
        }
        response = admin_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201, f"Failed to create private group: {response.text}"
        group_id = get_response_data(response)["group_id"]

        try:
            stdin = (
                f"/group:join group-id={group_id} "
                f"group-key={secret_key}\n"
                "/exit\n"
            )
            result = _run_cli(stdin, extra_args=["-api-key", user_token])
            assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
            assert "Joined group" in result.stdout or "added to group" in result.stdout.lower(), (
                f"Expected join success, got: {result.stdout}"
            )
        finally:
            admin_client.delete(f"{server_url}/api/v1/groups/{group_id}")

    def test_cli_group_join_private_without_key_fails(self, test_account_with_api_key: tuple, admin_client: requests.Session, server_url: str):
        """CLI-GRP-007: self-join a private group without key fails."""
        _, user_token = test_account_with_api_key
        secret_key = f"secret-key-{int(time.time() * 1000)}"
        group_data = {
            "group_name": f"Private Smoke Group {int(time.time() * 1000)}",
            "group_context": "private group for CLI test",
            "group_key": secret_key,
        }
        response = admin_client.post(f"{server_url}/api/v1/groups", json=group_data)
        assert response.status_code == 201, f"Failed to create private group: {response.text}"
        group_id = get_response_data(response)["group_id"]

        try:
            stdin = (
                f"/group:join group-id={group_id}\n"
                "/exit\n"
            )
            result = _run_cli(stdin, extra_args=["-api-key", user_token])
            assert result.returncode != 0 or (
                "access denied" in result.stdout.lower()
                or "key" in result.stdout.lower()
                or "error" in result.stdout.lower()
            ), f"Expected failure for missing group key, got: {result.stdout}"
        finally:
            admin_client.delete(f"{server_url}/api/v1/groups/{group_id}")

    def test_cli_member_add_and_list(self, admin_token: str, test_group: dict):
        """CLI-MEM-001/002: add and list members via CLI."""
        member_id = f"cli-user-{int(time.time() * 1000)}"
        stdin = (
            f"/member:add group-id={test_group['group_id']} "
            f"member-id={member_id} member-name=CLIUser member-type=user\n"
            f"/member:list group-id={test_group['group_id']}\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", admin_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "added to group" in result.stdout.lower(), (
            f"Expected member add success, got: {result.stdout}"
        )
        assert member_id in result.stdout, f"Expected member id in list, got: {result.stdout}"

    def test_cli_member_update_and_remove(self, admin_token: str, test_group: dict):
        """CLI-MEM-003/004: update and remove a member via CLI."""
        member_id = f"cli-user-{int(time.time() * 1000)}"
        stdin_add = (
            f"/member:add group-id={test_group['group_id']} "
            f"member-id={member_id} member-name=CLIUser member-type=user\n"
            "/exit\n"
        )
        _run_cli(stdin_add, extra_args=["-api-key", admin_token])

        stdin_update_remove = (
            f"/member:update group-id={test_group['group_id']} "
            f"member-id={member_id} member-name=CLIUserUpdated\n"
            f"/member:remove group-id={test_group['group_id']} member-id={member_id}\n"
            f"/member:list group-id={test_group['group_id']}\n"
            "/exit\n"
        )
        result = _run_cli(stdin_update_remove, extra_args=["-api-key", admin_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "updated" in result.stdout.lower(), (
            f"Expected member update success, got: {result.stdout}"
        )
        assert "removed from group" in result.stdout.lower(), (
            f"Expected member remove success, got: {result.stdout}"
        )
        assert "CLIUserUpdated" not in result.stdout, (
            f"Expected removed member to be absent, got: {result.stdout}"
        )

    def test_cli_message_list_edit_delete(self, admin_token: str, test_group: dict, test_member: dict):
        """CLI-MSG-001/002/003: list, edit, and delete messages via CLI."""
        # Create a message via API so we have a known message ID.
        # The server derives sender_id and sender_type from the authenticated
        # caller, so we do not send them in the request body.
        response = requests.post(
            f"http://localhost:7370/api/v1/groups/{test_group['group_id']}/messages",
            headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
            json={"message_text": "CLI original message"},
        )
        assert response.status_code == 201, f"Failed to create message: {response.text}"
        message_id = get_response_data(response)["message_id"]

        stdin = (
            f"/message:list group-id={test_group['group_id']}\n"
            f"/message:edit group-id={test_group['group_id']} message-id={message_id} text=CLI edited message\n"
            f"/message:list group-id={test_group['group_id']}\n"
            f"/message:delete group-id={test_group['group_id']} message-id={message_id}\n"
            f"/message:list group-id={test_group['group_id']}\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", admin_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "updated" in result.stdout.lower(), (
            f"Expected message edit success, got: {result.stdout}"
        )
        assert "deleted" in result.stdout.lower(), (
            f"Expected message delete success, got: {result.stdout}"
        )

    def test_cli_api_key_create_and_list(self, test_account_with_api_key: tuple):
        """CLI-KEY-001/002: create and list API keys via CLI as the account owner."""
        account, user_token = test_account_with_api_key
        key_name = f"SmokeKey_{int(time.time() * 1000)}"
        stdin = (
            f"/api-key:create account-id={account['account_id']} name={key_name} role=user\n"
            f"/api-key:list account-id={account['account_id']}\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", user_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "API key created" in result.stdout, f"Expected key creation, got: {result.stdout}"
        assert key_name in result.stdout, f"Expected key name in list, got: {result.stdout}"

    def test_cli_api_key_delete(self, test_account_with_api_key: tuple):
        """CLI-KEY-003: delete an API key via CLI as the account owner."""
        account, user_token = test_account_with_api_key
        key_name = f"SmokeKeyDel_{int(time.time() * 1000)}"
        stdin_create = (
            f"/api-key:create account-id={account['account_id']} name={key_name} role=user\n"
            "/exit\n"
        )
        result_create = _run_cli(stdin_create, extra_args=["-api-key", user_token])
        assert result_create.returncode == 0, f"CLI exited with error: {result_create.stderr}"
        assert "API key created" in result_create.stdout, f"Expected key creation, got: {result_create.stdout}"

        # Extract the api_key_id from the output.
        api_key_id = None
        for line in result_create.stdout.splitlines():
            if "api_key_id" in line or "ak-" in line:
                # Try to find an ak-xxx token in the line.
                for token in line.split():
                    if token.startswith("ak-"):
                        api_key_id = token.strip(".,")
                        break
            if api_key_id:
                break

        assert api_key_id, f"Could not find api_key_id in output: {result_create.stdout}"

        stdin_delete = (
            f"/api-key:delete account-id={account['account_id']} key-id={api_key_id}\n"
            f"/api-key:list account-id={account['account_id']}\n"
            "/exit\n"
        )
        result_delete = _run_cli(stdin_delete, extra_args=["-api-key", user_token])
        assert result_delete.returncode == 0, f"CLI exited with error: {result_delete.stderr}"
        assert (
            "api key" in result_delete.stdout.lower()
            and "deleted" in result_delete.stdout.lower()
        ), f"Expected key deletion, got: {result_delete.stdout}"
        assert key_name not in result_delete.stdout, (
            f"Expected deleted key to be absent, got: {result_delete.stdout}"
        )

    def test_cli_account_create_user(self, admin_token: str):
        """CLI-ACC-001: admin creates a user account via CLI."""
        login_name = f"smoke_user_{int(time.time() * 1000)}@example.com"
        stdin = (
            f"/account:create role=user login-name={login_name} "
            f"login-password=SmokeP@ss123 name=SmokeUser\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", admin_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "Account created:" in result.stdout, f"Expected account creation, got: {result.stdout}"

    def test_cli_account_update_and_delete(self, admin_token: str, test_account: dict):
        """CLI-ACC-002/003: update and delete an account via CLI."""
        account_id = test_account["account_id"]
        stdin = (
            f"/account:update account-id={account_id} name=UpdatedByCLI\n"
            f"/account:delete account-id={account_id} yes=true\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", admin_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert (
            "account" in result.stdout.lower() and "updated" in result.stdout.lower()
        ), f"Expected account update success, got: {result.stdout}"
        assert (
            "account" in result.stdout.lower() and "deleted" in result.stdout.lower()
        ), f"Expected account delete success, got: {result.stdout}"

    def test_cli_account_password_change(self, admin_token: str, test_account: dict):
        """CLI-RBAC-010: change account password via CLI."""
        account_id = test_account["account_id"]
        stdin = (
            f"/account:password account-id={account_id} new-password=NewSmokeP@ss456\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", admin_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "password updated" in result.stdout.lower(), (
            f"Expected password update success, got: {result.stdout}"
        )

    def test_cli_account_session_create(self, admin_token: str, test_account: dict):
        """CLI-RBAC-009: create a login session via CLI."""
        account_id = test_account["account_id"]
        stdin = (
            f"/account:session account-id={account_id}\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", admin_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "session key" in result.stdout.lower(), (
            f"Expected session creation, got: {result.stdout}"
        )


class TestCLIRBAC:
    """RBAC-specific CLI smoke tests."""

    def test_cli_user_cannot_create_account(self, test_account_with_api_key: tuple):
        """CLI-RBAC-003: user API key cannot create accounts."""
        _, user_token = test_account_with_api_key
        login_name = f"unauthorized_user_{int(time.time() * 1000)}@example.com"
        stdin = (
            f"/account:create role=user login-name={login_name} "
            f"login-password=SmokeP@ss123 name=UnauthorizedUser\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", user_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "access denied" in result.stdout.lower() or "error" in result.stdout.lower(), (
            f"Expected forbidden error, got: {result.stdout}"
        )

    def test_cli_user_cannot_create_admin_api_key(self, test_account_with_api_key: tuple):
        """CLI-RBAC-005: user cannot create admin-level API key."""
        account, user_token = test_account_with_api_key
        stdin = (
            f"/api-key:create account-id={account['account_id']} name=BadKey role=admin\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", user_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "access denied" in result.stdout.lower() or "error" in result.stdout.lower(), (
            f"Expected forbidden error, got: {result.stdout}"
        )

    def test_cli_user_cannot_delete_other_account(self, test_account_with_api_key: tuple, test_account: dict):
        """CLI-RBAC-007: user cannot delete another account."""
        _, user_token = test_account_with_api_key
        other_account_id = test_account["account_id"]
        stdin = (
            f"/account:delete account-id={other_account_id}\n"
            "/exit\n"
        )
        result = _run_cli(stdin, extra_args=["-api-key", user_token])
        assert result.returncode == 0, f"CLI exited with error: {result.stderr}"
        assert "access denied" in result.stdout.lower() or "error" in result.stdout.lower(), (
            f"Expected forbidden error, got: {result.stdout}"
        )
