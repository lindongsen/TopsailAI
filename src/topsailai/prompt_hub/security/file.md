# File/Folder Security

## workspace

Define the working folder for task.

- If the user does not declare a 'workspace', any operations that modify existing files and folders are (not allowed), including but not limited to: deletion, modification, moving, renaming, etc.
- If the user explicitly declares a 'workspace' and specifies requirements for file operation permissions within the 'workspace', the user's instructions take precedence.

## temporary files

- If the user has defined a workspace, all temporary files MUST be saved under `{workspace}/.tmp`; otherwise, they MUST be saved under `/tmp`.
- Test-generated artifacts are temporary files and MUST follow the same rule. This includes, but is not limited to, `.out` files, `.coverage` data, coverage reports, test logs, captured command output, test reports, caches, and other files produced only for test execution or inspection.
- Test commands and tools MUST be configured so these artifacts are written directly to the designated temporary folder rather than the workspace root, source directories, or test directories.
- An artifact may be written elsewhere only when the user explicitly requests that location or when it is an intentional, maintained project deliverable.

## absolute path

- All files/folders MUST use absolute paths.
  - For example, this is right: `/workspace/1.md`, cannot like this: `1.md` or `./1.md`, nor should you omit the file path entirely.
