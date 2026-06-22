# Context Management for File Operations

[ACTION] First, explore and understand the project's file structure. Do not read any file contents until you have a good understanding of the directory layout.

When the output content is too long, it will be forcibly truncated, and the flag information is `force to truncate`.

IF full file content is present in the context: Analyze directly without invoking any file-reading tools.
ELSE IF essential information is missing: Read specific segments only when necessary.

## File Content Inspection

Scope: Apply ONLY to file inspection/probing. IGNORE if the goal is analysis, summarization, or data extraction.
Rule: For inspection/probing, unless full-content is explicitly requested, read only partial content (e.g., head/tail -c 100 file).

## Command Output Control

- Ignore stderr content when using:
  curl, Example `curl https://example.com 2>/dev/null`;
  `uv add`, Example `uv add pip 2>/dev/null`;

## Temporary File Utilization

For the storage location of temporary files, refer to Section "File/Folder Security".

- Save results to temporary files when not all tool output needs attention
- Read partial content from temporary files for inspection
- Promptly clean up temporary resources after inspection completion
