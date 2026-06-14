"""
Unit tests for topsailai.ai_base.multimodal.message module.

Tests cover ContentItem classes (TextContent, ImageContent, VideoContent, AudioContent)
and MultimodalMessage class.

Author: AI
Created: 2026-06-14
"""

import base64
import os
from unittest.mock import patch, mock_open

import pytest

from topsailai.ai_base.multimodal.message import (
    ContentItem,
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    MultimodalMessage,
    _is_url,
    _read_file_as_base64,
    _get_mime_type,
)
from topsailai.ai_base.multimodal.constants import (
    CONTENT_TYPE_TEXT,
    CONTENT_TYPE_IMAGE_URL,
    CONTENT_TYPE_VIDEO,
    CONTENT_TYPE_AUDIO,
    DEFAULT_IMAGE_DETAIL,
    IMAGE_MIME_TYPES,
    VIDEO_MIME_TYPES,
    AUDIO_MIME_TYPES,
    MAX_BASE64_FILE_SIZE,
)


#################################################################################
# Helper Function Tests
#################################################################################

class TestIsUrl:
    """Tests for _is_url helper function."""

    def test_http_url(self):
        """Test that http URLs are recognized."""
        assert _is_url("http://example.com/image.png") is True

    def test_https_url(self):
        """Test that https URLs are recognized."""
        assert _is_url("https://example.com/image.png") is True

    def test_ftp_url_not_supported(self):
        """Test that ftp URLs are not recognized."""
        assert _is_url("ftp://example.com/image.png") is False

    def test_local_path(self):
        """Test that local paths are not URLs."""
        assert _is_url("/path/to/image.png") is False

    def test_relative_path(self):
        """Test that relative paths are not URLs."""
        assert _is_url("./image.png") is False

    def test_empty_string(self):
        """Test that empty string is not a URL."""
        assert _is_url("") is False

    def test_none(self):
        """Test that None is not a URL."""
        assert _is_url(None) is False


class TestReadFileAsBase64:
    """Tests for _read_file_as_base64 helper function."""

    def test_read_existing_file(self):
        """Test reading an existing file as base64."""
        test_content = b"Hello, World!"
        expected_b64 = base64.b64encode(test_content).decode("utf-8")

        with patch("builtins.open", mock_open(read_data=test_content)):
            with patch("os.path.exists", return_value=True):
                with patch("os.path.getsize", return_value=len(test_content)):
                    result = _read_file_as_base64("/fake/path/test.txt")

        assert result == expected_b64

    def test_file_not_found(self):
        """Test that FileNotFoundError is raised for missing files."""
        with patch("os.path.exists", return_value=False):
            with pytest.raises(FileNotFoundError):
                _read_file_as_base64("/nonexistent/file.png")

    def test_file_too_large(self):
        """Test that ValueError is raised for files exceeding max size."""
        with patch("os.path.exists", return_value=True):
            with patch("os.path.getsize", return_value=MAX_BASE64_FILE_SIZE + 1):
                with pytest.raises(ValueError) as exc_info:
                    _read_file_as_base64("/fake/path/large.png")
                assert "exceeds maximum allowed" in str(exc_info.value)


