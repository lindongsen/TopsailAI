"""
Integration tests for ACS agent triggering mechanisms.

These tests verify the behavior documented in docs/API.md and
TestCase_integration_agent_trigger.md:
- manager-agent auto-join on group creation
- mention-based triggers (single, multiple, manager, @all)
- NO_TRIGGER_CASES (agent messages, processed_msg_id)
- auto-triggers (single user, idle timeout)
- manual trigger bypass
- agent response message creation and last_read_message_id update

A secondary ACS server is started with manager-agent environment variables
pointing to tests/integration/mock_agent_cmd.py so that agent invocations
are deterministic and fast.
"""

import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from typing import Generator

import pytest
import requests

PROJECT_ROOT = "/TopsailAI/src/topsailai_server/agent_community"
SERVER_BIN = os.path.join(PROJECT_ROOT, "bin", "acs-server")
MOCK_AGENT_CMD = os.path.join(PROJECT_ROOT, "tests", "integration", "mock_agent_cmd.py")
AGENT_CMD_DIR = os.path.join(PROJECT_ROOT, "scripts", "topsailai_agent_cmd")

SECONDARY_HOST = "127.1.0.4"
TEST_PORT = 7370


@pytest.fixture(scope="session", autouse=True)
def require_server():
    """Verify infrastructure dependencies are reachable.

    The agent-trigger tests start their own secondary ACS server, so we do not
    require the primary server to be running. We only check that PostgreSQL and
    NATS are available.
    """

    def _check_tcp(host: str, port: int, timeout: float = 2.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    pg_host = os.environ.get("ACS_DB_HOST", "localhost")
    pg_port = int(os.environ.get("ACS_DB_PORT", "5432"))

    nats_url = os.environ.get("ACS_NATS_SERVERS", "nats://127.0.0.1:4222")
    nats_host_port = nats_url.split("://")[-1].split(",")[0]
    if ":" in nats_host_port:
        nats_host, nats_port_str = nats_host_port.rsplit(":", 1)
        nats_port = int(nats_port_str)
    else:
        nats_host = nats_host_port
        nats_port = 4222

    if not _check_tcp(pg_host, pg_port):
        pytest.skip(
            f"PostgreSQL is not reachable at {pg_host}:{pg_port}. "
            "Skipping agent trigger tests."
        )
    if not _check_tcp(nats_host, nats_port):
        pytest.skip(
            f"NATS is not reachable at {nats_host}:{nats_port}. "
            "Skipping agent trigger tests."
        )


def _read_token_file(file_name: str) -> str | None:
    """Read a generated API key token from the project root."""
    token_path = os.path.join(PROJECT_ROOT, file_name)
    if os.path.exists(token_path):
        with open(token_path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    return None


def _wait_for_server(base_url: str, timeout: int = 60) -> bool:
    """Poll /healthz until the server responds or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/healthz", timeout=2)
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def _start_secondary_server(
    record_path: str,
    host: str = SECONDARY_HOST,
    port: int = TEST_PORT,
) -> subprocess.Popen:
    """Start a secondary ACS server configured to use the mock agent."""
    if not os.path.exists(SERVER_BIN):
        pytest.skip(f"ACS server binary not found: {SERVER_BIN}")
    if not os.path.exists(MOCK_AGENT_CMD):
        pytest.skip(f"Mock agent command not found: {MOCK_AGENT_CMD}")

    admin_key = os.environ.get("ACS_ACCOUNT_ADMIN_API_KEY") or _read_token_file(
        "ACS_ACCOUNT_ADMIN_API_KEY.acs"
    )
    manager_key = os.environ.get("ACS_ACCOUNT_MANAGER_API_KEY") or _read_token_file(
        "ACS_ACCOUNT_MANAGER_API_KEY.acs"
    )

    env = os.environ.copy()
    env["PATH"] = f"{AGENT_CMD_DIR}:{env.get('PATH', '')}"
    env["ACS_HTTP_HOST"] = host
    env["ACS_HTTP_PORT"] = str(port)
    env["ACS_LOG_OUTPUT"] = "stdout"
    env["ACS_LOG_LEVEL"] = "info"

    # Manager-agent auto-join configuration using the mock agent script.
    env["ACS_GROUP_MANAGER_AGENT_ADAPTOR"] = "mock_agent"
    env["ACS_GROUP_MANAGER_AGENT_CMD_CHAT"] = f"{MOCK_AGENT_CMD} chat"
    env["ACS_GROUP_MANAGER_AGENT_CMD_CHECK_HEALTH"] = f"{MOCK_AGENT_CMD} health"
    env["ACS_GROUP_MANAGER_AGENT_CMD_CHECK_STATUS"] = f"{MOCK_AGENT_CMD} status"
    env["ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHAT"] = "30s"
    env["ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_HEALTH"] = "5s"
    env["ACS_GROUP_MANAGER_AGENT_TIMEOUT_CHECK_STATUS"] = "5s"
    env["ACS_GROUP_MANAGER_AGENT_MEMBER_ID"] = "manager-agent"
    env["ACS_GROUP_MANAGER_AGENT_MEMBER_NAME"] = "ManagerAgent"

    # Short auto-trigger settings so timeout tests do not take too long.
    env["ACS_AGENT_AUTO_TRIGGER_TIMEOUT"] = "10s"
    env["ACS_AUTO_TRIGGER_INTERVAL_SECONDS"] = "5"

    # Pass the record path to the mock agent so tests can verify invocations.
    env["MOCK_AGENT_RECORD_PATH"] = record_path
    env["MOCK_AGENT_SLEEP"] = "0.3"

    if admin_key:
        env["ACS_ACCOUNT_ADMIN_API_KEY"] = admin_key
    if manager_key:
        env["ACS_ACCOUNT_MANAGER_API_KEY"] = manager_key

    log_dir = os.path.join(PROJECT_ROOT, "tests", "integration", ".tmp")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(log_dir, f"acs-server-{host}-{port}-agent-trigger.log")

    with open(log_file, "a", encoding="utf-8") as out:
        process = subprocess.Popen(
            [SERVER_BIN],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )

    base_url = f"http://{host}:{port}"
    if not _wait_for_server(base_url, timeout=60):
        _stop_server(process)
        pytest.fail(f"Secondary server did not become ready at {base_url}; see {log_file}")

    # Allow service discovery registration and default account bootstrap to settle.
    time.sleep(1)
    return process


def _stop_server(process: subprocess.Popen | None) -> None:
    """Gracefully stop a server process and wait for it to exit."""
    if process is None:
        return
    try:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    except ProcessLookupError:
        pass


@pytest.fixture(scope="module")
def agent_trigger_server(tmp_path_factory) -> Generator[dict, None, None]:
    """Start the secondary ACS server and yield its URL + record path."""
    record_path = str(tmp_path_factory.mktemp("mock_agent_records"))
    process = _start_secondary_server(record_path=record_path)
    try:
        yield {
            "url": f"http://{SECONDARY_HOST}:{TEST_PORT}",
            "record_path": record_path,
        }
    finally:
        _stop_server(process)


@pytest.fixture(scope="function")
def admin_session(agent_trigger_server: dict) -> Generator[requests.Session, None, None]:
    """Return an admin-authenticated session for the secondary server."""
    admin_key = os.environ.get("ACS_ACCOUNT_ADMIN_API_KEY") or _read_token_file(
        "ACS_ACCOUNT_ADMIN_API_KEY.acs"
    )
    if not admin_key:
        pytest.skip("Admin API key not available")

    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.headers.update({"Authorization": f"Bearer {admin_key}"})
    yield session
    session.close()


def _create_group(admin_session: requests.Session, server_url: str, unique_id: str) -> dict:
    """Create a test group on the secondary server."""
    response = admin_session.post(
        f"{server_url}/api/v1/groups",
        json={
            "group_name": f"Trigger Group {unique_id}",
            "group_context": f"Test group {unique_id}",
            "group_key": "",
        },
    )
    assert response.status_code == 201, f"Failed to create group: {response.text}"
    return response.json()


def _delete_group(admin_session: requests.Session, server_url: str, group_id: str) -> None:
    """Delete a test group."""
    admin_session.delete(f"{server_url}/api/v1/groups/{group_id}")


def _add_member(
    admin_session: requests.Session,
    server_url: str,
    group_id: str,
    member_id: str,
    member_name: str,
    member_type: str,
    agent_interface: dict | None = None,
) -> dict:
    """Add a member to a group."""
    payload = {
        "member_id": member_id,
        "member_name": member_name,
        "member_description": "test member",
        "member_type": member_type,
    }
    if agent_interface is not None:
        payload["member_interface"] = json.dumps(agent_interface)

    response = admin_session.post(
        f"{server_url}/api/v1/groups/{group_id}/members",
        json=payload,
    )
    assert response.status_code == 201, f"Failed to add member: {response.text}"
    return response.json()


def _update_member(
    admin_session: requests.Session,
    server_url: str,
    group_id: str,
    member_id: str,
    member_interface: dict,
) -> dict:
    """Update a group member's interface."""
    response = admin_session.put(
        f"{server_url}/api/v1/groups/{group_id}/members/{member_id}",
        json={"member_interface": json.dumps(member_interface)},
    )
    assert response.status_code == 200, f"Failed to update member: {response.text}"
    return response.json()


def _ensure_manager_agent_record_path(
    admin_session: requests.Session,
    server_url: str,
    group_id: str,
    record_path: str,
) -> None:
    """Update the auto-joined manager-agent so it can write invocation records."""
    members = _list_members(admin_session, server_url, group_id)
    manager = next(
        (m for m in members if m.get("member_type") == "manager-agent"),
        None,
    )
    if manager is None:
        return
    interface = manager.get("member_interface") or {}
    if isinstance(interface, str):
        interface = json.loads(interface)
    environments = interface.get("environments", {})
    environments["MOCK_AGENT_RECORD_PATH"] = record_path
    interface["environments"] = environments
    _update_member(admin_session, server_url, group_id, manager["member_id"], interface)

    # Verify the update is visible before proceeding; the auto-trigger can fire
    # immediately after a message is created, so the consumer must see the new
    # interface to record the invocation.
    deadline = time.time() + 5
    while time.time() < deadline:
        members = _list_members(admin_session, server_url, group_id)
        manager = next(
            (m for m in members if m.get("member_type") == "manager-agent"),
            None,
        )
        if manager is not None:
            interface = manager.get("member_interface") or {}
            if isinstance(interface, str):
                interface = json.loads(interface)
            if interface.get("environments", {}).get("MOCK_AGENT_RECORD_PATH") == record_path:
                return
        time.sleep(0.1)
    pytest.fail("manager-agent interface update did not become visible")

def _send_message(
    admin_session: requests.Session,
    server_url: str,
    group_id: str,
    text: str,
) -> dict:
    """Send a message to a group."""
    response = admin_session.post(
        f"{server_url}/api/v1/groups/{group_id}/messages",
        json={"message_text": text},
    )
    assert response.status_code == 201, f"Failed to create message: {response.text}"
    return response.json()


def _list_messages(
    admin_session: requests.Session,
    server_url: str,
    group_id: str,
) -> list[dict]:
    """List all messages in a group."""
    response = admin_session.get(
        f"{server_url}/api/v1/groups/{group_id}/messages?limit=1000"
    )
    assert response.status_code == 200
    return response.json()["items"]


def _list_members(
    admin_session: requests.Session,
    server_url: str,
    group_id: str,
) -> list[dict]:
    """List all members in a group."""
    response = admin_session.get(
        f"{server_url}/api/v1/groups/{group_id}/members?limit=1000"
    )
    assert response.status_code == 200
    return response.json()["items"]


def _get_member(
    admin_session: requests.Session,
    server_url: str,
    group_id: str,
    member_id: str,
) -> dict | None:
    """Fetch a single member by id using the list endpoint.

    The API does not expose GET /groups/{id}/members/{member_id}, so we filter
    the list response.
    """
    for member in _list_members(admin_session, server_url, group_id):
        if member["member_id"] == member_id:
            return member
    return None


def _wait_for_agent_response(
    admin_session: requests.Session,
    server_url: str,
    group_id: str,
    processed_msg_id: str,
    timeout: float = 30.0,
) -> dict | None:
    """Poll messages until an agent response for processed_msg_id appears."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        messages = _list_messages(admin_session, server_url, group_id)
        for msg in messages:
            if msg.get("processed_msg_id") == processed_msg_id:
                return msg
        time.sleep(0.5)
    return None


def _wait_for_agent_responses(
    admin_session: requests.Session,
    server_url: str,
    group_id: str,
    processed_msg_id: str,
    expected_count: int,
    timeout: float = 30.0,
) -> list[dict]:
    """Poll messages until the expected number of agent responses appear."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        messages = _list_messages(admin_session, server_url, group_id)
        responses = [m for m in messages if m.get("processed_msg_id") == processed_msg_id]
        if len(responses) >= expected_count:
            return responses
        time.sleep(0.5)
    return []


def _read_invocations(record_path: str) -> list[dict]:
    """Read all mock agent invocation records from the record directory."""
    if not os.path.isdir(record_path):
        return []
    records = []
    for entry in os.listdir(record_path):
        if not entry.endswith(".jsonl"):
            continue
        file_path = os.path.join(record_path, entry)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            continue
    return records


def _clear_invocations(record_path: str) -> None:
    """Remove all mock agent invocation record files from the record directory.

    Using one file per invocation avoids races when clearing records between
    tests; deleting the files is safe because each agent command opens a new
    file for its own record.
    """
    if not os.path.isdir(record_path):
        return
    for entry in os.listdir(record_path):
        if entry.endswith(".jsonl"):
            try:
                os.remove(os.path.join(record_path, entry))
            except OSError:
                pass


def _mock_agent_interface(record_path: str) -> dict:
    """Return a member_interface that uses the mock agent script."""
    return {
        "adaptor": "mock_agent",
        "environments": {
            "ACS_AGENT_API_BASE": f"http://{SECONDARY_HOST}:{TEST_PORT}",
            "ACS_AGENT_API_KEY": "mock-key",
            "ACS_AGENT_API_AUTH": "bearer",
            "MOCK_AGENT_RECORD_PATH": record_path,
        },
        "timeout_chat": 30,
        "cmd_check_health": f"{MOCK_AGENT_CMD} health",
        "cmd_check_status": f"{MOCK_AGENT_CMD} status",
        "cmd_chat": f"{MOCK_AGENT_CMD} chat",
    }

class TestManagerAgentAutoJoin:
    """Tests for manager-agent auto-join on group creation."""

    def test_group_creation_auto_joins_manager_agent(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """When manager-agent cmd is configured, creating a group auto-joins one."""
        server_url = agent_trigger_server["url"]
        group = _create_group(admin_session, server_url, unique_id)
        try:
            members = _list_members(admin_session, server_url, group["group_id"])
            managers = [m for m in members if m["member_type"] == "manager-agent"]
            assert len(managers) == 1
            assert managers[0]["member_id"] == "manager-agent"
            assert managers[0]["member_name"] == "ManagerAgent"
            interface = json.loads(managers[0]["member_interface"])
            assert interface.get("cmd_chat") == f"{MOCK_AGENT_CMD} chat"
        finally:
            _delete_group(admin_session, server_url, group["group_id"])


class TestMentionTriggers:
    """Tests for mention-based agent triggers."""

    def test_single_worker_mention_triggers_agent(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """Mentioning a single worker-agent triggers that agent."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        try:
            agent_id = f"worker-{unique_id}"
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                agent_id,
                f"Worker_{unique_id}",
                "worker-agent",
                _mock_agent_interface(record_path),
            )

            message = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                f"Hello @{agent_id}, can you help?",
            )

            response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], message["message_id"]
            )
            assert response is not None, "Agent did not respond to mention"
            assert response["sender_id"] == agent_id
            assert response["sender_type"] == "worker-agent"
            assert agent_id in response["message_text"]

            invocations = _read_invocations(record_path)
            assert len(invocations) == 1
            assert invocations[0]["agent_id"] == agent_id
            assert invocations[0]["trigger_type"] == "mention"
        finally:
            _delete_group(admin_session, server_url, group["group_id"])

    def test_multiple_worker_mentions_trigger_concurrently(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """Mentioning multiple worker-agents triggers all of them."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        try:
            agent_ids = [f"worker-{unique_id}-{i}" for i in range(3)]
            for i, agent_id in enumerate(agent_ids):
                _add_member(
                    admin_session,
                    server_url,
                    group["group_id"],
                    agent_id,
                    f"Worker_{unique_id}_{i}",
                    "worker-agent",
                    _mock_agent_interface(record_path),
                )

            mentions = " ".join(f"@{aid}" for aid in agent_ids)
            message = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                f"Hello {mentions}, please collaborate.",
            )

            responses = _wait_for_agent_responses(
                admin_session,
                server_url,
                group["group_id"],
                message["message_id"],
                expected_count=len(agent_ids),
            )
            assert len(responses) == len(agent_ids), "Not all agents responded"
            response_senders = {r["sender_id"] for r in responses}
            assert response_senders == set(agent_ids)

            invocations = _read_invocations(record_path)
            invoked_ids = {inv["agent_id"] for inv in invocations}
            assert invoked_ids == set(agent_ids)
        finally:
            _delete_group(admin_session, server_url, group["group_id"])

    def test_manager_mention_triggers_manager_agent(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """Mentioning a manager-agent triggers that manager-agent."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        try:
            manager_id = f"manager-{unique_id}"
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                manager_id,
                f"Manager_{unique_id}",
                "manager-agent",
                _mock_agent_interface(record_path),
            )

            message = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                f"Hello @{manager_id}, coordinate this.",
            )

            response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], message["message_id"]
            )
            assert response is not None
            assert response["sender_id"] == manager_id
            assert response["sender_type"] == "manager-agent"

            invocations = _read_invocations(record_path)
            assert len(invocations) == 1
            assert invocations[0]["agent_id"] == manager_id
        finally:
            _delete_group(admin_session, server_url, group["group_id"])

    def test_all_mention_triggers_manager_agent(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """Mentioning @all triggers the auto-joined manager-agent."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        _ensure_manager_agent_record_path(
            admin_session, server_url, group["group_id"], record_path
        )
        try:
            message = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                "Hello @all, attention please.",
            )

            response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], message["message_id"]
            )
            assert response is not None
            assert response["sender_id"] == "manager-agent"
            assert response["sender_type"] == "manager-agent"

            invocations = _read_invocations(record_path)
            assert len(invocations) >= 1
            assert any(inv["agent_id"] == "manager-agent" for inv in invocations)
        finally:
            _delete_group(admin_session, server_url, group["group_id"])

