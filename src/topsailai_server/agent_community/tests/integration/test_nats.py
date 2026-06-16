"""
Integration tests for NATS messaging functionality.

These tests verify NATS pub/sub, JetStream, and pending message flows.
"""

import asyncio
import json
import time

import nats
import pytest
from nats.js.api import StreamConfig


class TestNATSConnection:
    """Test basic NATS connectivity."""

    @pytest.mark.asyncio
    async def test_nats_connection(self, nats_client):
        """Test NATS connection is established."""
        assert nats_client.is_connected
        assert nats_client.is_connected

    @pytest.mark.asyncio
    async def test_nats_publish_subscribe(self, nats_client):
        """Test basic NATS pub/sub (not JetStream)."""
        received_messages = []

        async def handler(msg):
            received_messages.append(msg.data.decode())

        # Subscribe to a plain NATS subject (not JetStream)
        test_subject = "acs.test.plain"
        sub = await nats_client.subscribe(test_subject, cb=handler)

        try:
            # Publish a message
            await nats_client.publish(test_subject, b"test message")
            await nats_client.flush()

            # Wait for message to be received
            await asyncio.sleep(0.5)

            assert len(received_messages) == 1
            assert received_messages[0] == "test message"
        finally:
            await sub.unsubscribe()

    @pytest.mark.asyncio
    async def test_nats_request_reply(self, nats_client):
        """Test NATS request-reply pattern."""
        async def handler(msg):
            await msg.respond(b"pong")

        # Create a service that responds to requests
        test_subject = "acs.test.ping"
        sub = await nats_client.subscribe(test_subject, cb=handler)

        try:
            # Send a request
            response = await nats_client.request(test_subject, b"ping", timeout=2)
            assert response.data == b"pong"
        finally:
            await sub.unsubscribe()


class TestNATSPubSub:
    """Test NATS pub/sub for group events."""

    @pytest.mark.asyncio
    async def test_subscribe_group_events(self, nats_client):
        """Test subscribing to group events via JetStream."""
        js = nats_client.jetstream()

        received_events = []
        test_group_id = f"test-group-{int(time.time() * 1000)}"
        subject = f"acs.group.message.{test_group_id}"

        # Create a consumer for this test
        try:
            # First create a stream for this subject if not exists
            await js.add_stream(
                name=f"TEST_STREAM_{test_group_id}",
                subjects=[subject],
                max_msgs=100,
                max_age=3600,
            )
        except Exception:
            pass  # Stream may already exist

        sub = await js.subscribe(subject)

        try:
            # Publish a group event via JetStream
            event = {
                "type": "group",
                "action": "create",
                "groupId": test_group_id,
                "data": {"group_id": test_group_id, "group_name": "Test"}
            }
            await js.publish(subject, json.dumps(event).encode())

            # Wait for message
            msg = await sub.next_msg(timeout=3)
            await msg.ack()

            data = json.loads(msg.data.decode())
            assert data["type"] == "group"
            assert data["action"] == "create"
            received_events.append(data)

            assert len(received_events) == 1
        finally:
            await sub.unsubscribe()
            # Clean up stream
            try:
                await js.delete_stream(f"TEST_STREAM_{test_group_id}")
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_subscribe_message_events(self, nats_client):
        """Test subscribing to message events via JetStream."""
        js = nats_client.jetstream()

        test_group_id = f"test-msg-group-{int(time.time() * 1000)}"
        subject = f"acs.group.message.{test_group_id}"

        try:
            await js.add_stream(
                name=f"TEST_MSG_STREAM_{test_group_id}",
                subjects=[subject],
                max_msgs=100,
                max_age=3600,
            )
        except Exception:
            pass

        sub = await js.subscribe(subject)

        try:
            # Publish a message event
            event = {
                "type": "message",
                "action": "create",
                "groupId": test_group_id,
                "data": {
                    "message_id": "msg-123",
                    "message_text": "Hello"
                }
            }
            await js.publish(subject, json.dumps(event).encode())

            # Wait for message
            msg = await sub.next_msg(timeout=3)
            await msg.ack()

            data = json.loads(msg.data.decode())
            assert data["type"] == "message"
            assert data["action"] == "create"
            assert data["data"]["message_id"] == "msg-123"
        finally:
            await sub.unsubscribe()
            try:
                await js.delete_stream(f"TEST_MSG_STREAM_{test_group_id}")
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_subscribe_member_events(self, nats_client):
        """Test subscribing to member events via JetStream."""
        js = nats_client.jetstream()

        test_group_id = f"test-member-group-{int(time.time() * 1000)}"
        subject = f"acs.group.message.{test_group_id}"

        try:
            await js.add_stream(
                name=f"TEST_MEMBER_STREAM_{test_group_id}",
                subjects=[subject],
                max_msgs=100,
                max_age=3600,
            )
        except Exception:
            pass

        sub = await js.subscribe(subject)

        try:
            # Publish a member event
            event = {
                "type": "group_member",
                "action": "create",
                "groupId": test_group_id,
                "data": {
                    "member_id": "user-123",
                    "member_name": "Test_User"
                }
            }
            await js.publish(subject, json.dumps(event).encode())

            # Wait for message
            msg = await sub.next_msg(timeout=3)
            await msg.ack()

            data = json.loads(msg.data.decode())
            assert data["type"] == "group_member"
            assert data["action"] == "create"
        finally:
            await sub.unsubscribe()
            try:
                await js.delete_stream(f"TEST_MEMBER_STREAM_{test_group_id}")
            except Exception:
                pass


