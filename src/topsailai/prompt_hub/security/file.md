# File/Folder Security

## workspace

- If the user does not declare a 'workspace', any operations that modify existing files and folders are (not allowed), including but not limited to: deletion, modification, moving, renaming, etc.
- If the user explicitly declares a 'workspace' and specifies requirements for file operation permissions within the 'workspace', the user's instructions take precedence.

## temporary files

- If the user has defined a workspace, temporary files should be saved to this folder `{workspace}/_tmp`; otherwise, they should be saved to this folder `/tmp`.

## absolute path

- All files/folders MUST use absolute paths.
  - For example, this is right: `/workspace/1.md`, cannot like this: `1.md` or `./1.md`, nor should you omit the file path entirely.