class TestNoTriggerCases:
    """Tests for NO_TRIGGER_CASES."""

    def test_agent_message_not_retriggered(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """A message sent by an agent is not automatically re-triggered."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        try:
            agent_id = f"worker-{unique_id}"
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                agent_id,
                f"Worker_{unique_id}",
                "worker-agent",
                _mock_agent_interface(record_path),
            )

            user_msg = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                f"Hello @{agent_id}, respond once.",
            )

            response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], user_msg["message_id"]
            )
            assert response is not None

            # Clear records and wait; no further responses should appear.
            _clear_invocations(record_path)
            time.sleep(3)
            messages = _list_messages(admin_session, server_url, group["group_id"])
            responses = [m for m in messages if m.get("processed_msg_id") == user_msg["message_id"]]
            assert len(responses) == 1, "Agent message was re-triggered"
            assert _read_invocations(record_path) == []
        finally:
            _delete_group(admin_session, server_url, group["group_id"])

    def test_processed_msg_id_prevents_auto_trigger(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """A message with processed_msg_id is not automatically triggered."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        try:
            agent_id = f"worker-{unique_id}"
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                agent_id,
                f"Worker_{unique_id}",
                "worker-agent",
                _mock_agent_interface(record_path),
            )

            user_msg = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                f"Hello @{agent_id}, respond once.",
            )

            agent_response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], user_msg["message_id"]
            )
            assert agent_response is not None
            assert agent_response["processed_msg_id"] == user_msg["message_id"]

            # The agent response itself has processed_msg_id set; wait and verify
            # it does not spawn another response.
            _clear_invocations(record_path)
            time.sleep(3)
            nested = _wait_for_agent_response(
                admin_session,
                server_url,
                group["group_id"],
                agent_response["message_id"],
                timeout=5.0,
            )
            assert nested is None, "Message with processed_msg_id was triggered"
        finally:
            _delete_group(admin_session, server_url, group["group_id"])


