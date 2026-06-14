"""
Multimodal Message Classes.

This module defines structured classes for managing multimodal content in LLM
interactions. All message management MUST use these classes instead of raw
lists, dicts, or JSON strings.

The class hierarchy follows OpenAI's multimodal API format:
- Content items are represented as typed objects (TextContent, ImageContent, etc.)
- Messages are containers of content items with a role
- to_dict() methods produce OpenAI-compatible serialization

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-06-14
Purpose: Provide structured message classes for multimodal LLM interactions.
"""

import base64
import os
from abc import ABC, abstractmethod
from typing import List, Optional

from topsailai.ai_base.multimodal.constants import (
    CONTENT_TYPE_TEXT,
    CONTENT_TYPE_IMAGE_URL,
    CONTENT_TYPE_VIDEO,
    CONTENT_TYPE_AUDIO,
    IMAGE_MIME_TYPES,
    VIDEO_MIME_TYPES,
    AUDIO_MIME_TYPES,
    VALID_IMAGE_DETAILS,
    DEFAULT_IMAGE_DETAIL,
    MAX_BASE64_FILE_SIZE,
    SUPPORTED_URL_SCHEMES,
)


#################################################################################
# Helper Functions
#################################################################################

def _is_url(source: str) -> bool:
    """
    Check if a source string is a URL.

    Args:
        source (str): The source string to check.

    Returns:
        bool: True if the source starts with a supported URL scheme.
    """
    if not source:
        return False
    source_lower = source.lower()
    return any(source_lower.startswith(scheme + "://") for scheme in SUPPORTED_URL_SCHEMES)


def _read_file_as_base64(file_path: str) -> str:
    """
    Read a file and return its contents as a base64-encoded string.

    Args:
        file_path (str): Absolute or relative path to the file.

    Returns:
        str: Base64-encoded file contents.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file exceeds MAX_BASE64_FILE_SIZE.
        IOError: If the file cannot be read.
    """
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"File not found: {abs_path}")

    file_size = os.path.getsize(abs_path)
    if file_size > MAX_BASE64_FILE_SIZE:
        raise ValueError(
            f"File size ({file_size} bytes) exceeds maximum allowed "
            f"({MAX_BASE64_FILE_SIZE} bytes). Consider using a URL instead: {abs_path}"
        )

    with open(abs_path, "rb") as f:
        file_bytes = f.read()

    return base64.b64encode(file_bytes).decode("utf-8")


def _get_mime_type(file_path: str, mime_map: dict) -> str:
    """
    Determine the MIME type of a file based on its extension.

    Args:
        file_path (str): Path to the file.
        mime_map (dict): Mapping of file extensions to MIME types.

    Returns:
        str: The MIME type if recognized, otherwise "application/octet-stream".
    """
    ext = os.path.splitext(file_path.lower())[1]
    return mime_map.get(ext, "application/octet-stream")


#################################################################################
# Content Item Base Class
#################################################################################

