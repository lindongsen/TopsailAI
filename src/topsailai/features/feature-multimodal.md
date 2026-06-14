---
maintainer: AI
---

# Feature: Multimodal Support for TopsailAI

## Overview

This feature adds multimodal capabilities to TopsailAI, enabling the agent to process and understand images, video, and audio content through vision-capable LLMs. The implementation is designed as an independent module with minimal changes to existing code.

## What Was Implemented

### Module Structure

```
ai_base/multimodal/
├── __init__.py          # Package init with build_image_content, build_audio_content, build_video_content helpers
├── message.py           # Multimodal message content classes
├── prompt_base.py       # Multimodal prompt manager
├── llm_base.py          # Multimodal LLM model wrapper
└── llm_shell.py         # Multimodal chat factory and interface

tools/
└── multimodal_tool.py   # Agent tools: recognize_image, recognize_voice, recognize_video

tests/unit/
├── test_topsailai_ai_base_multimodal_message.py      # 89 tests
├── test_topsailai_ai_base_multimodal_prompt_base.py  # 44 tests
├── test_topsailai_ai_base_multimodal_llm_base.py     # 24 tests
├── test_topsailai_ai_base_multimodal_llm_shell.py    # 26 tests
└── test_topsailai_tools_multimodal_tool.py           # 50 tests
```

### Key Classes

#### Content Classes (`message.py`)

| Class | Purpose | OpenAI Format |
|-------|---------|---------------|
| `TextContent` | Text content in a message | `{"type": "text", "text": "..."}` |
| `ImageContent` | Image content (URL or base64) | `{"type": "image_url", "image_url": {"url": "...", "detail": "auto"}}` |
| `VideoContent` | Video content (URL or base64) | `{"type": "video_url", "video_url": {"url": "..."}}` |
| `AudioContent` | Audio content (URL or base64) | `{"type": "audio_url", "audio_url": {"url": "..."}}` |

#### Message Class (`message.py`)

- `MultimodalMessage`: Container for multimodal conversation messages
  - `role`: One of `ROLE_USER`, `ROLE_ASSISTANT`, `ROLE_SYSTEM`, `ROLE_TOOL`
  - `content`: Either a `str` (simple text) or `list[ContentItem]` (content array)
  - `tool_call_id`: Optional, for tool response messages
  - `to_dict()`: Serializes to OpenAI-compatible format
    - Simple format: `{"role": "user", "content": "text"}`
    - Array format: `{"role": "user", "content": [{"type": "text", ...}, {"type": "image_url", ...}]}`

#### Prompt Manager (`prompt_base.py`)

- `MultimodalPromptBase`: Manages conversation history using `MultimodalMessage` objects
  - `add_user_message(content)`: Add text-only user message
  - `add_media_message(text, media_items)`: Add user message with text + media
  - `add_assistant_message(content)`: Add assistant response
  - `add_system_message(content)`: Add system message
  - `add_tool_message(content, tool_call_id)`: Add tool result
  - `to_dict_list()`: Export all messages as OpenAI-compatible dict list
  - `clear_messages()`, `reset_messages()`, `get_last_message()`, `get_messages_by_role()`

#### LLM Model (`llm_base.py`)

- `MultimodalLLMModel(LLMModelBase)`: Extends base LLM model for multimodal
  - `build_parameters_for_chat(messages, ...)`: Builds API params; preserves content arrays
  - `chat_with_content(messages, ...)`: Chat with `MultimodalMessage` list or dict list
  - `chat_with_prompt(prompt_base, ...)`: Chat using `MultimodalPromptBase`

#### Chat Interface (`llm_shell.py`)

- `MultimodalLLMChat`: High-level chat interface
  - `chat(message)`: Send text message, get response
  - `chat_with_image(message, image_source, detail="auto")`: Send image + text
  - `chat_with_content(message, content)`: Send text + single content item (image/video/audio)
  - `chat_with_media(message, media_items)`: Send multiple media items + text
- `get_multimodal_llm_chat(...)`: Factory function (mirrors `get_llm_chat`)

## How to Use the Multimodal Tools

### recognize_image

Recognize and describe the content of an image.

```python
from topsailai.tools.multimodal_tool import recognize_image

# With local file
result = recognize_image("/path/to/image.png")
print(result)
# Output: "The image shows a web browser with..."

# With URL
result = recognize_image("https://example.com/chart.jpg", prompt="What are the key trends?")
print(result)
```

### recognize_voice

Transcribe and describe audio content.

```python
from topsailai.tools.multimodal_tool import recognize_voice

# With local file
result = recognize_voice("/path/to/recording.mp3")
print(result)
# Output: "The audio contains a conversation about..."

# With URL and custom prompt
result = recognize_voice(
    "https://example.com/audio.wav",
    prompt="What language is spoken in this audio?"
)
print(result)
```

### recognize_video

Describe the content of a video.

```python
from topsailai.tools.multimodal_tool import recognize_video

# With local file
result = recognize_video("/path/to/video.mp4")
print(result)
# Output: "The video shows a person walking through..."

# With URL and custom prompt
result = recognize_video(
    "https://example.com/clip.mp4",
    prompt="What is the main action in this video?"
)
print(result)
```

### Tool Registration

The tools are automatically registered when loaded:

```python
TOOLS = dict(
    recognize_image=recognize_image,
    recognize_voice=recognize_voice,
    recognize_video=recognize_video,
)

TOOLS_INFO = dict(...)  # OpenAI function calling schema

FLAG_TOOL_ENABLED = True
```

## How to Use the Multimodal Module Programmatically

### Building Messages with Content Arrays