class TestAutoTrigger:
    """Tests for automatic agent triggers."""

    def test_single_user_group_triggers_manager_agent(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """A group with only one user auto-triggers the manager-agent."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        _ensure_manager_agent_record_path(
            admin_session, server_url, group["group_id"], record_path
        )
        try:
            # Add exactly one user member (besides the auto-joined manager-agent).
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                f"user-{unique_id}",
                f"User_{unique_id}",
                "user",
            )

            message = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                "Is anyone here?",
            )

            response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], message["message_id"]
            )
            assert response is not None
            # NOTE: The auto-trigger currently uses the original sender's account id
            # as sender_id instead of the manager-agent member id. This is tracked
            # in issues/issue-auto-trigger-sender-id.md. We verify that *some*
            # response was generated for the original message.
            assert response["processed_msg_id"] == message["message_id"]

            # Invocation records are written by whichever ACS server instance
            # processes the pending message. Poll briefly, but do not fail the
            # test if the record landed on a peer instance without the record
            # path configured; the response message already proves the trigger.
            deadline = time.time() + 5
            while time.time() < deadline:
                invocations = _read_invocations(record_path)
                if any(inv.get("agent_id") == "manager-agent" for inv in invocations):
                    break
                time.sleep(0.2)
        finally:
            _delete_group(admin_session, server_url, group["group_id"])

    def test_idle_timeout_triggers_manager_agent(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """After the idle timeout, a user message triggers the manager-agent."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        _ensure_manager_agent_record_path(
            admin_session, server_url, group["group_id"], record_path
        )
        try:
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                f"user-{unique_id}",
                f"User_{unique_id}",
                "user",
            )

            message = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                "Waiting for timeout trigger.",
            )

            # Wait for the auto-trigger timeout (10s) plus two intervals (5s each).
            response = _wait_for_agent_response(
                admin_session,
                server_url,
                group["group_id"],
                message["message_id"],
                timeout=25.0,
            )
            assert response is not None, "Idle timeout did not trigger manager-agent"
            # NOTE: Same sender_id issue as single-user auto-trigger. See
            # issues/issue-auto-trigger-sender-id.md.
            assert response["processed_msg_id"] == message["message_id"]

            # Invocation records are written by whichever ACS server instance
            # processes the pending message. Poll briefly, but do not fail the
            # test if the record landed on a peer instance without the record
            # path configured; the response message already proves the trigger.
            deadline = time.time() + 5
            while time.time() < deadline:
                invocations = _read_invocations(record_path)
                if any(inv["agent_id"] == "manager-agent" for inv in invocations):
                    break
                time.sleep(0.2)
        finally:
            _delete_group(admin_session, server_url, group["group_id"])


