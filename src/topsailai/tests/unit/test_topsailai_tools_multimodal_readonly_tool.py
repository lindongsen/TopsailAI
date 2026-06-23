"""
Unit tests for tools/multimodal_readonly_tool.py module.

Tests cover recognize_image, recognize_voice, recognize_video functions,
TOOLS dict, PROMPT, and FLAG_TOOL_ENABLED.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from topsailai.tools import multimodal_readonly_tool
from topsailai.tools.multimodal_readonly_tool import (
    recognize_image,
    recognize_voice,
    recognize_video,
    _get_extra_prompt,
    TOOLS,
    PROMPT,
    FLAG_TOOL_ENABLED,
)


class TestRecognizeImage:
    """Test recognize_image function."""

    def test_recognize_image_with_valid_inputs(self):
        """Test recognize_image with valid image_source and prompt."""
        mock_chat = MagicMock()
        mock_chat.chat_with_image.return_value = "The image shows a cat."

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_image(
                    image_source="https://example.com/image.png",
                    prompt="What is in this image?",
                )

        assert result == "The image shows a cat."
        mock_chat.chat_with_image.assert_called_once_with(
            message="What is in this image?",
            image_source="https://example.com/image.png",
            detail="auto",
        )

    def test_recognize_image_with_empty_prompt_uses_default(self):
        """Test recognize_image uses default prompt when prompt is empty."""
        mock_chat = MagicMock()
        mock_chat.chat_with_image.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_image(
                    image_source="https://example.com/image.png",
                    prompt="",
                )

        mock_chat.chat_with_image.assert_called_once_with(
            message="Describe this image in detail.",
            image_source="https://example.com/image.png",
            detail="auto",
        )
        assert result == "Description"

    def test_recognize_image_with_relative_path(self):
        """Test recognize_image resolves relative paths."""
        mock_chat = MagicMock()
        mock_chat.chat_with_image.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.abspath", return_value="/abs/path/to/image.png"):
                with patch("os.path.exists", return_value=True):
                    result = recognize_image(
                        image_source="image.png",
                        prompt="Describe this",
                    )

        mock_chat.chat_with_image.assert_called_once_with(
            message="Describe this",
            image_source="/abs/path/to/image.png",
            detail="auto",
        )
        assert result == "Description"

    def test_recognize_image_empty_source_raises(self):
        """Test recognize_image raises ValueError for empty image_source."""
        with pytest.raises(ValueError, match="image_source must be a non-empty string"):
            recognize_image(image_source="", prompt="test")

    def test_recognize_image_none_source_raises(self):
        """Test recognize_image raises ValueError for None image_source."""
        with pytest.raises(ValueError, match="image_source must be a non-empty string"):
            recognize_image(image_source=None, prompt="test")

    def test_recognize_image_invalid_source_type_raises(self):
        """Test recognize_image raises ValueError for non-string image_source."""
        with pytest.raises(ValueError, match="image_source must be a non-empty string"):
            recognize_image(image_source=123, prompt="test")

    def test_recognize_image_strips_source(self):
        """Test recognize_image strips whitespace from image_source."""
        mock_chat = MagicMock()
        mock_chat.chat_with_image.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                recognize_image(
                    image_source="  https://example.com/image.png  ",
                    prompt="Describe",
                )

        call_args = mock_chat.chat_with_image.call_args
        assert call_args[1]["image_source"] == "https://example.com/image.png"

    def test_recognize_image_no_response(self):
        """Test recognize_image returns default when LLM returns None."""
        mock_chat = MagicMock()
        mock_chat.chat_with_image.return_value = None

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_image(
                    image_source="https://example.com/image.png",
                    prompt="Describe",
                )

        assert result == "No response from LLM."

    def test_recognize_image_system_prompt(self):
        """Test recognize_image creates chat with vision system prompt."""
        mock_chat = MagicMock()
        mock_chat.chat_with_image.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat") as mock_get_chat:
            mock_get_chat.return_value = mock_chat
            with patch("os.path.exists", return_value=False):
                recognize_image(
                    image_source="https://example.com/image.png",
                    prompt="Describe",
                )

        mock_get_chat.assert_called_once_with(
            message="Describe",
            system_prompt="You are a helpful assistant with strong image understanding capabilities. Describe images accurately and concisely.",
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )

    def test_recognize_image_with_local_absolute_path(self):
        """Test recognize_image with local absolute path."""
        mock_chat = MagicMock()
        mock_chat.chat_with_image.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=True):
                result = recognize_image(
                    image_source="/path/to/local/image.png",
                    prompt="Describe",
                )

        call_args = mock_chat.chat_with_image.call_args
        assert call_args[1]["image_source"] == "/path/to/local/image.png"
        assert result == "Description"

    def test_recognize_image_with_http_url(self):
        """Test recognize_image with http URL."""
        mock_chat = MagicMock()
        mock_chat.chat_with_image.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_image(
                    image_source="http://example.com/image.png",
                    prompt="Describe",
                )

        call_args = mock_chat.chat_with_image.call_args
        assert call_args[1]["image_source"] == "http://example.com/image.png"
        assert result == "Description"

    def test_recognize_image_with_model_name(self):
        """Test recognize_image sets model_name on chat.llm_model."""
        mock_chat = MagicMock()
        mock_chat.chat_with_image.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_image(
                    image_source="https://example.com/image.png",
                    prompt="Describe",
                    model_name="gpt-4o",
                )

        assert mock_chat.llm_model.model_name == "gpt-4o"
        assert result == "Description"

    def test_recognize_image_with_empty_model_name(self):
        """Test recognize_image does not change model_name when empty."""
        mock_chat = MagicMock()
        mock_chat.llm_model.model_name = "default-model"
        mock_chat.chat_with_image.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_image(
                    image_source="https://example.com/image.png",
                    prompt="Describe",
                    model_name="",
                )

        assert mock_chat.llm_model.model_name == "default-model"
        assert result == "Description"


class TestRecognizeVoice:
    """Test recognize_voice function."""

    def test_recognize_voice_with_valid_inputs(self):
        """Test recognize_voice with valid audio_source and prompt."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "The audio contains a conversation."

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_voice(
                    audio_source="https://example.com/audio.mp3",
                    prompt="What is in this audio?",
                )

        assert result == "The audio contains a conversation."
        mock_chat.chat_with_content.assert_called_once()
        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "What is in this audio?"

    def test_recognize_voice_with_empty_prompt_uses_default(self):
        """Test recognize_voice uses default prompt when prompt is empty."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Transcription"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_voice(
                    audio_source="https://example.com/audio.mp3",
                    prompt="",
                )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Transcribe and describe this audio content."
        assert result == "Transcription"

    def test_recognize_voice_with_relative_path(self):
        """Test recognize_voice resolves relative paths."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Transcription"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.abspath", return_value="/abs/path/to/audio.mp3"):
                with patch("os.path.exists", return_value=True):
                    result = recognize_voice(
                        audio_source="audio.mp3",
                        prompt="Transcribe this",
                    )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Transcribe this"
        assert result == "Transcription"

    def test_recognize_voice_empty_source_raises(self):
        """Test recognize_voice raises ValueError for empty audio_source."""
        with pytest.raises(ValueError, match="audio_source must be a non-empty string"):
            recognize_voice(audio_source="", prompt="test")

    def test_recognize_voice_none_source_raises(self):
        """Test recognize_voice raises ValueError for None audio_source."""
        with pytest.raises(ValueError, match="audio_source must be a non-empty string"):
            recognize_voice(audio_source=None, prompt="test")

    def test_recognize_voice_invalid_source_type_raises(self):
        """Test recognize_voice raises ValueError for non-string audio_source."""
        with pytest.raises(ValueError, match="audio_source must be a non-empty string"):
            recognize_voice(audio_source=123, prompt="test")

    def test_recognize_voice_strips_source(self):
        """Test recognize_voice strips whitespace from audio_source."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Transcription"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                recognize_voice(
                    audio_source="  https://example.com/audio.mp3  ",
                    prompt="Transcribe",
                )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Transcribe"

    def test_recognize_voice_no_response(self):
        """Test recognize_voice returns default when LLM returns None."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = None

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_voice(
                    audio_source="https://example.com/audio.mp3",
                    prompt="Transcribe",
                )

        assert result == "No response from LLM."

    def test_recognize_voice_system_prompt(self):
        """Test recognize_voice creates chat with audio system prompt."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Transcription"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat") as mock_get_chat:
            mock_get_chat.return_value = mock_chat
            with patch("os.path.exists", return_value=False):
                recognize_voice(
                    audio_source="https://example.com/audio.mp3",
                    prompt="Transcribe",
                )

        mock_get_chat.assert_called_once_with(
            message="Transcribe",
            system_prompt="You are a helpful assistant with strong audio understanding capabilities. Transcribe and analyze audio accurately and concisely.",
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )

    def test_recognize_voice_with_local_absolute_path(self):
        """Test recognize_voice with local absolute path."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Transcription"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=True):
                result = recognize_voice(
                    audio_source="/path/to/local/audio.mp3",
                    prompt="Transcribe",
                )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Transcribe"
        assert result == "Transcription"

    def test_recognize_voice_with_http_url(self):
        """Test recognize_voice with http URL."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Transcription"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_voice(
                    audio_source="http://example.com/audio.mp3",
                    prompt="Transcribe",
                )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Transcribe"
        assert result == "Transcription"

    def test_recognize_voice_with_model_name(self):
        """Test recognize_voice sets model_name on chat.llm_model."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Transcription"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_voice(
                    audio_source="https://example.com/audio.mp3",
                    prompt="Transcribe",
                    model_name="gpt-4o-audio",
                )

        assert mock_chat.llm_model.model_name == "gpt-4o-audio"
        assert result == "Transcription"


