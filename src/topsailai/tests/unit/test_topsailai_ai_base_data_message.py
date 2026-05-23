"""
Unit tests for topsailai.ai_base.data.message module.

Tests cover BaseMessageItem, Message, LLMResponseItem, and LLMRequestItem.
"""

import pytest

from topsailai.ai_base.data.message import (
    BaseMessageItem,
    LLMRequestItem,
    LLMResponseItem,
    Message,
)


class TestBaseMessageItem:
    """Tests for BaseMessageItem class."""

    def test_init_default_values(self):
        """Test BaseMessageItem initializes with empty strings."""
        item = BaseMessageItem()
        assert item.step_name == ""
        assert item.raw_text == ""

    def test_set_step_name(self):
        """Test setting step_name attribute."""
        item = BaseMessageItem()
        item.step_name = "thought"
        assert item.step_name == "thought"

    def test_set_raw_text(self):
        """Test setting raw_text attribute."""
        item = BaseMessageItem()
        item.raw_text = "Hello world"
        assert item.raw_text == "Hello world"

    def test_set_raw_text_to_dict(self):
        """Test setting raw_text to a dictionary."""
        item = BaseMessageItem()
        test_dict = {"key": "value"}
        item.raw_text = test_dict
        assert item.raw_text == test_dict

    def test_multiple_instances_independent(self):
        """Test that multiple instances are independent."""
        item1 = BaseMessageItem()
        item1.step_name = "action"
        item1.raw_text = "text1"

        item2 = BaseMessageItem()
        item2.step_name = "thought"
        item2.raw_text = "text2"

        assert item1.step_name == "action"
        assert item1.raw_text == "text1"
        assert item2.step_name == "thought"
        assert item2.raw_text == "text2"


class TestMessage:
    """Tests for Message class."""

    def test_init_empty(self):
        """Test Message initializes with no items."""
        msg = Message()
        assert msg.message == ()

    def test_init_single_item(self):
        """Test Message initializes with a single item."""
        item = BaseMessageItem()
        item.step_name = "action"
        msg = Message(item)
        assert len(msg.message) == 1
        assert msg.message[0] == item
        assert msg.message[0].step_name == "action"

    def test_init_multiple_items(self):
        """Test Message initializes with multiple items."""
        item1 = BaseMessageItem()
        item1.step_name = "thought"
        item2 = BaseMessageItem()
        item2.step_name = "action"
        item3 = BaseMessageItem()
        item3.step_name = "observation"

        msg = Message(item1, item2, item3)
        assert len(msg.message) == 3
        assert msg.message[0].step_name == "thought"
        assert msg.message[1].step_name == "action"
        assert msg.message[2].step_name == "observation"

    def test_init_with_llm_response_item(self):
        """Test Message with LLMResponseItem."""
        item = LLMResponseItem()
        item.step_name = "action"
        item.raw_text = '{"tool_call": "test_tool"}'
        msg = Message(item)
        assert len(msg.message) == 1
        assert isinstance(msg.message[0], LLMResponseItem)

    def test_init_with_llm_request_item(self):
        """Test Message with LLMRequestItem."""
        item = LLMRequestItem()
        item.step_name = "task"
        item.raw_text = "Do something"
        msg = Message(item)
        assert len(msg.message) == 1
        assert isinstance(msg.message[0], LLMRequestItem)

    def test_init_mixed_items(self):
        """Test Message with mixed item types."""
        response_item = LLMResponseItem()
        response_item.step_name = "action"
        request_item = LLMRequestItem()
        request_item.step_name = "observation"
        base_item = BaseMessageItem()
        base_item.step_name = "thought"

        msg = Message(response_item, request_item, base_item)
        assert len(msg.message) == 3
        assert isinstance(msg.message[0], LLMResponseItem)
        assert isinstance(msg.message[1], LLMRequestItem)
        assert isinstance(msg.message[2], BaseMessageItem)

    def test_message_tuple_immutable(self):
        """Test that message tuple is immutable."""
        item = BaseMessageItem()
        msg = Message(item)
        with pytest.raises(TypeError):
            msg.message[0] = BaseMessageItem()


