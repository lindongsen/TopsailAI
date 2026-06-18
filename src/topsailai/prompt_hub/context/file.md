# Context Management for File Operations

[ACTION] First, explore and understand the project's file structure. Do not read any file contents until you have a good understanding of the directory layout.

> When the output content is too long, it will be forcibly truncated, and the flag information is `force to truncate`.

## File Content Inspection

- When the user hasn't explicitly requested a full-content inspection, only read partial content during file checks.
  Example: For text material inspection, only read the first 100 bytes. Applicable commands: `head -c 100 file`, `tail -c 100 file`.

## Command Output Control

- Ignore stderr content when using:
  curl, Example `curl https://example.com 2>/dev/null`;
  `uv add`, Example `uv add pip 2>/dev/null`;

## Temporary File Utilization

For the storage location of temporary files, refer to Section "File/Folder Security".

- Save results to temporary files when not all tool output needs attention
- Read partial content from temporary files for inspection
- Promptly clean up temporary resources after inspection completion
