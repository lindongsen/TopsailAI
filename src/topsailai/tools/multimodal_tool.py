"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-06-14
  Purpose: Multimodal recognition tool for image, voice, and video understanding via LLM.
"""

import os

from topsailai.ai_base.multimodal.llm_shell import get_multimodal_llm_chat
from topsailai.ai_base.multimodal import (
    build_image_content,
    build_audio_content,
    build_video_content,
)


def recognize_image(image_source: str, prompt: str = "") -> str:
    """
    Recognize and describe the content of an image using a multimodal LLM.

    This tool sends an image to a vision-capable LLM and returns its description
    or analysis of the image content.

    Args:
        image_source (str): File path or URL to the image.
            - Local file: absolute path like "/path/to/image.png"
            - URL: "https://example.com/image.jpg"
        prompt (str, optional): Specific question or instruction about the image.
            Defaults to "Describe this image in detail." if not provided.

    Returns:
        str: The LLM's description or analysis of the image.

    Raises:
        FileNotFoundError: If the image file does not exist.
        ValueError: If image_source is empty or invalid.

    Example:
        >>> recognize_image("/path/to/screenshot.png")
        'The image shows a web browser with...'

        >>> recognize_image("/path/to/chart.png", "What are the key trends in this chart?")
        'The chart shows an upward trend in...'
    """
    if not image_source or not isinstance(image_source, str):
        raise ValueError("image_source must be a non-empty string")

    image_source = image_source.strip()

    # Handle relative paths
    if image_source[0] not in ["/", "h"]:
        abs_path = os.path.abspath(image_source)
        if os.path.exists(abs_path):
            image_source = abs_path

    if not prompt:
        prompt = "Describe this image in detail."

    chat = get_multimodal_llm_chat(
        message=prompt,
        system_prompt="You are a helpful assistant with strong image understanding capabilities. Describe images accurately and concisely.",
        need_input_message=False,
        need_print_session=False,
        need_print_message=False,
    )

    response = chat.chat_with_image(
        message=prompt,
        image_source=image_source,
        detail="auto",
    )

    return response or "No response from LLM."


def recognize_voice(audio_source: str, prompt: str = "") -> str:
    """
    Recognize and transcribe audio content using a multimodal LLM.

    This tool sends an audio file to an audio-capable LLM and returns its
    transcription or analysis.

    Args:
        audio_source (str): File path or URL to the audio.
            - Local file: absolute path like "/path/to/audio.mp3"
            - URL: "https://example.com/audio.mp3"
        prompt (str, optional): Specific question or instruction about the audio.
            Defaults to "Transcribe and describe this audio content." if not provided.

    Returns:
        str: The LLM's transcription or analysis of the audio.

    Raises:
        FileNotFoundError: If the audio file does not exist.
        ValueError: If audio_source is empty or invalid.

    Example:
        >>> recognize_voice("/path/to/recording.mp3")
        'The audio contains a conversation about...'
    """
    if not audio_source or not isinstance(audio_source, str):
        raise ValueError("audio_source must be a non-empty string")

    audio_source = audio_source.strip()

    # Handle relative paths
    if audio_source[0] not in ["/", "h"]:
        abs_path = os.path.abspath(audio_source)
        if os.path.exists(abs_path):
            audio_source = abs_path

    if not prompt:
        prompt = "Transcribe and describe this audio content."

    chat = get_multimodal_llm_chat(
        message=prompt,
        system_prompt="You are a helpful assistant with strong audio understanding capabilities. Transcribe and analyze audio accurately and concisely.",
        need_input_message=False,
        need_print_session=False,
        need_print_message=False,
    )

    response = chat.chat_with_content(
        message=prompt,
        content=build_audio_content(audio_source),
    )

    return response or "No response from LLM."


def recognize_video(video_source: str, prompt: str = "") -> str:
    """
    Recognize and describe the content of a video using a multimodal LLM.

    This tool sends a video file to a video-capable LLM and returns its
    description or analysis.

    Args:
        video_source (str): File path or URL to the video.
            - Local file: absolute path like "/path/to/video.mp4"
            - URL: "https://example.com/video.mp4"
        prompt (str, optional): Specific question or instruction about the video.
            Defaults to "Describe the content of this video." if not provided.

    Returns:
        str: The LLM's description or analysis of the video.

    Raises:
        FileNotFoundError: If the video file does not exist.
        ValueError: If video_source is empty or invalid.

    Example:
        >>> recognize_video("/path/to/clip.mp4")
        'The video shows a person walking through...'
    """
    if not video_source or not isinstance(video_source, str):
        raise ValueError("video_source must be a non-empty string")

    video_source = video_source.strip()

    # Handle relative paths
    if video_source[0] not in ["/", "h"]:
        abs_path = os.path.abspath(video_source)
        if os.path.exists(abs_path):
            video_source = abs_path

    if not prompt:
        prompt = "Describe the content of this video."

    chat = get_multimodal_llm_chat(
        message=prompt,
        system_prompt="You are a helpful assistant with strong video understanding capabilities. Describe videos accurately and concisely.",
        need_input_message=False,
        need_print_session=False,
        need_print_message=False,
    )

    response = chat.chat_with_content(
        message=prompt,
        content=build_video_content(video_source),
    )

    return response or "No response from LLM."


# Tool registration
TOOLS = dict(
    recognize_image=recognize_image,
    recognize_voice=recognize_voice,
    recognize_video=recognize_video,
)

# OpenAI function calling schema
TOOLS_INFO = dict(
    recognize_image={
        "type": "function",
        "function": {
            "name": "recognize_image",
            "description": recognize_image.__doc__,
            "parameters": {
                "type": "object",
                "properties": {
                    "image_source": {
                        "type": "string",
                        "description": "File path or URL to the image. Local file: absolute path like '/path/to/image.png'. URL: 'https://example.com/image.jpg'",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Specific question or instruction about the image. Defaults to 'Describe this image in detail.'",
                    },
                },
                "required": ["image_source"],
            },
        },
    },
    recognize_voice={
        "type": "function",
        "function": {
            "name": "recognize_voice",
            "description": recognize_voice.__doc__,
            "parameters": {
                "type": "object",
                "properties": {
                    "audio_source": {
                        "type": "string",
                        "description": "File path or URL to the audio. Local file: absolute path like '/path/to/audio.mp3'. URL: 'https://example.com/audio.mp3'",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Specific question or instruction about the audio. Defaults to 'Transcribe and describe this audio content.'",
                    },
                },
                "required": ["audio_source"],
            },
        },
    },
    recognize_video={
        "type": "function",
        "function": {
            "name": "recognize_video",
            "description": recognize_video.__doc__,
            "parameters": {
                "type": "object",
                "properties": {
                    "video_source": {
                        "type": "string",
                        "description": "File path or URL to the video. Local file: absolute path like '/path/to/video.mp4'. URL: 'https://example.com/video.mp4'",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Specific question or instruction about the video. Defaults to 'Describe the content of this video.'",
                    },
                },
                "required": ["video_source"],
            },
        },
    },
)

# Tool prompt for agent context
PROMPT = """
# About multimodal_tool
This tool provides multimodal recognition capabilities via multimodal LLM.
Use recognize_image to get a description of an image.
Use recognize_voice to transcribe and analyze audio content.
Use recognize_video to describe the content of a video.

Supported image formats: PNG, JPG, JPEG, GIF, WEBP, BMP, TIFF.
Supported audio formats: MP3, WAV, OGG, M4A.
Supported video formats: MP4, AVI, MOV, WEBM.
Media source can be a local file path or a URL.
"""

# Enable this tool by default
FLAG_TOOL_ENABLED = True