class TestGetMimeType:
    """Tests for _get_mime_type helper function."""

    def test_known_image_extension(self):
        """Test MIME type lookup for known image extensions."""
        assert _get_mime_type("image.png", IMAGE_MIME_TYPES) == "image/png"
        assert _get_mime_type("image.jpg", IMAGE_MIME_TYPES) == "image/jpeg"
        assert _get_mime_type("image.jpeg", IMAGE_MIME_TYPES) == "image/jpeg"

    def test_known_video_extension(self):
        """Test MIME type lookup for known video extensions."""
        assert _get_mime_type("video.mp4", VIDEO_MIME_TYPES) == "video/mp4"
        assert _get_mime_type("video.webm", VIDEO_MIME_TYPES) == "video/webm"

    def test_known_audio_extension(self):
        """Test MIME type lookup for known audio extensions."""
        assert _get_mime_type("audio.mp3", AUDIO_MIME_TYPES) == "audio/mpeg"
        assert _get_mime_type("audio.wav", AUDIO_MIME_TYPES) == "audio/wav"

    def test_unknown_extension(self):
        """Test default MIME type for unknown extensions."""
        assert _get_mime_type("file.xyz", IMAGE_MIME_TYPES) == "application/octet-stream"

    def test_no_extension(self):
        """Test default MIME type for files without extension."""
        assert _get_mime_type("file", IMAGE_MIME_TYPES) == "application/octet-stream"

    def test_case_insensitive(self):
        """Test that extension lookup is case-insensitive."""
        assert _get_mime_type("image.PNG", IMAGE_MIME_TYPES) == "image/png"
        assert _get_mime_type("image.JPG", IMAGE_MIME_TYPES) == "image/jpeg"


#################################################################################
# TextContent Tests
#################################################################################

class TestTextContent:
    """Tests for TextContent class."""

    def test_creation(self):
        """Test basic TextContent creation."""
        content = TextContent("Hello, world!")
        assert content.type == CONTENT_TYPE_TEXT
        assert content.text == "Hello, world!"

    def test_to_dict(self):
        """Test TextContent to_dict() output format."""
        content = TextContent("Hello, world!")
        result = content.to_dict()
        assert result == {"type": CONTENT_TYPE_TEXT, "text": "Hello, world!"}

    def test_empty_text(self):
        """Test TextContent with empty string."""
        content = TextContent("")
        assert content.text == ""
        assert content.to_dict() == {"type": CONTENT_TYPE_TEXT, "text": ""}

    def test_multiline_text(self):
        """Test TextContent with multiline string."""
        text = "Line 1\nLine 2\nLine 3"
        content = TextContent(text)
        assert content.text == text
        assert content.to_dict()["text"] == text

    def test_unicode_text(self):
        """Test TextContent with unicode characters."""
        text = "Hello \u4e16\u754c \ud83c\udf0d"
        content = TextContent(text)
        assert content.text == text

    def test_invalid_type_raises(self):
        """Test that non-string text raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            TextContent(123)
        assert "must be a string" in str(exc_info.value)

    def test_none_raises(self):
        """Test that None text raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            TextContent(None)
        assert "must be a string" in str(exc_info.value)

    def test_repr(self):
        """Test TextContent repr format."""
        content = TextContent("test")
        assert "TextContent" in repr(content)
        assert "test" in repr(content)


#################################################################################
# ImageContent Tests
#################################################################################

