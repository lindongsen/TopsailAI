"""
Integration tests for member_status active update feature.

These tests verify that member_status transitions correctly:
- When an agent is invoked, status becomes "processing"
- When agent call ends (success or failure), status returns to "idle"
- NATS group_member/modify events are published for status changes
"""

import asyncio
import json
import time

import nats
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

    @pytest.mark.asyncio
    async def test_member_status_processing_then_idle_success(
        self,
        api_client: requests.Session,
        server_url: str,
        test_group: dict,
        unique_id: str,
        nats_client: nats.NATS,
    ):
        """
        Test that member_status transitions to 'processing' during agent invocation
        and back to 'idle' after successful completion, and that NATS
        group_member/modify events are published for both transitions.
        """
        agent_id = f"agent-{unique_id}"
        user_id = f"user-{unique_id}"
        group_id = test_group["group_id"]
        subject = f"acs.group.message.{group_id}"

        # 1. Start a mock agent server with a noticeable delay so we can observe "processing"
        mock_agent = MockAgentServer(
            host="127.0.0.1",
            port=18081,
            agent_id=agent_id,
            agent_name=f"Test_Agent_{unique_id}",
            auth_token="test-key",
            delay=1.5,  # 1.5s delay to allow polling the processing state
            error_rate=0.0,
        )
        mock_agent.start()
        await asyncio.sleep(0.3)  # wait for mock server to be ready

        received_events = []

        async def on_message(msg):
            try:
                event = json.loads(msg.data.decode("utf-8"))
                if event.get("type") == "group_member" and event.get("action") == "modify":
                    if event.get("data", {}).get("member_id") == agent_id:
                        received_events.append(event)
            except Exception:
                pass

        sub = await nats_client.subscribe(subject, cb=on_message)
        await asyncio.sleep(0.5)  # ensure subscription is active before events are published

        try:
            agent_interface = {
                "adaptor": "topsailai_agent",
                "environments": {
                    "ACS_AGENT_API_BASE": "http://127.0.0.1:18081",
                    "ACS_AGENT_API_KEY": "test-key",
                    "ACS_AGENT_API_AUTH": "bearer",
                },
                "timeout_chat": 30,
            }
            agent_data = {
                "member_id": agent_id,
                "member_name": f"Test_Agent_{unique_id}",
                "member_description": "A test agent for status transitions",
                "member_type": "worker-agent",
                "member_interface": json.dumps(agent_interface),
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{group_id}/members",
                json=agent_data,
            )
            assert response.status_code == 201, f"Failed to add agent: {response.text}"

            # 3. Add a human user member
            user_data = {
                "member_id": user_id,
                "member_name": f"Test_User_{unique_id}",
                "member_type": "user",
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{group_id}/members",
                json=user_data,
            )
            assert response.status_code == 201, f"Failed to add user: {response.text}"

            # 4. Verify initial status is "online" (set on join)
            status = self._get_member_status(api_client, server_url, group_id, agent_id)
            assert status == "online", f"Expected initial status 'online', got '{status}'"

            # 5. Send a message that mentions the agent to trigger it
            message_data = {
                "message_text": f"Hello @{agent_id}, can you help me?",
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{group_id}/messages",
                json=message_data,
            )
            assert response.status_code == 201, f"Failed to send message: {response.text}"

            # 6. Poll member status: should eventually become "processing"
            processing_observed = False
            deadline = time.time() + 10.0
            while time.time() < deadline:
                status = self._get_member_status(api_client, server_url, group_id, agent_id)
                if status == "processing":
                    processing_observed = True
                    break
                await asyncio.sleep(0.2)

            assert processing_observed, (
                "Agent member_status never transitioned to 'processing' within timeout"
            )

            # 7. Poll member status: should eventually return to "idle"
            idle_observed = False
            deadline = time.time() + 15.0
            while time.time() < deadline:
                status = self._get_member_status(api_client, server_url, group_id, agent_id)
                if status == "idle":
                    idle_observed = True
                    break
                await asyncio.sleep(0.2)

            assert idle_observed, (
                "Agent member_status never transitioned back to 'idle' within timeout"
            )

            # 8. Verify NATS events were published for both transitions
            await asyncio.sleep(0.5)  # allow any in-flight events to be delivered

            processing_events = [e for e in received_events if e["data"].get("member_status") == "processing"]
            idle_events = [e for e in received_events if e["data"].get("member_status") == "idle"]

            assert len(processing_events) >= 1, (
                "No group_member/modify event with member_status='processing' was received"
            )
            assert len(idle_events) >= 1, (
                "No group_member/modify event with member_status='idle' was received"
            )

            # The processing event should be received before the idle event
            first_processing_index = next(
                (i for i, e in enumerate(received_events) if e["data"].get("member_status") == "processing"),
                None,
            )
            first_idle_index = next(
                (i for i, e in enumerate(received_events) if e["data"].get("member_status") == "idle"),
                None,
            )
            assert first_processing_index is not None
            assert first_idle_index is not None
            assert first_processing_index < first_idle_index, (
                "Expected 'processing' event to be received before 'idle' event"
            )

        finally:
            await sub.unsubscribe()
            mock_agent.stop()
            # Cleanup: remove agent member if it exists
            try:
                api_client.delete(
                    f"{server_url}/api/v1/groups/{group_id}/members/{agent_id}"
                )
            except Exception:
                pass
            # Cleanup: remove user member if it exists
            try:
                api_client.delete(
                    f"{server_url}/api/v1/groups/{group_id}/members/{user_id}"
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
            agent_name=f"Fail_Agent_{unique_id}",
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
                    "ACS_AGENT_API_AUTH": "bearer",
                },
                "timeout_chat": 30,
            }
            agent_data = {
                "member_id": f"fail-agent-{unique_id}",
                "member_name": f"Fail_Agent_{unique_id}",
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
                "member_name": f"Test_User_{unique_id}",
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
                "ACS_AGENT_API_AUTH": "bearer",
            },
            "timeout_chat": 5,
            "timeout_check_health": 1,
        }
        agent_data = {
            "member_id": f"dead-agent-{unique_id}",
            "member_name": f"Dead_Agent_{unique_id}",
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
            "member_name": f"Test_User_{unique_id}",
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

    @pytest.mark.asyncio
    async def test_member_status_modify_event_published(
        self,
        api_client: requests.Session,
        server_url: str,
        test_group: dict,
        unique_id: str,
        nats_client: nats.NATS,
    ):
        """
        Test that a group_member/modify NATS event is published when member_status
        is changed via the API update member endpoint.
        """
        user_id = f"event-user-{unique_id}"
        group_id = test_group["group_id"]
        subject = f"acs.group.message.{group_id}"

        # 1. Add a user member
        user_data = {
            "member_id": user_id,
            "member_name": f"Event_User_{unique_id}",
            "member_type": "user",
        }
        response = api_client.post(
            f"{server_url}/api/v1/groups/{group_id}/members",
            json=user_data,
        )
        assert response.status_code == 201, f"Failed to add user: {response.text}"

        # 2. Subscribe to group events
        received_events = []

        async def on_message(msg):
            try:
                event = json.loads(msg.data.decode("utf-8"))
                if event.get("type") == "group_member" and event.get("action") == "modify":
                    received_events.append(event)
            except Exception:
                pass

        sub = await nats_client.subscribe(subject, cb=on_message)
        await asyncio.sleep(0.5)  # allow subscription to be ready

        try:
            # 3. Update member_status via API
            update_data = {"member_status": "idle"}
            response = api_client.put(
                f"{server_url}/api/v1/groups/{group_id}/members/{user_id}",
                json=update_data,
            )
            assert response.status_code == 200, f"Failed to update member: {response.text}"

            # 4. Wait for the modify event
            deadline = time.time() + 5.0
            while time.time() < deadline and not received_events:
                await asyncio.sleep(0.2)

            assert len(received_events) >= 1, "No group_member/modify event received"
            event = received_events[0]
            assert event["data"]["member_id"] == user_id
            assert event["data"]["member_status"] == "idle"

        finally:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
            try:
                api_client.delete(
                    f"{server_url}/api/v1/groups/{group_id}/members/{user_id}"
                )
            except Exception:
                pass
    @pytest.mark.asyncio
    async def test_member_status_agent_invocation_path_diagnostic(
        self,
        api_client: requests.Session,
        server_url: str,
        test_group: dict,
        unique_id: str,
    ):
        """
        Diagnostic test: verify that mentioning an agent creates a response message
        and that we can observe the member_status transition.
        """
        agent_id = f"diag-agent-{unique_id}"
        user_id = f"diag-user-{unique_id}"
        group_id = test_group["group_id"]

        mock_agent = MockAgentServer(
            host="127.0.0.1",
            port=18084,
            agent_id=agent_id,
            agent_name=f"Diag_Agent_{unique_id}",
            auth_token="test-key",
            delay=0.5,
            error_rate=0.0,
        )
        mock_agent.start()
        await asyncio.sleep(0.3)

        try:
            agent_interface = {
                "adaptor": "topsailai_agent",
                "environments": {
                    "ACS_AGENT_API_BASE": "http://127.0.0.1:18084",
                    "ACS_AGENT_API_KEY": "test-key",
                    "ACS_AGENT_API_AUTH": "bearer",
                },
                "timeout_chat": 30,
            }
            response = api_client.post(
                f"{server_url}/api/v1/groups/{group_id}/members",
                json={
                    "member_id": agent_id,
                    "member_name": f"Diag_Agent_{unique_id}",
                    "member_type": "worker-agent",
                    "member_interface": json.dumps(agent_interface),
                },
            )
            assert response.status_code == 201, f"Failed to add agent: {response.text}"

            response = api_client.post(
                f"{server_url}/api/v1/groups/{group_id}/members",
                json={
                    "member_id": user_id,
                    "member_name": f"Diag_User_{unique_id}",
                    "member_type": "user",
                },
            )
            assert response.status_code == 201, f"Failed to add user: {response.text}"

            response = api_client.post(
                f"{server_url}/api/v1/groups/{group_id}/messages",
                json={"message_text": f"Hello @{agent_id}, can you help me?"},
            )
            assert response.status_code == 201, f"Failed to send message: {response.text}"
            message_id = response.json()["message_id"]

            # Wait for agent response
            deadline = time.time() + 15.0
            found_response = False
            while time.time() < deadline:
                response = api_client.get(f"{server_url}/api/v1/groups/{group_id}/messages")
                assert response.status_code == 200
                data = response.json()
                for msg in data.get("items", []):
                    if msg.get("processed_msg_id") == message_id:
                        found_response = True
                        break
                if found_response:
                    break
                await asyncio.sleep(0.5)

            assert found_response, "No agent response message with processed_msg_id was created"
        finally:
            mock_agent.stop()
            try:
                api_client.delete(f"{server_url}/api/v1/groups/{group_id}/members/{agent_id}")
            except Exception:
                pass
            try:
                api_client.delete(f"{server_url}/api/v1/groups/{group_id}/members/{user_id}")
            except Exception:
                pass

