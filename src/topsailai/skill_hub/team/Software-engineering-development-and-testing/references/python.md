# Python Development rules

## Project Structure

It should include the following:

- folder: `cli`, store script files
- folder: `src`, store source code files
- folder: `tests`, store test files
- file: `README.md`, save detail info about of the project

## Project Management

Use the uv tool to manage the project:

- Initialize project: `uv init`. You cannot create or edit the configuration file `pyproject.toml` - it must be managed exclusively by the uv tool itself.
- Add dependency: `uv add {package_name}`
- Remove dependency: `uv remove {package_name}`
- Execute command: `uv run {python_file_or_command}`

## Test

If the test file already exists, you need to read and understand its content.

- Unit tests folder is `{ProjectFolder}/tests/unit`
- Use pytest
- Use `uv run` to run pytest
- Test file name: `test_{module_path}.py`,
  - example: one module file path is `src/topsailai/utils/file_tool.py`, {module_path} is `topsailai_utils_file_tool`
  - example: one function is `from project.context.a.b import functionX`, {module_path} is `project_context_a_b_functionX`
- Try not to use mock for test as much as possible