class TestImageContent:
    """Tests for ImageContent class."""

    def test_creation_with_url(self):
        """Test ImageContent creation with URL source."""
        content = ImageContent("https://example.com/image.png")
        assert content.type == CONTENT_TYPE_IMAGE_URL
        assert content.source == "https://example.com/image.png"
        assert content.detail == DEFAULT_IMAGE_DETAIL

    def test_creation_with_local_path(self):
        """Test ImageContent creation with local file path."""
        content = ImageContent("/path/to/image.png")
        assert content.source == "/path/to/image.png"

    def test_creation_with_custom_detail(self):
        """Test ImageContent creation with custom detail level."""
        content = ImageContent("https://example.com/image.png", detail="high")
        assert content.detail == "high"

    def test_to_dict_with_url(self):
        """Test ImageContent to_dict() with URL source."""
        content = ImageContent("https://example.com/image.png", detail="low")
        result = content.to_dict()
        assert result == {
            "type": CONTENT_TYPE_IMAGE_URL,
            "image_url": {
                "url": "https://example.com/image.png",
                "detail": "low",
            },
        }

    def test_to_dict_with_local_file(self):
        """Test ImageContent to_dict() with local file (mocked base64)."""
        test_bytes = b"fake_image_data"
        expected_b64 = base64.b64encode(test_bytes).decode("utf-8")

        with patch("builtins.open", mock_open(read_data=test_bytes)):
            with patch("os.path.exists", return_value=True):
                with patch("os.path.getsize", return_value=len(test_bytes)):
                    content = ImageContent("/fake/path/image.png")
                    result = content.to_dict()

        assert result["type"] == CONTENT_TYPE_IMAGE_URL
        assert result["image_url"]["detail"] == DEFAULT_IMAGE_DETAIL
        assert result["image_url"]["url"].startswith("data:image/png;base64,")
        assert result["image_url"]["url"].endswith(expected_b64)

    def test_to_dict_with_local_jpeg(self):
        """Test ImageContent to_dict() with local JPEG file."""
        test_bytes = b"fake_jpeg_data"
        expected_b64 = base64.b64encode(test_bytes).decode("utf-8")

        with patch("builtins.open", mock_open(read_data=test_bytes)):
            with patch("os.path.exists", return_value=True):
                with patch("os.path.getsize", return_value=len(test_bytes)):
                    content = ImageContent("/fake/path/photo.jpg")
                    result = content.to_dict()

        assert result["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert result["image_url"]["url"].endswith(expected_b64)

    def test_empty_source_raises(self):
        """Test that empty source raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ImageContent("")
        assert "non-empty string" in str(exc_info.value)

    def test_none_source_raises(self):
        """Test that None source raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ImageContent(None)
        assert "non-empty string" in str(exc_info.value)

    def test_invalid_detail_raises(self):
        """Test that invalid detail level raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ImageContent("https://example.com/image.png", detail="invalid")
        assert "Invalid detail level" in str(exc_info.value)

    def test_file_not_found_raises(self):
        """Test that missing local file raises FileNotFoundError."""
        with patch("os.path.exists", return_value=False):
            content = ImageContent("/nonexistent/image.png")
            with pytest.raises(FileNotFoundError):
                content.to_dict()

    def test_repr(self):
        """Test ImageContent repr format."""
        content = ImageContent("https://example.com/image.png")
        assert "ImageContent" in repr(content)


#################################################################################
# VideoContent Tests
#################################################################################

class TestVideoContent:
    """Tests for VideoContent class."""

    def test_creation_with_url(self):
        """Test VideoContent creation with URL source."""
        content = VideoContent("https://example.com/video.mp4")
        assert content.type == CONTENT_TYPE_VIDEO
        assert content.source == "https://example.com/video.mp4"

    def test_creation_with_local_path(self):
        """Test VideoContent creation with local file path."""
        content = VideoContent("/path/to/video.mp4")
        assert content.source == "/path/to/video.mp4"

    def test_to_dict_with_url(self):
        """Test VideoContent to_dict() with URL source."""
        content = VideoContent("https://example.com/video.mp4")
        result = content.to_dict()
        assert result == {
            "type": CONTENT_TYPE_VIDEO,
            "video": {
                "url": "https://example.com/video.mp4",
            },
        }

    def test_to_dict_with_local_file(self):
        """Test VideoContent to_dict() with local file (mocked base64)."""
        test_bytes = b"fake_video_data"
        expected_b64 = base64.b64encode(test_bytes).decode("utf-8")

        with patch("builtins.open", mock_open(read_data=test_bytes)):
            with patch("os.path.exists", return_value=True):
                with patch("os.path.getsize", return_value=len(test_bytes)):
                    content = VideoContent("/fake/path/video.mp4")
                    result = content.to_dict()

        assert result["type"] == CONTENT_TYPE_VIDEO
        assert result["video"]["url"].startswith("data:video/mp4;base64,")
        assert result["video"]["url"].endswith(expected_b64)

    def test_empty_source_raises(self):
        """Test that empty source raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            VideoContent("")
        assert "non-empty string" in str(exc_info.value)

    def test_none_source_raises(self):
        """Test that None source raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            VideoContent(None)
        assert "non-empty string" in str(exc_info.value)

    def test_file_not_found_raises(self):
        """Test that missing local file raises FileNotFoundError."""
        with patch("os.path.exists", return_value=False):
            content = VideoContent("/nonexistent/video.mp4")
            with pytest.raises(FileNotFoundError):
                content.to_dict()

    def test_repr(self):
        """Test VideoContent repr format."""
        content = VideoContent("https://example.com/video.mp4")
        assert "VideoContent" in repr(content)


#################################################################################
# AudioContent Tests
#################################################################################

class TestAudioContent:
    """Tests for AudioContent class."""

    def test_creation_with_url(self):
        """Test AudioContent creation with URL source."""
        content = AudioContent("https://example.com/audio.mp3")
        assert content.type == CONTENT_TYPE_AUDIO
        assert content.source == "https://example.com/audio.mp3"

    def test_creation_with_local_path(self):
        """Test AudioContent creation with local file path."""
        content = AudioContent("/path/to/audio.mp3")
        assert content.source == "/path/to/audio.mp3"

    def test_to_dict_with_url(self):
        """Test AudioContent to_dict() with URL source."""
        content = AudioContent("https://example.com/audio.mp3")
        result = content.to_dict()
        assert result == {
            "type": CONTENT_TYPE_AUDIO,
            "audio": {
                "url": "https://example.com/audio.mp3",
            },
        }

    def test_to_dict_with_local_file(self):
        """Test AudioContent to_dict() with local file (mocked base64)."""
        test_bytes = b"fake_audio_data"
        expected_b64 = base64.b64encode(test_bytes).decode("utf-8")

        with patch("builtins.open", mock_open(read_data=test_bytes)):
            with patch("os.path.exists", return_value=True):
                with patch("os.path.getsize", return_value=len(test_bytes)):
                    content = AudioContent("/fake/path/audio.mp3")
                    result = content.to_dict()

        assert result["type"] == CONTENT_TYPE_AUDIO
        assert result["audio"]["url"].startswith("data:audio/mpeg;base64,")
        assert result["audio"]["url"].endswith(expected_b64)

    def test_empty_source_raises(self):
        """Test that empty source raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            AudioContent("")
        assert "non-empty string" in str(exc_info.value)

    def test_none_source_raises(self):
        """Test that None source raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            AudioContent(None)
        assert "non-empty string" in str(exc_info.value)

    def test_file_not_found_raises(self):
        """Test that missing local file raises FileNotFoundError."""
        with patch("os.path.exists", return_value=False):
            content = AudioContent("/nonexistent/audio.mp3")
            with pytest.raises(FileNotFoundError):
                content.to_dict()

    def test_repr(self):
        """Test AudioContent repr format."""
        content = AudioContent("https://example.com/audio.mp3")
        assert "AudioContent" in repr(content)


#################################################################################
# MultimodalMessage Tests
#################################################################################

class TestMultimodalMessage:
    """Tests for MultimodalMessage class."""

    def test_creation_with_single_text(self):
        """Test MultimodalMessage creation with single TextContent."""
        text = TextContent("Hello")
        msg = MultimodalMessage("user", [text])
        assert msg.role == "user"
        assert len(msg.content_items) == 1
        assert msg.content_items[0] == text

    def test_creation_with_multiple_items(self):
        """Test MultimodalMessage creation with multiple content items."""
        text = TextContent("Describe this image")
        image = ImageContent("https://example.com/image.png")
        msg = MultimodalMessage("user", [text, image])
        assert len(msg.content_items) == 2
        assert msg.content_items[0].type == CONTENT_TYPE_TEXT
        assert msg.content_items[1].type == CONTENT_TYPE_IMAGE_URL

    def test_creation_with_tool_call_id(self):
        """Test MultimodalMessage creation with tool_call_id."""
        text = TextContent("Tool result")
        msg = MultimodalMessage("tool", [text], tool_call_id="call_123")
        assert msg.tool_call_id == "call_123"

    def test_creation_without_tool_call_id(self):
        """Test MultimodalMessage creation without tool_call_id."""
        text = TextContent("Hello")
        msg = MultimodalMessage("user", [text])
        assert msg.tool_call_id is None

    def test_empty_role_raises(self):
        """Test that empty role raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            MultimodalMessage("", [TextContent("test")])
        assert "non-empty string" in str(exc_info.value)

    def test_none_role_raises(self):
        """Test that None role raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            MultimodalMessage(None, [TextContent("test")])
        assert "non-empty string" in str(exc_info.value)

    def test_empty_content_items_raises(self):
        """Test that empty content_items raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            MultimodalMessage("user", [])
        assert "must not be empty" in str(exc_info.value)

    def test_invalid_content_item_raises(self):
        """Test that non-ContentItem in content_items raises TypeError."""
        with pytest.raises(TypeError) as exc_info:
            MultimodalMessage("user", ["not a content item"])
        assert "must be a ContentItem" in str(exc_info.value)

    def test_mixed_invalid_content_items_raises(self):
        """Test that mixed valid/invalid content_items raises TypeError."""
        with pytest.raises(TypeError) as exc_info:
            MultimodalMessage("user", [TextContent("valid"), "invalid"])
        assert "must be a ContentItem" in str(exc_info.value)
        assert "content_items[1]" in str(exc_info.value)

    def test_to_dict_single_text(self):
        """Test to_dict() with single TextContent returns simple format."""
        msg = MultimodalMessage("user", [TextContent("Hello, world!")])
        result = msg.to_dict()
        assert result == {"role": "user", "content": "Hello, world!"}

    def test_to_dict_multiple_items(self):
        """Test to_dict() with multiple content items returns content array."""
        text = TextContent("Describe this")
        image = ImageContent("https://example.com/image.png")
        msg = MultimodalMessage("user", [text, image])
        result = msg.to_dict()
        assert result["role"] == "user"
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2
        assert result["content"][0] == {"type": CONTENT_TYPE_TEXT, "text": "Describe this"}
        assert result["content"][1]["type"] == CONTENT_TYPE_IMAGE_URL

    def test_to_dict_with_tool_call_id(self):
        """Test to_dict() includes tool_call_id when set."""
        msg = MultimodalMessage("tool", [TextContent("Result")], tool_call_id="call_123")
        result = msg.to_dict()
        assert result["role"] == "tool"
        assert result["content"] == "Result"
        assert result["tool_call_id"] == "call_123"

    def test_to_dict_without_tool_call_id(self):
        """Test to_dict() does NOT include tool_call_id when not set."""
        msg = MultimodalMessage("user", [TextContent("Hello")])
        result = msg.to_dict()
        assert "tool_call_id" not in result

    def test_to_dict_text_plus_image(self):
        """Test to_dict() with text + image returns content array."""
        text = TextContent("What is in this image?")
        image = ImageContent("https://example.com/image.png", detail="high")
        msg = MultimodalMessage("user", [text, image])
        result = msg.to_dict()
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == CONTENT_TYPE_TEXT
        assert result["content"][1]["type"] == CONTENT_TYPE_IMAGE_URL
        assert result["content"][1]["image_url"]["detail"] == "high"

    def test_to_dict_text_plus_video(self):
        """Test to_dict() with text + video returns content array."""
        text = TextContent("Describe this video")
        video = VideoContent("https://example.com/video.mp4")
        msg = MultimodalMessage("user", [text, video])
        result = msg.to_dict()
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == CONTENT_TYPE_TEXT
        assert result["content"][1]["type"] == CONTENT_TYPE_VIDEO

    def test_to_dict_text_plus_audio(self):
        """Test to_dict() with text + audio returns content array."""
        text = TextContent("Transcribe this audio")
        audio = AudioContent("https://example.com/audio.mp3")
        msg = MultimodalMessage("user", [text, audio])
        result = msg.to_dict()
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == CONTENT_TYPE_TEXT
        assert result["content"][1]["type"] == CONTENT_TYPE_AUDIO

    def test_to_dict_all_media_types(self):
        """Test to_dict() with all media types in one message."""
        text = TextContent("Analyze everything")
        image = ImageContent("https://example.com/image.png")
        video = VideoContent("https://example.com/video.mp4")
        audio = AudioContent("https://example.com/audio.mp3")
        msg = MultimodalMessage("user", [text, image, video, audio])
        result = msg.to_dict()
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 4
        assert result["content"][0]["type"] == CONTENT_TYPE_TEXT
        assert result["content"][1]["type"] == CONTENT_TYPE_IMAGE_URL
        assert result["content"][2]["type"] == CONTENT_TYPE_VIDEO
        assert result["content"][3]["type"] == CONTENT_TYPE_AUDIO

    def test_add_content_item(self):
        """Test add_content_item appends to message."""
        msg = MultimodalMessage("user", [TextContent("Hello")])
        msg.add_content_item(ImageContent("https://example.com/image.png"))
        assert len(msg.content_items) == 2
        assert msg.content_items[1].type == CONTENT_TYPE_IMAGE_URL

    def test_add_content_item_returns_self(self):
        """Test add_content_item returns self for chaining."""
        msg = MultimodalMessage("user", [TextContent("Hello")])
        result = msg.add_content_item(TextContent("World"))
        assert result is msg

    def test_add_content_item_invalid_raises(self):
        """Test add_content_item with invalid item raises TypeError."""
        msg = MultimodalMessage("user", [TextContent("Hello")])
        with pytest.raises(TypeError) as exc_info:
            msg.add_content_item("not a content item")
        assert "must be a ContentItem" in str(exc_info.value)

    def test_get_text_content_single(self):
        """Test get_text_content with single text item."""
        msg = MultimodalMessage("user", [TextContent("Hello")])
        assert msg.get_text_content() == "Hello"

    def test_get_text_content_multiple(self):
        """Test get_text_content with multiple text items."""
        msg = MultimodalMessage("user", [
            TextContent("Line 1"),
            TextContent("Line 2"),
        ])
        assert msg.get_text_content() == "Line 1\nLine 2"

    def test_get_text_content_with_media(self):
        """Test get_text_content ignores non-text items."""
        msg = MultimodalMessage("user", [
            TextContent("Describe this"),
            ImageContent("https://example.com/image.png"),
            TextContent("Please"),
        ])
        assert msg.get_text_content() == "Describe this\nPlease"

    def test_get_text_content_no_text(self):
        """Test get_text_content with no text items returns empty string."""
        msg = MultimodalMessage("user", [ImageContent("https://example.com/image.png")])
        assert msg.get_text_content() == ""

    def test_has_media_content_true(self):
        """Test has_media_content returns True when media is present."""
        msg = MultimodalMessage("user", [
            TextContent("Hello"),
            ImageContent("https://example.com/image.png"),
        ])
        assert msg.has_media_content() is True

    def test_has_media_content_false(self):
        """Test has_media_content returns False for text-only message."""
        msg = MultimodalMessage("user", [TextContent("Hello")])
        assert msg.has_media_content() is False

    def test_content_items_read_only(self):
        """Test that content_items returns a copy, not the original list."""
        text = TextContent("Hello")
        msg = MultimodalMessage("user", [text])
        items = msg.content_items
        items.append(ImageContent("https://example.com/image.png"))
        assert len(msg.content_items) == 1

    def test_repr(self):
        """Test MultimodalMessage repr format."""
        msg = MultimodalMessage("user", [TextContent("Hello")])
        repr_str = repr(msg)
        assert "MultimodalMessage" in repr_str
        assert "user" in repr_str
        assert "1" in repr_str

    def test_system_role(self):
        """Test MultimodalMessage with system role."""
        msg = MultimodalMessage("system", [TextContent("You are helpful")])
        assert msg.role == "system"
        assert msg.to_dict()["role"] == "system"

    def test_assistant_role(self):
        """Test MultimodalMessage with assistant role."""
        msg = MultimodalMessage("assistant", [TextContent("I can help")])
        assert msg.role == "assistant"
        assert msg.to_dict()["role"] == "assistant"

    def test_tool_role_with_tool_call_id(self):
        """Test MultimodalMessage with tool role and tool_call_id."""
        msg = MultimodalMessage("tool", [TextContent("42")], tool_call_id="call_abc")
        result = msg.to_dict()
        assert result["role"] == "tool"
        assert result["tool_call_id"] == "call_abc"
        assert result["content"] == "42"


#################################################################################
# Integration Tests
#################################################################################

class TestIntegration:
    """Integration tests combining multiple classes."""

    def test_full_multimodal_message_flow(self):
        """Test a complete multimodal message creation and serialization flow."""
        text = TextContent("What do you see in this image?")
        image = ImageContent("https://example.com/photo.jpg", detail="high")
        msg = MultimodalMessage("user", [text, image])

        result = msg.to_dict()
        assert result["role"] == "user"
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 2
        assert result["content"][0] == {"type": CONTENT_TYPE_TEXT, "text": "What do you see in this image?"}
        assert result["content"][1]["type"] == CONTENT_TYPE_IMAGE_URL
        assert result["content"][1]["image_url"]["url"] == "https://example.com/photo.jpg"
        assert result["content"][1]["image_url"]["detail"] == "high"

    def test_message_with_local_image_mocked(self):
        """Test complete flow with local image file (fully mocked)."""
        test_bytes = b"\x89PNG\r\n\x1a\n"  # PNG magic bytes
        expected_b64 = base64.b64encode(test_bytes).decode("utf-8")

        with patch("builtins.open", mock_open(read_data=test_bytes)):
            with patch("os.path.exists", return_value=True):
                with patch("os.path.getsize", return_value=len(test_bytes)):
                    text = TextContent("Analyze this chart")
                    image = ImageContent("/data/chart.png")
                    msg = MultimodalMessage("user", [text, image])
                    result = msg.to_dict()

        assert result["content"][1]["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"

    def test_conversation_sequence(self):
        """Test a sequence of messages simulating a conversation."""
        # System message
        system_msg = MultimodalMessage("system", [TextContent("You are a vision assistant.")])

        # User message with image
        user_text = TextContent("What is this?")
        user_image = ImageContent("https://example.com/object.png")
        user_msg = MultimodalMessage("user", [user_text, user_image])

        # Assistant response
        assistant_msg = MultimodalMessage("assistant", [TextContent("This is a cat.")])

        # Tool call result
        tool_msg = MultimodalMessage("tool", [TextContent("42")], tool_call_id="call_123")

        messages = [system_msg.to_dict(), user_msg.to_dict(), assistant_msg.to_dict(), tool_msg.to_dict()]

        assert messages[0] == {"role": "system", "content": "You are a vision assistant."}
        assert messages[1]["role"] == "user"
        assert isinstance(messages[1]["content"], list)
        assert messages[2] == {"role": "assistant", "content": "This is a cat."}
        assert messages[3] == {"role": "tool", "content": "42", "tool_call_id": "call_123"}

    def test_content_item_is_abstract(self):
        """Test that ContentItem cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ContentItem()

    def test_all_content_items_are_content_item_subclasses(self):
        """Test that all concrete content items are subclasses of ContentItem."""
        assert issubclass(TextContent, ContentItem)
        assert issubclass(ImageContent, ContentItem)
        assert issubclass(VideoContent, ContentItem)
        assert issubclass(AudioContent, ContentItem)

    def test_empty_text_content_to_dict(self):
        """Test TextContent with empty string serializes correctly."""
        msg = MultimodalMessage("user", [TextContent("")])
        result = msg.to_dict()
        assert result == {"role": "user", "content": ""}

    def test_whitespace_only_text_content(self):
        """Test TextContent with whitespace-only string."""
        msg = MultimodalMessage("user", [TextContent("   \n\t  ")])
        result = msg.to_dict()
        assert result["content"] == "   \n\t  "
