"""
Constants for multimodal content handling.

This module defines constants used throughout the multimodal module,
including content type identifiers, image detail levels, and MIME type mappings.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-06-14
Purpose: Provide centralized constants for multimodal message processing.
"""

#################################################################################
# Content Type Identifiers
#################################################################################

# Content type identifiers for multimodal messages.
# These values are used in the "type" field of content items when building
# OpenAI-compatible content arrays.
CONTENT_TYPE_TEXT = "text"
CONTENT_TYPE_IMAGE_URL = "image_url"
CONTENT_TYPE_VIDEO = "video"
CONTENT_TYPE_AUDIO = "audio"

# Collection of all supported content types for validation.
SUPPORTED_CONTENT_TYPES = {
    CONTENT_TYPE_TEXT,
    CONTENT_TYPE_IMAGE_URL,
    CONTENT_TYPE_VIDEO,
    CONTENT_TYPE_AUDIO,
}

#################################################################################
# Image Detail Levels
#################################################################################

# Image detail levels for vision-capable models.
# Controls the resolution at which the model processes the image.
# - auto: Let the model decide based on image size
# - low: Low resolution, faster processing
# - high: High resolution, more detail
IMAGE_DETAIL_AUTO = "auto"
IMAGE_DETAIL_LOW = "low"
IMAGE_DETAIL_HIGH = "high"

# Valid image detail levels for input validation.
VALID_IMAGE_DETAILS = {
    IMAGE_DETAIL_AUTO,
    IMAGE_DETAIL_LOW,
    IMAGE_DETAIL_HIGH,
}

#################################################################################
# MIME Type Mappings
#################################################################################

# Supported image MIME types mapped by file extension.
# Used when converting local image files to base64 data URIs.
IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}

# Supported video MIME types mapped by file extension.
# Used when converting local video files to base64 data URIs.
VIDEO_MIME_TYPES = {
    ".mp4": "video/mp4",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".flv": "video/x-flv",
    ".wmv": "video/x-ms-wmv",
}

# Supported audio MIME types mapped by file extension.
# Used when converting local audio files to base64 data URIs.
AUDIO_MIME_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".opus": "audio/opus",
    ".wma": "audio/x-ms-wma",
}

# Combined mapping of all supported MIME types for quick lookup.
ALL_MIME_TYPES = {}
ALL_MIME_TYPES.update(IMAGE_MIME_TYPES)
ALL_MIME_TYPES.update(VIDEO_MIME_TYPES)
ALL_MIME_TYPES.update(AUDIO_MIME_TYPES)

#################################################################################
# Default Values
#################################################################################

# Default image detail level when not explicitly specified.
DEFAULT_IMAGE_DETAIL = IMAGE_DETAIL_AUTO

# Default prompt for image recognition when no prompt is provided.
DEFAULT_IMAGE_PROMPT = "Describe this image in detail."

# Default prompt for video analysis when no prompt is provided.
DEFAULT_VIDEO_PROMPT = "Describe the content of this video."

# Default prompt for audio analysis when no prompt is provided.
DEFAULT_AUDIO_PROMPT = "Transcribe and describe this audio content."

# Default system prompt for multimodal LLM interactions.
DEFAULT_MULTIMODAL_SYSTEM_PROMPT = (
    "You are a helpful assistant with strong multimodal understanding capabilities. "
    "Analyze and describe visual and audio content accurately and concisely."
)

#################################################################################
# Validation
#################################################################################

# Maximum file size in bytes for base64 encoding (50 MB).
# Files larger than this should use URL-based references instead.
MAX_BASE64_FILE_SIZE = 50 * 1024 * 1024

# Supported URL schemes for remote media sources.
SUPPORTED_URL_SCHEMES = {"http", "https"}
