"""
Integration tests for member_status active update feature.

These tests verify that member_status transitions correctly:
- When an agent is invoked, status becomes "processing"
- When agent call ends (success or failure), status returns to "idle"
"""

import json
import time

import pytest
import requests

from .mock_agent_server import MockAgentServer


class TestMemberStatusActiveUpdate:
    """Test member_status transitions during agent execution."""

    def _get_member_status(self, api_client: requests.Session, server_url: str, group_id: str, member_id: str) -> str:
        """Helper to fetch current member_status for a specific member."""
        response = api_client.get(f"{server_url}/api/v1/groups/{group_id}/members")
        assert response.status_code == 200, f"Failed to list members: {response.text}"

        data = response.json()
        for member in data.get("items", []):
            if member.get("member_id") == member_id:
                return member.get("member_status", "")
        return ""

    def test_member_status_processing_then_idle_success(
        self,
        api_client: requests.Session,
        server_url: str,
        test_group: dict,
        unique_id: str,
    ):
        """
        Test that member_status transitions to 'processing' during agent invocation
        and back to 'idle' after successful completion.
        """
        # 1. Start a mock agent server with a noticeable delay so we can observe "processing"
        mock_agent = MockAgentServer(
            host="127.0.0.1",
            port=18081,
            agent_id=f"agent-{unique_id}",
            agent_name=f"Test Agent {unique_id}",
            auth_token="test-key",
            delay=1.5,  # 1.5s delay to allow polling the processing state
            error_rate=0.0,
        )
        mock_agent.start()
        time.sleep(0.3)  # wait for mock server to be ready

        try:
            # 2. Add agent member pointing to mock agent server
            agent_interface = {
                "adaptor": "topsailai_agent",
                "environments": {
                    "ACS_AGENT_API_BASE": "http://127.0.0.1:18081",
                    "ACS_AGENT_API_KEY": "test-key",
                    "ACS_AGENT_API_AUTH": "BearerToken",
                },
                "timeout_chat": 30,
            }
            agent_data = {
                "member_id": f"agent-{unique_id}",
                "member_name": f"Test Agent {unique_id}",
                "member_description": "A test agent for status transitions",
                "member_type": "worker-agent",
                "member_interface": json.dumps(agent_interface),
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
                json=agent_data,
            )
            assert response.status_code == 201, f"Failed to add agent: {response.text}"

            # 3. Add a human user member
            user_data = {
                "member_id": f"user-{unique_id}",
                "member_name": f"Test User {unique_id}",
                "member_type": "user",
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
                json=user_data,
            )
            assert response.status_code == 201, f"Failed to add user: {response.text}"

            # 4. Verify initial status is "online" (set on join)
            status = self._get_member_status(
                api_client, server_url, test_group["group_id"], f"agent-{unique_id}"
            )
            assert status == "online", f"Expected initial status 'online', got '{status}'"

            # 5. Send a message that mentions the agent to trigger it
            message_data = {
                "message_text": f"Hello @agent-{unique_id}, can you help me?",
                "sender_id": f"user-{unique_id}",
                "sender_type": "user",
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 201, f"Failed to send message: {response.text}"

            # 6. Poll member status: should eventually become "processing"
            processing_observed = False
            deadline = time.time() + 10.0
            while time.time() < deadline:
                status = self._get_member_status(
                    api_client, server_url, test_group["group_id"], f"agent-{unique_id}"
                )
                if status == "processing":
                    processing_observed = True
                    break
                time.sleep(0.2)

            assert processing_observed, (
                "Agent member_status never transitioned to 'processing' within timeout"
            )

            # 7. Poll member status: should eventually return to "idle"
            idle_observed = False
            deadline = time.time() + 15.0
            while time.time() < deadline:
                status = self._get_member_status(
                    api_client, server_url, test_group["group_id"], f"agent-{unique_id}"
                )
                if status == "idle":
                    idle_observed = True
                    break
                time.sleep(0.2)

            assert idle_observed, (
                "Agent member_status never transitioned back to 'idle' within timeout"
            )

        finally:
            mock_agent.stop()
            # Cleanup: remove agent member if it exists
            try:
                api_client.delete(
                    f"{server_url}/api/v1/groups/{test_group['group_id']}/members/agent-{unique_id}"
                )
            except Exception:
                pass
            # Cleanup: remove user member if it exists
            try:
                api_client.delete(
                    f"{server_url}/api/v1/groups/{test_group['group_id']}/members/user-{unique_id}"
                )
            except Exception:
                pass

    def test_member_status_idle_after_agent_failure(
        self,
        api_client: requests.Session,
        server_url: str,
        test_group: dict,
        unique_id: str,
    ):
        """
        Test that member_status returns to 'idle' even when the agent call fails.
        """
        # 1. Start a mock agent server that always returns errors
        mock_agent = MockAgentServer(
            host="127.0.0.1",
            port=18082,
            agent_id=f"fail-agent-{unique_id}",
            agent_name=f"Fail Agent {unique_id}",
            auth_token="test-key",
            delay=0.2,
            error_rate=1.0,  # 100% error rate
        )
        mock_agent.start()
        time.sleep(0.3)

        try:
            # 2. Add failing agent member
            agent_interface = {
                "adaptor": "topsailai_agent",
                "environments": {
                    "ACS_AGENT_API_BASE": "http://127.0.0.1:18082",
                    "ACS_AGENT_API_KEY": "test-key",
                    "ACS_AGENT_API_AUTH": "BearerToken",
                },
                "timeout_chat": 30,
            }
            agent_data = {
                "member_id": f"fail-agent-{unique_id}",
                "member_name": f"Fail Agent {unique_id}",
                "member_description": "An agent that always fails",
                "member_type": "worker-agent",
                "member_interface": json.dumps(agent_interface),
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
                json=agent_data,
            )
            assert response.status_code == 201, f"Failed to add agent: {response.text}"

            # 3. Add a human user member
            user_data = {
                "member_id": f"user-fail-{unique_id}",
                "member_name": f"Test User {unique_id}",
                "member_type": "user",
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
                json=user_data,
            )
            assert response.status_code == 201, f"Failed to add user: {response.text}"

            # 4. Verify initial status
            status = self._get_member_status(
                api_client, server_url, test_group["group_id"], f"fail-agent-{unique_id}"
            )
            assert status == "online", f"Expected initial status 'online', got '{status}'"

            # 5. Send a message that mentions the failing agent
            message_data = {
                "message_text": f"Hello @fail-agent-{unique_id}, can you help me?",
                "sender_id": f"user-fail-{unique_id}",
                "sender_type": "user",
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 201, f"Failed to send message: {response.text}"

            # 6. Wait for processing to start and then fail; status should return to idle
            idle_observed = False
            deadline = time.time() + 15.0
            while time.time() < deadline:
                status = self._get_member_status(
                    api_client, server_url, test_group["group_id"], f"fail-agent-{unique_id}"
                )
                if status == "idle":
                    idle_observed = True
                    break
                time.sleep(0.2)

            assert idle_observed, (
                "Agent member_status never returned to 'idle' after failure within timeout"
            )

        finally:
            mock_agent.stop()
            try:
                api_client.delete(
                    f"{server_url}/api/v1/groups/{test_group['group_id']}/members/fail-agent-{unique_id}"
                )
            except Exception:
                pass
            try:
                api_client.delete(
                    f"{server_url}/api/v1/groups/{test_group['group_id']}/members/user-fail-{unique_id}"
                )
            except Exception:
                pass

    def test_member_status_no_change_when_health_check_fails(
        self,
        api_client: requests.Session,
        server_url: str,
        test_group: dict,
        unique_id: str,
    ):
        """
        Test that member_status is NOT changed when the agent's health check fails
        (agent never actually invoked for processing).
        """
        # 1. Use a port where no server is running -> health check will fail
        dead_port = 18083

        agent_interface = {
            "adaptor": "topsailai_agent",
            "environments": {
                "ACS_AGENT_API_BASE": f"http://127.0.0.1:{dead_port}",
                "ACS_AGENT_API_KEY": "test-key",
                "ACS_AGENT_API_AUTH": "BearerToken",
            },
            "timeout_chat": 5,
            "timeout_check_health": 1,
        }
        agent_data = {
            "member_id": f"dead-agent-{unique_id}",
            "member_name": f"Dead Agent {unique_id}",
            "member_description": "An agent with no running server",
            "member_type": "worker-agent",
            "member_interface": json.dumps(agent_interface),
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
            json=agent_data,
        )
        assert response.status_code == 201, f"Failed to add agent: {response.text}"

        # 2. Add a human user member
        user_data = {
            "member_id": f"user-dead-{unique_id}",
            "member_name": f"Test User {unique_id}",
            "member_type": "user",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{test_group['group_id']}/members",
            json=user_data,
        )
        assert response.status_code == 201, f"Failed to add user: {response.text}"

        try:
            # 3. Verify initial status
            status = self._get_member_status(
                api_client, server_url, test_group["group_id"], f"dead-agent-{unique_id}"
            )
            assert status == "online", f"Expected initial status 'online', got '{status}'"

            # 4. Send a message that mentions the dead agent
            message_data = {
                "message_text": f"Hello @dead-agent-{unique_id}, can you help me?",
                "sender_id": f"user-dead-{unique_id}",
                "sender_type": "user",
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{test_group['group_id']}/messages",
                json=message_data,
            )
            assert response.status_code == 201, f"Failed to send message: {response.text}"

            # 5. Wait a bit for any potential processing to be attempted
            time.sleep(3.0)

            # 6. Verify status is still "online" (never changed to processing/idle)
            status = self._get_member_status(
                api_client, server_url, test_group["group_id"], f"dead-agent-{unique_id}"
            )
            assert status == "online", (
                f"Expected status to remain 'online' when health check fails, got '{status}'"
            )

        finally:
            try:
                api_client.delete(
                    f"{server_url}/api/v1/groups/{test_group['group_id']}/members/dead-agent-{unique_id}"
                )
            except Exception:
                pass
            try:
                api_client.delete(
                    f"{server_url}/api/v1/groups/{test_group['group_id']}/members/user-dead-{unique_id}"
                )
            except Exception:
                pass
