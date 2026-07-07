"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-06-14
  Purpose: Multimodal module - provides message classes, prompt management,
           and LLM interaction for vision, video, and audio content.
"""

from .message import (
    ContentItem,
    TextContent,
    ImageContent,
    VideoContent,
    AudioContent,
    MultimodalMessage,
)
from .prompt_base import MultimodalPromptBase
from .constants import (
    CONTENT_TYPE_TEXT,
    CONTENT_TYPE_IMAGE_URL,
    CONTENT_TYPE_VIDEO,
    CONTENT_TYPE_AUDIO,
    IMAGE_DETAIL_AUTO,
    IMAGE_DETAIL_LOW,
    IMAGE_DETAIL_HIGH,
)


def build_image_content(image_source: str, detail: str = IMAGE_DETAIL_AUTO) -> ImageContent:
    """
    Build an ImageContent item from an image source.

    Helper function for creating ImageContent objects from file paths or URLs.
    This is the primary entry point for converting image sources into
    ContentItem objects that can be added to MultimodalMessage instances.

    Args:
        image_source (str): File path or URL to the image.
            - Local file: absolute path like "/path/to/image.png"
            - URL: "https://example.com/image.jpg"
        detail (str, optional): Image detail level for the LLM.
            One of "auto", "low", "high". Defaults to "auto".

    Returns:
        ImageContent: A ContentItem representing the image.

    Raises:
        ValueError: If image_source is empty or invalid.
        FileNotFoundError: If the local image file does not exist.

    Example:
        >>> from topsailai.ai_base.multimodal import build_image_content
        >>> img = build_image_content("/path/to/screenshot.png", detail="high")
        >>> print(img.to_dict())
        {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,...', 'detail': 'high'}}
    """
    if not image_source or not isinstance(image_source, str):
        raise ValueError("image_source must be a non-empty string")

    image_source = image_source.strip()

    # Handle relative paths
    import os
    if image_source[0] not in ["/", "h"]:
        abs_path = os.path.abspath(image_source)
        if os.path.exists(abs_path):
            image_source = abs_path

    return ImageContent(image_source, detail=detail)


def build_video_content(video_source: str) -> VideoContent:
    """
    Build a VideoContent item from a video source.

    Args:
        video_source (str): File path or URL to the video.

    Returns:
        VideoContent: A ContentItem representing the video.

    Raises:
        ValueError: If video_source is empty or invalid.
        FileNotFoundError: If the local video file does not exist.
    """
    if not video_source or not isinstance(video_source, str):
        raise ValueError("video_source must be a non-empty string")

    video_source = video_source.strip()

    import os
    if video_source[0] not in ["/", "h"]:
        abs_path = os.path.abspath(video_source)
        if os.path.exists(abs_path):
            video_source = abs_path

    return VideoContent(video_source)


def build_audio_content(audio_source: str) -> AudioContent:
    """
    Build an AudioContent item from an audio source.

    Args:
        audio_source (str): File path or URL to the audio.

    Returns:
        AudioContent: A ContentItem representing the audio.

    Raises:
        ValueError: If audio_source is empty or invalid.
        FileNotFoundError: If the local audio file does not exist.
    """
    if not audio_source or not isinstance(audio_source, str):
        raise ValueError("audio_source must be a non-empty string")

    audio_source = audio_source.strip()

    import os
    if audio_source[0] not in ["/", "h"]:
        abs_path = os.path.abspath(audio_source)
        if os.path.exists(abs_path):
            audio_source = abs_path

    return AudioContent(audio_source)


def build_text_content(text: str) -> TextContent:
    """
    Build a TextContent item from a text string.

    Args:
        text (str): The text content.

    Returns:
        TextContent: A ContentItem representing the text.
    """
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    return TextContent(text)


__all__ = [
    # Content items
    "ContentItem",
    "TextContent",
    "ImageContent",
    "VideoContent",
    "AudioContent",
    # Message
    "MultimodalMessage",
    # Prompt
    "MultimodalPromptBase",
    # LLM, DONOT IMPORT DUE TO TOO LONG TIME TO IMPORT
    # Helpers
    "build_image_content",
    "build_video_content",
    "build_audio_content",
    "build_text_content",
    # Constants
    "CONTENT_TYPE_TEXT",
    "CONTENT_TYPE_IMAGE_URL",
    "CONTENT_TYPE_VIDEO",
    "CONTENT_TYPE_AUDIO",
    "IMAGE_DETAIL_AUTO",
    "IMAGE_DETAIL_LOW",
    "IMAGE_DETAIL_HIGH",
]