class ContentItem(ABC):
    """
    Abstract base class for all multimodal content items.

    Subclasses must implement to_dict() to produce OpenAI-compatible
    content item dictionaries.
    """

    @property
    @abstractmethod
    def type(self) -> str:
        """
        Return the content type identifier.

        Returns:
            str: One of the CONTENT_TYPE_* constants.
        """
        pass

    @abstractmethod
    def to_dict(self) -> dict:
        """
        Serialize this content item to an OpenAI-compatible dictionary.

        Returns:
            dict: The serialized content item.
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.to_dict()})"


#################################################################################
# Text Content
#################################################################################

class TextContent(ContentItem):
    """
    Represents a text content item in a multimodal message.

    Serializes to: {"type": "text", "text": "..."}
    """

    def __init__(self, text: str):
        """
        Initialize a TextContent item.

        Args:
            text (str): The text content.

        Raises:
            ValueError: If text is not a string.
        """
        if not isinstance(text, str):
            raise ValueError(f"text must be a string, got {type(text).__name__}")
        self._text = text

    @property
    def type(self) -> str:
        return CONTENT_TYPE_TEXT

    @property
    def text(self) -> str:
        """Return the text content."""
        return self._text

    def to_dict(self) -> dict:
        return {
            "type": CONTENT_TYPE_TEXT,
            "text": self._text,
        }


#################################################################################
# Image Content
#################################################################################

class ImageContent(ContentItem):
    """
    Represents an image content item in a multimodal message.

    Supports both remote URLs and local file paths. Local files are
    automatically converted to base64 data URIs when serialized.

    Serializes to: {"type": "image_url", "image_url": {"url": "...", "detail": "auto"}}
    """

    def __init__(self, source: str, detail: str = DEFAULT_IMAGE_DETAIL):
        """
        Initialize an ImageContent item.

        Args:
            source (str): URL or local file path to the image.
            detail (str, optional): Image detail level ("auto", "low", "high").
                Defaults to "auto".

        Raises:
            ValueError: If source is empty or detail is invalid.
        """
        if not source or not isinstance(source, str):
            raise ValueError("source must be a non-empty string")
        if detail not in VALID_IMAGE_DETAILS:
            raise ValueError(
                f"Invalid detail level '{detail}'. Must be one of: {VALID_IMAGE_DETAILS}"
            )
        self._source = source.strip()
        self._detail = detail

    @property
    def type(self) -> str:
        return CONTENT_TYPE_IMAGE_URL

    @property
    def source(self) -> str:
        """Return the original image source (URL or file path)."""
        return self._source

    @property
    def detail(self) -> str:
        """Return the image detail level."""
        return self._detail

    def _resolve_url(self) -> str:
        """
        Resolve the source to a URL suitable for the LLM API.

        If the source is a local file, convert it to a base64 data URI.
        If it's already a URL, return it as-is.

        Returns:
            str: The resolved URL (data URI or original URL).

        Raises:
            FileNotFoundError: If the local file does not exist.
            ValueError: If the file is too large for base64 encoding.
        """
        if _is_url(self._source):
            return self._source

        # Local file: convert to base64 data URI
        mime_type = _get_mime_type(self._source, IMAGE_MIME_TYPES)
        base64_data = _read_file_as_base64(self._source)
        return f"data:{mime_type};base64,{base64_data}"

    def to_dict(self) -> dict:
        return {
            "type": CONTENT_TYPE_IMAGE_URL,
            "image_url": {
                "url": self._resolve_url(),
                "detail": self._detail,
            },
        }


#################################################################################
# Video Content
#################################################################################

class VideoContent(ContentItem):
    """
    Represents a video content item in a multimodal message.

    Supports both remote URLs and local file paths. Local files are
    automatically converted to base64 data URIs when serialized.

    Note: Video support depends on the specific LLM model's capabilities.
    Some models may not support video input directly.

    Serializes to: {"type": "video", "video": {"url": "..."}}
    """

    def __init__(self, source: str):
        """
        Initialize a VideoContent item.

        Args:
            source (str): URL or local file path to the video.

        Raises:
            ValueError: If source is empty.
        """
        if not source or not isinstance(source, str):
            raise ValueError("source must be a non-empty string")
        self._source = source.strip()

    @property
    def type(self) -> str:
        return CONTENT_TYPE_VIDEO

    @property
    def source(self) -> str:
        """Return the original video source (URL or file path)."""
        return self._source

    def _resolve_url(self) -> str:
        """
        Resolve the source to a URL suitable for the LLM API.

        If the source is a local file, convert it to a base64 data URI.
        If it's already a URL, return it as-is.

        Returns:
            str: The resolved URL (data URI or original URL).

        Raises:
            FileNotFoundError: If the local file does not exist.
            ValueError: If the file is too large for base64 encoding.
        """
        if _is_url(self._source):
            return self._source

        mime_type = _get_mime_type(self._source, VIDEO_MIME_TYPES)
        base64_data = _read_file_as_base64(self._source)
        return f"data:{mime_type};base64,{base64_data}"

    def to_dict(self) -> dict:
        return {
            "type": CONTENT_TYPE_VIDEO,
            "video": {
                "url": self._resolve_url(),
            },
        }


#################################################################################
# Audio Content
#################################################################################

class AudioContent(ContentItem):
    """
    Represents an audio content item in a multimodal message.

    Supports both remote URLs and local file paths. Local files are
    automatically converted to base64 data URIs when serialized.

    Note: Audio support depends on the specific LLM model's capabilities.
    Some models may not support audio input directly.

    Serializes to: {"type": "audio", "audio": {"url": "..."}}
    """

    def __init__(self, source: str):
        """
        Initialize an AudioContent item.

        Args:
            source (str): URL or local file path to the audio.

        Raises:
            ValueError: If source is empty.
        """
        if not source or not isinstance(source, str):
            raise ValueError("source must be a non-empty string")
        self._source = source.strip()

    @property
    def type(self) -> str:
        return CONTENT_TYPE_AUDIO

    @property
    def source(self) -> str:
        """Return the original audio source (URL or file path)."""
        return self._source

    def _resolve_url(self) -> str:
        """
        Resolve the source to a URL suitable for the LLM API.

        If the source is a local file, convert it to a base64 data URI.
        If it's already a URL, return it as-is.

        Returns:
            str: The resolved URL (data URI or original URL).

        Raises:
            FileNotFoundError: If the local file does not exist.
            ValueError: If the file is too large for base64 encoding.
        """
        if _is_url(self._source):
            return self._source

        mime_type = _get_mime_type(self._source, AUDIO_MIME_TYPES)
        base64_data = _read_file_as_base64(self._source)
        return f"data:{mime_type};base64,{base64_data}"

    def to_dict(self) -> dict:
        return {
            "type": CONTENT_TYPE_AUDIO,
            "audio": {
                "url": self._resolve_url(),
            },
        }


#################################################################################
# Multimodal Message
#################################################################################

class MultimodalMessage:
    """
    Represents a single message in a multimodal conversation.

    A message has a role (e.g., "user", "assistant", "system") and a list
    of content items. This class enforces structured content management
    and provides OpenAI-compatible serialization.

    For backward compatibility with text-only models, to_dict() returns
    the simple string format when the message contains only a single
    TextContent item. Otherwise, it returns the content array format.
    """

    def __init__(self, role: str, content_items: List[ContentItem], tool_call_id: Optional[str] = None):
        """
        Initialize a MultimodalMessage.

        Args:
            role (str): The message role ("user", "assistant", "system", "tool").
            content_items (List[ContentItem]): List of content items.
            tool_call_id (str, optional): The tool call ID for role="tool" messages.
                Required by the OpenAI API for tool result messages. Defaults to None.

        Raises:
            ValueError: If role is empty or content_items is empty.
            TypeError: If content_items contains non-ContentItem objects.
        """
        if not role or not isinstance(role, str):
            raise ValueError("role must be a non-empty string")
        if not content_items:
            raise ValueError("content_items must not be empty")

        for idx, item in enumerate(content_items):
            if not isinstance(item, ContentItem):
                raise TypeError(
                    f"content_items[{idx}] must be a ContentItem, "
                    f"got {type(item).__name__}"
                )

        self._role = role
        self._content_items = list(content_items)
        self._tool_call_id = tool_call_id

    @property
    def role(self) -> str:
        """Return the message role."""
        return self._role

    @property
    def content_items(self) -> List[ContentItem]:
        """Return the list of content items (read-only copy)."""
        return list(self._content_items)

    @property
    def tool_call_id(self) -> Optional[str]:
        """Return the tool call ID, or None if not set."""
        return self._tool_call_id

    def add_content_item(self, item: ContentItem) -> "MultimodalMessage":
        """
        Append a content item to this message.

        Args:
            item (ContentItem): The content item to append.

        Returns:
            MultimodalMessage: Self for method chaining.

        Raises:
            TypeError: If item is not a ContentItem.
        """
        if not isinstance(item, ContentItem):
            raise TypeError(f"item must be a ContentItem, got {type(item).__name__}")
        self._content_items.append(item)
        return self

    def get_text_content(self) -> str:
        """
        Extract and concatenate all text content from this message.

        Returns:
            str: Concatenated text from all TextContent items.
        """
        texts = []
        for item in self._content_items:
            if isinstance(item, TextContent):
                texts.append(item.text)
        return "\n".join(texts)

    def has_media_content(self) -> bool:
        """
        Check if this message contains non-text media content.

        Returns:
            bool: True if any content item is not TextContent.
        """
        return any(not isinstance(item, TextContent) for item in self._content_items)

    def to_dict(self) -> dict:
        """
        Serialize this message to an OpenAI-compatible dictionary.

        Returns:
            dict: The serialized message. Format depends on content:
                - Single TextContent: {"role": "...", "content": "..."}
                - Multiple items or media: {"role": "...", "content": [{...}, ...]}
                - Tool messages also include: {"tool_call_id": "..."}
        """
        # Build base result with role and content
        if len(self._content_items) == 1 and isinstance(self._content_items[0], TextContent):
            result = {
                "role": self._role,
                "content": self._content_items[0].text,
            }
        else:
            result = {
                "role": self._role,
                "content": [item.to_dict() for item in self._content_items],
            }

        # Include tool_call_id for tool messages (required by OpenAI API)
        if self._tool_call_id:
            result["tool_call_id"] = self._tool_call_id

        return result

    def __repr__(self) -> str:
        return f"MultimodalMessage(role={self._role!r}, items={len(self._content_items)}, tool_call_id={self._tool_call_id!r})"