class TestRecognizeVideo:
    """Test recognize_video function."""

    def test_recognize_video_with_valid_inputs(self):
        """Test recognize_video with valid video_source and prompt."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "The video shows a person walking."

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_video(
                    video_source="https://example.com/video.mp4",
                    prompt="What is in this video?",
                )

        assert result == "The video shows a person walking."
        mock_chat.chat_with_content.assert_called_once()
        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "What is in this video?"

    def test_recognize_video_with_empty_prompt_uses_default(self):
        """Test recognize_video uses default prompt when prompt is empty."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_video(
                    video_source="https://example.com/video.mp4",
                    prompt="",
                )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Describe the content of this video."
        assert result == "Description"

    def test_recognize_video_with_relative_path(self):
        """Test recognize_video resolves relative paths."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.abspath", return_value="/abs/path/to/video.mp4"):
                with patch("os.path.exists", return_value=True):
                    result = recognize_video(
                        video_source="video.mp4",
                        prompt="Describe this",
                    )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Describe this"
        assert result == "Description"

    def test_recognize_video_empty_source_raises(self):
        """Test recognize_video raises ValueError for empty video_source."""
        with pytest.raises(ValueError, match="video_source must be a non-empty string"):
            recognize_video(video_source="", prompt="test")

    def test_recognize_video_none_source_raises(self):
        """Test recognize_video raises ValueError for None video_source."""
        with pytest.raises(ValueError, match="video_source must be a non-empty string"):
            recognize_video(video_source=None, prompt="test")

    def test_recognize_video_invalid_source_type_raises(self):
        """Test recognize_video raises ValueError for non-string video_source."""
        with pytest.raises(ValueError, match="video_source must be a non-empty string"):
            recognize_video(video_source=123, prompt="test")

    def test_recognize_video_strips_source(self):
        """Test recognize_video strips whitespace from video_source."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                recognize_video(
                    video_source="  https://example.com/video.mp4  ",
                    prompt="Describe",
                )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Describe"

    def test_recognize_video_no_response(self):
        """Test recognize_video returns default when LLM returns None."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = None

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_video(
                    video_source="https://example.com/video.mp4",
                    prompt="Describe",
                )

        assert result == "No response from LLM."

    def test_recognize_video_system_prompt(self):
        """Test recognize_video creates chat with video system prompt."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat") as mock_get_chat:
            mock_get_chat.return_value = mock_chat
            with patch("os.path.exists", return_value=False):
                recognize_video(
                    video_source="https://example.com/video.mp4",
                    prompt="Describe",
                )

        mock_get_chat.assert_called_once_with(
            message="Describe",
            system_prompt="You are a helpful assistant with strong video understanding capabilities. Describe videos accurately and concisely.",
            need_input_message=False,
            need_print_session=False,
            need_print_message=False,
        )

    def test_recognize_video_with_local_absolute_path(self):
        """Test recognize_video with local absolute path."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=True):
                result = recognize_video(
                    video_source="/path/to/local/video.mp4",
                    prompt="Describe",
                )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Describe"
        assert result == "Description"

    def test_recognize_video_with_http_url(self):
        """Test recognize_video with http URL."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_video(
                    video_source="http://example.com/video.mp4",
                    prompt="Describe",
                )

        call_args = mock_chat.chat_with_content.call_args
        assert call_args[1]["message"] == "Describe"
        assert result == "Description"

    def test_recognize_video_with_model_name(self):
        """Test recognize_video sets model_name on chat.llm_model."""
        mock_chat = MagicMock()
        mock_chat.chat_with_content.return_value = "Description"

        with patch("topsailai.tools.multimodal_readonly_tool.get_multimodal_llm_chat", return_value=mock_chat):
            with patch("os.path.exists", return_value=False):
                result = recognize_video(
                    video_source="https://example.com/video.mp4",
                    prompt="Describe",
                    model_name="gpt-4o-video",
                )

        assert mock_chat.llm_model.model_name == "gpt-4o-video"
        assert result == "Description"