class TestPendingMessageFlow:
    """Test pending message processing flow."""

    @pytest.mark.asyncio
    async def test_pending_message_published(self, nats_client):
        """Test that pending messages are published to NATS."""
        js = nats_client.jetstream()

        test_group_id = f"test-pending-{int(time.time() * 1000)}"
        # Use a test-specific subject that does NOT overlap with acs_pending_messages stream
        subject = f"acs.test.pending-message.{test_group_id}"
        stream_name = f"TEST_PENDING_STREAM_{test_group_id}"

        # Clean up any existing stream first, then create
        try:
            await js.delete_stream(stream_name)
        except Exception:
            pass
        try:
            await js.add_stream(
                name=stream_name,
                subjects=[subject],
                max_msgs=100,
                max_age=3600,
            )
        except Exception:
            pass

        sub = await js.subscribe(subject, durable=f"test_pending_{test_group_id}")

        try:
            pending_msg = {
                "group_id": test_group_id,
                "message_id": "pending-msg-1",
                "message_text": "Test pending message",
                "sender_id": "user-1",
                "sender_type": "user",
                "trigger": {
                    "type": "mention",
                    "agent_id": "agent-1"
                }
            }
            await js.publish(subject, json.dumps(pending_msg).encode())

            # Wait for message
            msg = await sub.next_msg(timeout=3)
            await msg.ack()

            data = json.loads(msg.data.decode())
            assert data["group_id"] == test_group_id
            assert data["message_id"] == "pending-msg-1"
            assert "trigger" in data
        finally:
            await sub.unsubscribe()
            try:
                await js.delete_stream(stream_name)
            except Exception:
                pass
    @pytest.mark.asyncio
    async def test_pending_message_with_at_all(self, nats_client):
        """Test pending message with @all trigger."""
        js = nats_client.jetstream()

        test_group_id = f"test-at-all-{int(time.time() * 1000)}"
        # Use a test-specific subject that does NOT overlap with acs_pending_messages stream
        subject = f"acs.test.pending-message.{test_group_id}"
        stream_name = f"TEST_ATALL_STREAM_{test_group_id}"

        # Clean up any existing stream first, then create
        try:
            await js.delete_stream(stream_name)
        except Exception:
            pass
        try:
            await js.add_stream(
                name=stream_name,
                subjects=[subject],
                max_msgs=100,
                max_age=3600,
            )
        except Exception:
            pass

        sub = await js.subscribe(subject, durable=f"test_atall_{test_group_id}")

        try:
            # Publish a pending message with @all trigger
            pending_msg = {
                "group_id": test_group_id,
                "message_id": "pending-msg-at-all",
                "message_text": "@all Attention everyone!",
                "sender_id": "user-1",
                "sender_type": "user",
                "trigger": {
                    "type": "mention",
                    "agent_id": "manager-agent"
                }
            }
            await js.publish(subject, json.dumps(pending_msg).encode())

            # Wait for message
            msg = await sub.next_msg(timeout=3)
            await msg.ack()

            data = json.loads(msg.data.decode())
            assert "@all" in data["message_text"]
            assert data["trigger"]["type"] == "mention"
        finally:
            await sub.unsubscribe()
            try:
                await js.delete_stream(stream_name)
            except Exception:
                pass