class TestLLMResponseItem:
    """Tests for LLMResponseItem class."""

    def test_is_subclass_of_base_message_item(self):
        """Test LLMResponseItem is a subclass of BaseMessageItem."""
        assert issubclass(LLMResponseItem, BaseMessageItem)

    def test_init_default_values(self):
        """Test LLMResponseItem initializes with empty strings."""
        item = LLMResponseItem()
        assert item.step_name == ""
        assert item.raw_text == ""

    def test_init_with_action_data(self):
        """Test LLMResponseItem with action-like data."""
        item = LLMResponseItem()
        item.step_name = "action"
        item.raw_text = {
            "tool_call": "TOOL-NAME",
            "tool_args": {
                "arg1": "1",
                "arg2": "2",
            },
        }
        assert item.step_name == "action"
        assert item.raw_text["tool_call"] == "TOOL-NAME"
        assert item.raw_text["tool_args"]["arg1"] == "1"

    def test_init_with_json_string(self):
        """Test LLMResponseItem with JSON string raw_text."""
        item = LLMResponseItem()
        item.step_name = "action"
        item.raw_text = '{"tool_call": "test_tool", "tool_args": {}}'
        assert isinstance(item.raw_text, str)
        assert "tool_call" in item.raw_text

    def test_is_instance_of_base_message_item(self):
        """Test LLMResponseItem instance is also BaseMessageItem instance."""
        item = LLMResponseItem()
        assert isinstance(item, BaseMessageItem)


class TestLLMRequestItem:
    """Tests for LLMRequestItem class."""

    def test_is_subclass_of_base_message_item(self):
        """Test LLMRequestItem is a subclass of BaseMessageItem."""
        assert issubclass(LLMRequestItem, BaseMessageItem)

    def test_init_default_values(self):
        """Test LLMRequestItem initializes with empty strings."""
        item = LLMRequestItem()
        assert item.step_name == ""
        assert item.raw_text == ""

    def test_init_with_task_data(self):
        """Test LLMRequestItem with task-like data."""
        item = LLMRequestItem()
        item.step_name = "task"
        item.raw_text = "Please analyze this data"
        assert item.step_name == "task"
        assert item.raw_text == "Please analyze this data"

    def test_init_with_observation_data(self):
        """Test LLMRequestItem with observation-like data."""
        item = LLMRequestItem()
        item.step_name = "observation"
        item.raw_text = "The result is 42"
        assert item.step_name == "observation"
        assert item.raw_text == "The result is 42"

    def test_is_instance_of_base_message_item(self):
        """Test LLMRequestItem instance is also BaseMessageItem instance."""
        item = LLMRequestItem()
        assert isinstance(item, BaseMessageItem)


class TestIntegration:
    """Integration tests combining multiple classes."""

    def test_full_conversation_flow(self):
        """Test simulating a full conversation flow with multiple messages."""
        # User task
        task = LLMRequestItem()
        task.step_name = "task"
        task.raw_text = "Calculate 2 + 2"

        # LLM thought
        thought = LLMResponseItem()
        thought.step_name = "thought"
        thought.raw_text = "I need to use the calculator tool"

        # LLM action
        action = LLMResponseItem()
        action.step_name = "action"
        action.raw_text = {
            "tool_call": "calculator",
            "tool_args": {"expression": "2 + 2"},
        }

        # Observation
        observation = LLMRequestItem()
        observation.step_name = "observation"
        observation.raw_text = "4"

        msg = Message(task, thought, action, observation)
        assert len(msg.message) == 4
        assert msg.message[0].step_name == "task"
        assert msg.message[1].step_name == "thought"
        assert msg.message[2].step_name == "action"
        assert msg.message[3].step_name == "observation"
        assert msg.message[2].raw_text["tool_call"] == "calculator"
        assert msg.message[3].raw_text == "4"

    def test_empty_message_in_conversation(self):
        """Test that empty messages are handled correctly."""
        empty_response = LLMResponseItem()
        empty_request = LLMRequestItem()
        msg = Message(empty_response, empty_request)
        assert len(msg.message) == 2
        assert msg.message[0].step_name == ""
        assert msg.message[0].raw_text == ""
        assert msg.message[1].step_name == ""
        assert msg.message[1].raw_text == ""