class TestToolsDict:
    """Test TOOLS dict structure."""

    def test_tools_has_recognize_image(self):
        """Test TOOLS dict contains recognize_image."""
        assert "recognize_image" in TOOLS
        assert TOOLS["recognize_image"] is recognize_image

    def test_tools_has_recognize_voice(self):
        """Test TOOLS dict contains recognize_voice."""
        assert "recognize_voice" in TOOLS
        assert TOOLS["recognize_voice"] is recognize_voice

    def test_tools_has_recognize_video(self):
        """Test TOOLS dict contains recognize_video."""
        assert "recognize_video" in TOOLS
        assert TOOLS["recognize_video"] is recognize_video

    def test_tools_count(self):
        """Test TOOLS dict has exactly 3 entries."""
        assert len(TOOLS) == 3




class TestPrompt:
    """Test PROMPT string."""

    def test_prompt_contains_tool_name(self):
        """Test PROMPT mentions the tool name."""
        assert "multimodal_readonly_tool" in PROMPT

    def test_prompt_contains_recognize_image(self):
        """Test PROMPT mentions recognize_image."""
        assert "recognize_image" in PROMPT

    def test_prompt_contains_recognize_voice(self):
        """Test PROMPT mentions recognize_voice."""
        assert "recognize_voice" in PROMPT

    def test_prompt_contains_recognize_video(self):
        """Test PROMPT mentions recognize_video."""
        assert "recognize_video" in PROMPT

    def test_prompt_contains_audio_formats(self):
        """Test PROMPT mentions supported audio formats."""
        assert "audio formats" in PROMPT

    def test_prompt_contains_video_formats(self):
        """Test PROMPT mentions supported video formats."""
        assert "video formats" in PROMPT

    def test_prompt_is_non_empty(self):
        """Test PROMPT is not empty."""
        assert len(PROMPT.strip()) > 0

    def test_prompt_contains_model_selection_guidance(self):
        """Test PROMPT contains model selection guidance."""
        assert "Model Selection Guidance" in PROMPT
        assert "model_name" in PROMPT


class TestFlagToolEnabled:
    """Test FLAG_TOOL_ENABLED."""

    def test_flag_tool_enabled_is_false(self):
        """Test FLAG_TOOL_ENABLED is false."""
        assert FLAG_TOOL_ENABLED is False


class TestEdgeCases:
    """Test edge cases."""

    def test_tools_functions_are_callable(self):
        """Test that all functions in TOOLS are callable."""
        for name, func in TOOLS.items():
            assert callable(func), f"{name} is not callable"


class TestGetExtraPrompt:
    """Test _get_extra_prompt function."""

    def test_get_extra_prompt_returns_empty_when_not_set(self):
        """Test _get_extra_prompt returns empty string when env var not set."""
        with patch.object(
            multimodal_readonly_tool.env_tool.EnvReaderInstance,
            "read_file_or_content",
            return_value="",
        ):
            result = _get_extra_prompt()
        assert result == ""

    def test_get_extra_prompt_returns_text(self):
        """Test _get_extra_prompt returns text from env var."""
        with patch.object(
            multimodal_readonly_tool.env_tool.EnvReaderInstance,
            "read_file_or_content",
            return_value="Extra guidance text",
        ):
            result = _get_extra_prompt()
        assert result == "Extra guidance text"