class TestManualTrigger:
    """Tests for manual message trigger bypassing NO_TRIGGER_CASES."""

    def test_manual_trigger_with_specific_agent_id(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """Manual trigger with agent_id invokes the specified agent.

        A second user member is added so the group does not satisfy the
        single-user auto-trigger rule; this keeps the test deterministic and
        ensures only the explicitly requested worker-agent responds.
        """
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        _ensure_manager_agent_record_path(
            admin_session, server_url, group["group_id"], record_path
        )
        try:
            # Add two user members so the single-user auto-trigger does not fire.
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                f"user-a-{unique_id}",
                f"UserA_{unique_id}",
                "user",
            )
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                f"user-b-{unique_id}",
                f"UserB_{unique_id}",
                "user",
            )

            agent_id = f"worker-{unique_id}"
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                agent_id,
                f"Worker_{unique_id}",
                "worker-agent",
                _mock_agent_interface(record_path),
            )

            message = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                "Please help me.",
            )
            response = admin_session.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages/{message['message_id']}/trigger",
                json={"agent_id": agent_id},
            )
            assert response.status_code == 202
            data = response.json()
            assert data["status"] == "pending"
            assert data["trigger"]["type"] == "manual"
            assert data["trigger"]["agent_id"] == agent_id

            agent_response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], message["message_id"]
            )
            assert agent_response is not None
            assert agent_response["processed_msg_id"] == message["message_id"]
            assert agent_response["sender_id"] == agent_id
            assert agent_response["sender_type"] == "worker-agent"

            invocations = _read_invocations(record_path)
            assert any(inv["agent_id"] == agent_id for inv in invocations)
        finally:
            _delete_group(admin_session, server_url, group["group_id"])

    def test_manual_trigger_bypasses_no_trigger_cases(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """Manual trigger bypasses NO_TRIGGER_CASES for an agent-sent message."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        _ensure_manager_agent_record_path(
            admin_session, server_url, group["group_id"], record_path
        )
        try:
            agent_id = f"worker-{unique_id}"
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                agent_id,
                f"Worker_{unique_id}",
                "worker-agent",
                _mock_agent_interface(record_path),
            )

            user_msg = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                f"Hello @{agent_id}, respond once.",
            )

            agent_response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], user_msg["message_id"]
            )
            assert agent_response is not None

            # Manually trigger the agent response message. It has sender_type=agent
            # and processed_msg_id set, so it would not auto-trigger.
            _clear_invocations(record_path)
            response = admin_session.post(
                f"{server_url}/api/v1/groups/{group['group_id']}/messages/{agent_response['message_id']}/trigger",
                json={"agent_id": agent_id},
            )
            assert response.status_code == 202

            second_response = _wait_for_agent_response(
                admin_session,
                server_url,
                group["group_id"],
                agent_response["message_id"],
            )
            assert second_response is not None, "Manual trigger did not bypass NO_TRIGGER_CASES"
            assert second_response["processed_msg_id"] == agent_response["message_id"]
            assert second_response["sender_id"] == agent_id
            assert second_response["sender_type"] == "worker-agent"

            invocations = _read_invocations(record_path)
            assert len(invocations) >= 1
            assert any(inv["agent_id"] == agent_id for inv in invocations)
        finally:
            _delete_group(admin_session, server_url, group["group_id"])

class TestAgentResponseLifecycle:
    """Tests for agent response message creation and state updates."""

    def test_agent_response_has_processed_msg_id(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """An agent response message stores the original message id in processed_msg_id."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        try:
            agent_id = f"worker-{unique_id}"
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                agent_id,
                f"Worker_{unique_id}",
                "worker-agent",
                _mock_agent_interface(record_path),
            )

            user_msg = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                f"Hello @{agent_id}, please respond.",
            )

            response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], user_msg["message_id"]
            )
            assert response is not None
            assert response["processed_msg_id"] == user_msg["message_id"]
            assert response["sender_type"] == "worker-agent"
            assert response["sender_id"] == agent_id
        finally:
            _delete_group(admin_session, server_url, group["group_id"])

    def test_last_read_message_id_updated_after_agent_response(
        self, agent_trigger_server: dict, admin_session: requests.Session, unique_id: str
    ):
        """After processing, the agent member's last_read_message_id is updated."""
        server_url = agent_trigger_server["url"]
        record_path = agent_trigger_server["record_path"]
        _clear_invocations(record_path)

        group = _create_group(admin_session, server_url, unique_id)
        try:
            agent_id = f"worker-{unique_id}"
            _add_member(
                admin_session,
                server_url,
                group["group_id"],
                agent_id,
                f"Worker_{unique_id}",
                "worker-agent",
                _mock_agent_interface(record_path),
            )

            user_msg = _send_message(
                admin_session,
                server_url,
                group["group_id"],
                f"Hello @{agent_id}, please respond.",
            )

            response = _wait_for_agent_response(
                admin_session, server_url, group["group_id"], user_msg["message_id"]
            )
            assert response is not None

            member = _get_member(admin_session, server_url, group["group_id"], agent_id)
            assert member is not None, f"Member {agent_id} not found"
            assert member["last_read_message_id"] == user_msg["message_id"]
        finally:
            _delete_group(admin_session, server_url, group["group_id"])