```python
from topsailai.ai_base.multimodal.message import (
    MultimodalMessage, TextContent, ImageContent, ROLE_USER
)

# Single text message
msg = MultimodalMessage(
    role=ROLE_USER,
    content="Hello, describe this image"
)

# Multimodal message with text + image
msg = MultimodalMessage(
    role=ROLE_USER,
    content=[
        TextContent("What do you see in this image?"),
        ImageContent("https://example.com/image.jpg"),
    ]
)

# Convert to OpenAI format
dict_msg = msg.to_dict()
# {
#   "role": "user",
#   "content": [
#     {"type": "text", "text": "What do you see in this image?"},
#     {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg", "detail": "auto"}}
#   ]
# }
```

### Using MultimodalPromptBase

```python
from topsailai.ai_base.multimodal.prompt_base import MultimodalPromptBase
from topsailai.ai_base.multimodal.message import ImageContent

prompt = MultimodalPromptBase("You are a helpful vision assistant.")

# Add text-only message
prompt.add_user_message("Hello!")

# Add message with image
prompt.add_media_message(
    text="Describe this image",
    media_items=[ImageContent("/path/to/image.png")]
)

# Get messages as OpenAI-compatible dicts
messages = prompt.to_dict_list()
```

### Calling the Multimodal LLM

```python
from topsailai.ai_base.multimodal.llm_base import MultimodalLLMModel
from topsailai.ai_base.multimodal.prompt_base import MultimodalPromptBase

# Create model
model = MultimodalLLMModel()

# Create prompt
prompt = MultimodalPromptBase("You are a vision assistant.")
prompt.add_media_message(
    text="What is in this image?",
    media_items=[ImageContent("/path/to/image.png")]
)

# Chat
response = model.chat_with_prompt(prompt, for_raw=True, for_stream=False)
print(response)
```

### Using the Chat Interface

```python
from topsailai.ai_base.multimodal.llm_shell import get_multimodal_llm_chat

# Create chat instance
chat = get_multimodal_llm_chat(
    message="Describe this image",
    system_prompt="You are a helpful vision assistant."
)

# Chat with image
response = chat.chat_with_image(
    message="What do you see?",
    image_source="/path/to/image.png"
)
print(response)

# Chat with audio
from topsailai.ai_base.multimodal import build_audio_content
response = chat.chat_with_content(
    message="Transcribe this audio",
    content=build_audio_content("/path/to/audio.mp3")
)
print(response)

# Chat with video
from topsailai.ai_base.multimodal import build_video_content
response = chat.chat_with_content(
    message="Describe this video",
    content=build_video_content("/path/to/video.mp4")
)
print(response)

# Chat with multiple media
from topsailai.ai_base.multimodal.message import ImageContent, VideoContent
response = chat.chat_with_media(
    message="Compare these",
    media_items=[
        ImageContent("/path/to/image1.png"),
        VideoContent("/path/to/video.mp4"),
    ]
)
```

## Supported Formats

### Images
- **Formats**: PNG, JPG, JPEG, GIF, WEBP, BMP, TIFF
- **Sources**: Local file path (absolute or relative), HTTP/HTTPS URL, base64 data URL
- **Detail levels**: `auto` (default), `low`, `high`

### Video
- **Formats**: MP4, AVI, MOV, WEBM
- **Sources**: Local file path, HTTP/HTTPS URL, base64 data URL

### Audio
- **Formats**: MP3, WAV, OGG, M4A
- **Sources**: Local file path, HTTP/HTTPS URL, base64 data URL

## Design Decisions

### 1. Independent Module

The multimodal support is implemented as a self-contained module under `ai_base/multimodal/`. This ensures:
- **Zero changes** to existing `LLMModel`, `PromptBase`, `LLMChat`, and agent core
- Existing text-based workflows remain unaffected
- The multimodal module can evolve independently

### 2. Class-Based Messages

All message management uses defined Python classes (`MultimodalMessage`, `TextContent`, `ImageContent`, etc.) rather than raw `list`, `dict`, or JSON strings:
- Type safety and validation at construction time
- Clear separation between internal representation and API serialization
- `to_dict()` method handles conversion to OpenAI-compatible format only at the API boundary

### 3. Content Array Preservation

`MultimodalLLMModel.build_parameters_for_chat()` preserves content arrays (lists of content items) while still applying TopsailAI formatting to simple string content:
- String content messages are processed through `format_messages()` (existing behavior)
- List content messages (multimodal arrays) are passed through unchanged
- This allows seamless mixing of text-only and multimodal messages in the same conversation

### 4. OpenAI-Compatible Format

The message serialization follows the OpenAI vision API format:
```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "..."},
    {"type": "image_url", "image_url": {"url": "...", "detail": "auto"}}
  ]
}
```
This ensures compatibility with OpenAI GPT-4V, GPT-4o, and other vision-capable models using the OpenAI API specification.

### 5. Factory Pattern Consistency

`get_multimodal_llm_chat()` mirrors the existing `get_llm_chat()` factory in `workspace/llm_shell.py`, providing a familiar interface for developers already using TopsailAI.

## Testing

The multimodal module includes **233 unit tests** covering:
- Content class creation and serialization
- Message validation and format conversion
- Prompt base message management
- LLM parameter building with content array preservation
- Chat interface with mocked LLM calls
- Tool function behavior with mocked dependencies (image, voice, video)

All tests pass and no regressions were introduced to existing tests.

## Future Enhancements

- Streaming responses for multimodal content
- Batch image/audio/video processing
- Integration with the main agent ReAct loop for automatic media analysis during task execution
- Support for additional model providers beyond OpenAI-compatible APIs
