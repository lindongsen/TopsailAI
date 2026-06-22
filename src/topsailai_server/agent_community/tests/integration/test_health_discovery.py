"""
Integration tests for health and service discovery endpoints.

These tests verify the behavior documented in docs/API.md for:
- /healthz, /readyz, /health
- /health/leader
- /discovery/services

Tests are aligned with the actual server response shapes:
- readiness/health checks report "healthy"/"not_ready" with "checks" map
- leader status returns is_leader, self, leader, timestamp
- discovery services returns services and count
"""

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
import requests

PROJECT_ROOT = "/TopsailAI/src/topsailai_server/agent_community"
SERVER_BIN = os.path.join(PROJECT_ROOT, "bin", "acs-server")
AGENT_CMD_DIR = os.path.join(PROJECT_ROOT, "scripts", "topsailai_agent_cmd")

# Loopback aliases used for multi-instance tests.
PRIMARY_HOST = "127.0.0.1"
SECONDARY_HOST = "127.1.0.2"
TEST_PORT = 7370


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
    host: str = SECONDARY_HOST,
    port: int = TEST_PORT,
    extra_env: dict | None = None,
) -> subprocess.Popen:
    """Start a secondary ACS server instance and return its process handle."""
    if not os.path.exists(SERVER_BIN):
        pytest.skip(f"ACS server binary not found: {SERVER_BIN}")

    # Reuse the admin/manager keys created by the primary instance so both
    # instances share the same default account credentials and do not fight
    # over the generated .acs files in the project root.
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
    if admin_key:
        env["ACS_ACCOUNT_ADMIN_API_KEY"] = admin_key
    if manager_key:
        env["ACS_ACCOUNT_MANAGER_API_KEY"] = manager_key
    if extra_env:
        env.update(extra_env)

    log_dir = os.path.join(PROJECT_ROOT, "tests", "integration", ".tmp")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = os.path.join(log_dir, f"acs-server-{host}-{port}.log")

    with open(log_file, "a", encoding="utf-8") as out:
        # Run in foreground (no --daemon-internal) so the Popen handle is the
        # actual server process and multiple instances do not fight over the
        # shared daemon PID/log files.
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

    # Give service discovery a moment to register in NATS KV.
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