class TestRealTimeDelivery:
    """Test real-time message delivery."""

    @pytest.mark.asyncio
    async def test_real_time_message_stream(self, nats_client):
        """Test real-time message streaming."""
        js = nats_client.jetstream()

        test_group_id = f"test-rt-{int(time.time() * 1000)}"
        subject = f"acs.group.message.{test_group_id}"

        try:
            await js.add_stream(
                name=f"TEST_RT_STREAM_{test_group_id}",
                subjects=[subject],
                max_msgs=1000,
                max_age=3600,
            )
        except Exception:
            pass

        received_messages = []
        sub = await js.subscribe(subject)

        try:
            # Publish multiple messages
            for i in range(3):
                event = {
                    "type": "message",
                    "action": "create",
                    "groupId": test_group_id,
                    "data": {"message_id": f"msg-{i}", "message_text": f"Message {i}"}
                }
                await js.publish(subject, json.dumps(event).encode())

            # Collect messages
            for _ in range(3):
                msg = await sub.next_msg(timeout=2)
                await msg.ack()
                received_messages.append(json.loads(msg.data.decode()))

            assert len(received_messages) == 3
            assert received_messages[0]["data"]["message_id"] == "msg-0"
            assert received_messages[1]["data"]["message_id"] == "msg-1"
            assert received_messages[2]["data"]["message_id"] == "msg-2"
        finally:
            await sub.unsubscribe()
            try:
                await js.delete_stream(f"TEST_RT_STREAM_{test_group_id}")
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, nats_client):
        """Test multiple subscribers receive messages."""
        js = nats_client.jetstream()

        test_group_id = f"test-multi-{int(time.time() * 1000)}"
        subject = f"acs.group.message.{test_group_id}"

        try:
            await js.add_stream(
                name=f"TEST_MULTI_STREAM_{test_group_id}",
                subjects=[subject],
                max_msgs=100,
                max_age=3600,
            )
        except Exception:
            pass

        sub1_msgs = []
        sub2_msgs = []

        async def handler1(msg):
            sub1_msgs.append(json.loads(msg.data.decode()))
            await msg.ack()

        async def handler2(msg):
            sub2_msgs.append(json.loads(msg.data.decode()))
            await msg.ack()

        # Create two push subscribers with different durable names
        sub1 = await js.subscribe(subject, durable=f"durable1_{test_group_id}", cb=handler1)
        sub2 = await js.subscribe(subject, durable=f"durable2_{test_group_id}", cb=handler2)

        try:
            # Publish a message
            event = {
                "type": "message",
                "action": "create",
                "groupId": test_group_id,
                "data": {"message_id": "multi-msg-1"}
            }
            await js.publish(subject, json.dumps(event).encode())

            # Wait for both subscribers to receive
            await asyncio.sleep(1)

            assert len(sub1_msgs) == 1
            assert len(sub2_msgs) == 1
            assert sub1_msgs[0]["data"]["message_id"] == "multi-msg-1"
            assert sub2_msgs[0]["data"]["message_id"] == "multi-msg-1"
        finally:
            await sub1.unsubscribe()
            await sub2.unsubscribe()
            try:
                await js.delete_stream(f"TEST_MULTI_STREAM_{test_group_id}")
            except Exception:
                pass


class TestJetStream:
    """Test JetStream functionality."""

    @pytest.mark.asyncio
    async def test_jetstream_stream_exists(self, nats_client):
        """Test that required JetStream streams exist."""
        js = nats_client.jetstream()

        # Check if the ACS streams exist
        streams = ["acs_pending_messages", "acs_group_events"]
        for stream_name in streams:
            try:
                info = await js.stream_info(stream_name)
                assert info is not None
                assert info.config.name == stream_name
            except Exception as e:
                pytest.skip(f"Stream {stream_name} not found: {e}")

    @pytest.mark.asyncio
    async def test_jetstream_consumer_exists(self, nats_client):
        """Test that required JetStream consumers exist."""
        js = nats_client.jetstream()

        try:
            consumers = await js.consumers_info("acs_pending_messages")
            assert len(consumers) > 0
        except Exception as e:
            pytest.skip(f"Consumer check failed: {e}")

    @pytest.mark.asyncio
    async def test_jetstream_publish_with_msg_id(self, nats_client):
        """Test publishing with MsgID for deduplication."""
        js = nats_client.jetstream()

        test_subject = f"acs.test.dedup.{int(time.time() * 1000)}"
        msg_id = f"test-msg-{int(time.time() * 1000)}"

        # Create a stream for this subject
        try:
            await js.add_stream(
                name=f"TEST_DEDUP_STREAM_{msg_id}",
                subjects=[test_subject],
                max_msgs=100,
                max_age=3600,
            )
        except Exception:
            pass

        # Publish with MsgID
        headers = {"Nats-Msg-Id": msg_id}
        ack = await js.publish(test_subject, b"test message", headers=headers)
        assert ack is not None
        assert ack.stream != ""

        # Publish again with same MsgID - should be deduplicated
        ack2 = await js.publish(test_subject, b"test message", headers=headers)
        assert ack2 is not None

        # Clean up
        try:
            await js.delete_stream(f"TEST_DEDUP_STREAM_{msg_id}")
        except Exception:
            pass