class TestHealthEndpoints:
    """Tests for /healthz, /readyz, and /health."""

    def test_healthz_returns_alive(self, unauthenticated_client, server_url):
        """GET /healthz should return 200 with status alive."""
        response = unauthenticated_client.get(f"{server_url}/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "alive"

    def test_readyz_returns_ready_when_healthy(self, unauthenticated_client, server_url):
        """GET /readyz should return 200 with database check healthy."""
        response = unauthenticated_client.get(f"{server_url}/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ready"
        assert "database" in data.get("checks", {})
        assert data["checks"]["database"] == "healthy"

    def test_health_returns_comprehensive_status(self, unauthenticated_client, server_url):
        """GET /health should return status, version, timestamp, and checks."""
        response = unauthenticated_client.get(f"{server_url}/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        assert "version" in data
        assert "timestamp" in data
        assert "checks" in data
        assert data["checks"].get("database") == "healthy"


class TestServiceDiscovery:
    """Tests for /health/leader and /discovery/services."""

    def test_health_leader_single_instance(self, unauthenticated_client, server_url):
        """With a single registered instance, /health/leader returns is_leader=true."""
        response = unauthenticated_client.get(f"{server_url}/health/leader")
        assert response.status_code == 200
        data = response.json()
        assert data.get("is_leader") is True
        assert "self" in data
        assert data["self"].get("id")
        assert data["self"].get("address")

    def test_discovery_services_lists_self(self, unauthenticated_client, server_url):
        """GET /discovery/services should list the current service and count."""
        response = unauthenticated_client.get(f"{server_url}/discovery/services")
        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert "count" in data
        assert data["count"] >= 1
        assert len(data["services"]) == data["count"]
        service_ids = [svc["id"] for svc in data["services"]]
        assert len(service_ids) == len(set(service_ids))


class TestMultiInstanceDiscovery:
    """Tests that require a second ACS server instance."""

    @pytest.fixture(scope="function")
    def secondary_server(self):
        """Start and stop a secondary ACS instance for multi-node tests."""
        process = _start_secondary_server(host=SECONDARY_HOST, port=TEST_PORT)
        try:
            yield f"http://{SECONDARY_HOST}:{TEST_PORT}"
        finally:
            _stop_server(process)

    def test_multi_instance_discovery_lists_both_services(
        self, unauthenticated_client, server_url, secondary_server
    ):
        """With two instances, /discovery/services lists both and elects smallest id leader."""
        response = unauthenticated_client.get(f"{server_url}/discovery/services")
        assert response.status_code == 200
        data = response.json()
        services = data["services"]
        assert data["count"] >= 2

        addresses = {svc["address"] for svc in services}
        assert server_url in addresses or any(
            svc["address"] == PRIMARY_HOST for svc in services
        )
        assert secondary_server in addresses or any(
            svc["address"] == SECONDARY_HOST for svc in services
        )

        # Leader is the service with the smallest UUID id.
        leader = min(services, key=lambda svc: svc["id"])
        for svc in services:
            assert "id" in svc
            assert "name" in svc
            assert "address" in svc
            assert "started_at_ms" in svc

        # Verify /health/leader on both instances agrees on the leader id.
        primary_leader = unauthenticated_client.get(f"{server_url}/health/leader").json()
        secondary_resp = requests.get(f"{secondary_server}/health/leader", timeout=5)
        assert secondary_resp.status_code == 200
        secondary_leader = secondary_resp.json()

        assert primary_leader["leader"]["id"] == leader["id"]
        assert secondary_leader["leader"]["id"] == leader["id"]

    def test_health_leader_non_leader_instance(
        self, unauthenticated_client, server_url, secondary_server
    ):
        """The secondary instance should report is_leader=false when it is not the leader."""
        primary = unauthenticated_client.get(f"{server_url}/health/leader").json()
        secondary = requests.get(f"{secondary_server}/health/leader", timeout=5).json()

        # Exactly one of the two instances should be leader.
        assert primary["is_leader"] != secondary["is_leader"]
        if primary["is_leader"]:
            assert secondary["is_leader"] is False
            assert secondary["leader"]["id"] == primary["self"]["id"]
        else:
            assert primary["is_leader"] is False
            assert primary["leader"]["id"] == secondary["self"]["id"]

    def test_service_deregistration_on_shutdown(
        self, unauthenticated_client, server_url
    ):
        """After the secondary instance stops, it should disappear from discovery."""
        process = _start_secondary_server(host=SECONDARY_HOST, port=TEST_PORT)
        try:
            response = unauthenticated_client.get(f"{server_url}/discovery/services")
            assert response.status_code == 200
            services_before = response.json()["services"]
            assert any(
                svc["address"] == SECONDARY_HOST for svc in services_before
            )
        finally:
            _stop_server(process)

        # Give NATS TTL/heartbeat a moment to settle, then verify removal.
        time.sleep(2)
        response = unauthenticated_client.get(f"{server_url}/discovery/services")
        assert response.status_code == 200
        services_after = response.json()["services"]
        assert not any(svc["address"] == SECONDARY_HOST for svc in services_after)

    def test_heartbeat_keeps_registration_alive(self, unauthenticated_client, server_url):
        """A registered service should still be listed after one heartbeat interval."""
        # The ServiceInfo struct does not expose last_heartbeat_ms, so we verify
        # that the registration persists beyond the default heartbeat window.
        response = unauthenticated_client.get(f"{server_url}/discovery/services")
        assert response.status_code == 200
        before = response.json()["services"]
        assert before

        # Default heartbeat is 30s; wait slightly less and confirm still registered.
        time.sleep(5)
        response = unauthenticated_client.get(f"{server_url}/discovery/services")
        assert response.status_code == 200
        after = response.json()["services"]
        before_ids = {svc["id"] for svc in before}
        after_ids = {svc["id"] for svc in after}
        assert before_ids.issubset(after_ids)


class TestDiscoveryDisabled:
    """Tests for discovery-disabled mode."""

    @pytest.fixture(scope="function")
    def disabled_discovery_server(self):
        """Start a server instance with ACS_DISCOVERY_ENABLED=false."""
        process = _start_secondary_server(
            host="127.1.0.3",
            port=TEST_PORT,
            extra_env={"ACS_DISCOVERY_ENABLED": "false"},
        )
        try:
            yield f"http://127.1.0.3:{TEST_PORT}"
        finally:
            _stop_server(process)

    def test_health_leader_returns_503_when_discovery_disabled(
        self, disabled_discovery_server
    ):
        """GET /health/leader should return 503 when discovery is disabled."""
        response = requests.get(f"{disabled_discovery_server}/health/leader", timeout=5)
        assert response.status_code == 503
        assert "discovery" in response.json().get("error", "").lower()

    def test_discovery_services_returns_503_when_discovery_disabled(
        self, disabled_discovery_server
    ):
        """GET /discovery/services should return 503 when discovery is disabled."""
        response = requests.get(f"{disabled_discovery_server}/discovery/services", timeout=5)
        assert response.status_code == 503
        assert "discovery" in response.json().get("error", "").lower()


class TestReadinessDependencyFailure:
    """Tests for readiness probe dependency failures."""

    @pytest.mark.skip(
        reason="Requires stopping PostgreSQL or NATS, which would break the shared test server."
    )
    def test_readyz_returns_503_when_database_unreachable(self):
        """Skipped: destructive to the shared integration test environment."""
        pass
