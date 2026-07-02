'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-19
  Purpose: Input handling utilities for TopsailAI system
'''
import json
import logging
import os
import sys

# DONOT DELETE THIS FOR FUNCTION 'input'
import readline
from topsailai.utils import (
    env_tool,
    file_tool,
    input_tool as utils_input_tool,
    thread_local_tool,
)
from topsailai.utils.instruction_tool import (
    hook_message,
)
from topsailai.workspace.folder_constants import (
    FILE_INPUT_COMPLETIONS,
    FILE_INPUT_HISTORY_JSONL,
    FOLDER_WORKSPACE_TASK,
)
from topsailai.workspace.hook_instruction import (
    HookInstruction,
)
from topsailai.workspace.task.cleanup import (
    register_cleanup_file,
    unregister_cleanup_file,
)

logger = logging.getLogger(__name__)

SPLIT_LINE = "--------------------------------------------------------------------------------"
INPUT_TIPS = f">>> Your Turn: (pid={os.getpid()}) "


def _load_input_history_jsonl() -> None:
    """Load previous input history from the JSONL file into readline.

    Each line in the history file is expected to be a JSON object with a
    ``text`` field.  The ``text`` values are added to the in-process readline
    history so the user can recall previous messages with the UP/DOWN arrow
    keys in direct terminal input mode.
    """
    if not os.path.exists(FILE_INPUT_HISTORY_JSONL):
        return
    try:
        with open(FILE_INPUT_HISTORY_JSONL, "r", encoding="utf-8") as fd:
            for line in fd:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    text = entry.get("text", "")
                    if text:
                        readline.add_history(text)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass


def _append_input_history_jsonl(message: str) -> None:
    """Append a submitted message to the JSONL history file.

    The entry is written as ``{"ts": ..., "session_id": ..., "text": ...}``.
    Empty messages are ignored.
    """
    if not message:
        return
    session_id = env_tool.get_session_id() or ""
    utils_input_tool.append_input_history_jsonl(
        FILE_INPUT_HISTORY_JSONL, session_id, message
    )


# Load JSONL history into readline on module import.
_load_input_history_jsonl()


def _input(tips: str = "") -> str:
    """Unified line input: read from a named pipe or fall back to stdin.

    When ``TOPSAILAI_INPUT_PIPE_ENABLED`` is set, this function reads a
    single line from the session-scoped named pipe. Otherwise it delegates
    to the built-in ``input()`` function.

    Args:
        tips: Prompt text passed to ``input()`` in interactive mode.
            Ignored when pipe input is enabled.

    Returns:
        A single line of input (without the trailing newline).
    """
    if env_tool.is_input_pipe_enabled():
        return input_from_pipe_session(
            timeout=env_tool.get_input_pipe_timeout(),
            single_line=True,
            prompt=tips,
            history_file=FILE_INPUT_HISTORY_JSONL,
            completion_file=FILE_INPUT_COMPLETIONS,
        )
    return input(tips)


def input_one_line(tips: str = "", hook: HookInstruction = None) -> str:
    """
    Get single line input from user with hook processing.

    Continuously prompts the user for input until a non-empty, non-hook
    message is received. Handles hook instructions if provided.

    Args:
        tips (str, optional): Prompt message to display. Defaults to INPUT_TIPS.
        hook (HookInstruction, optional): Hook instruction manager. Defaults to None.

    Returns:
        str: User input message

    Example:
        >>> message = input_one_line("Enter your name: ")
        Enter your name: John
        >>> print(message)
        'John'
    """
    if not tips:
        tips = INPUT_TIPS

    message = ""
    while True:
        message = _input(tips)
        message = message.strip()
        if not message:
            continue
        if hook_message(message, hook):
            continue
        break
    if message.lower() == "/noop":
        return ""
    _append_input_history_jsonl(message)
    return message


def input_multi_line(tips: str = "", hook: HookInstruction = None) -> str:
    """
    Get multi-line input from user with hook processing.

    Allows user to enter multiple lines of text terminated by EOF (Ctrl+D)
    or the string "EOF". Processes hooks after first line is entered.

    When pipe-based input is enabled, each call to ``_input`` returns one
    line from the pipe. The pipe reader strips a trailing ``\\nEOF`` marker
    and signals end-of-input with an empty line; an embedded ``\\nEOF``
    marker in a multi-line payload is also handled here so that everything
    from the marker onward is discarded and the marker itself is never
    returned as content.

    Args:
        tips (str, optional): Prompt message to display. Defaults to INPUT_TIPS.
        hook (HookInstruction, optional): Hook instruction manager. Defaults to None.

    Returns:
        str: Combined multi-line user input

    Example:
        >>> message = input_multi_line("Enter your message: ")
        Enter your message: Press 'CTRL D' or Enter 'EOF' for end
        Line 1
        Line 2
        EOF
        >>> print(message)
        'Line 1\nLine 2'
    """
    if not tips:
        tips = INPUT_TIPS

    print(tips + " Press 'CTRL D' or Enter 'EOF' for end")
    sys.stdout.flush()
    message = ""
    count = 0
    while True:
        count += 1

        try:
            line = _input("")
            # A single read may contain a multi-line payload with an EOF
            # marker (e.g. a pipe source returning more than one line at
            # once).  Strip the marker and everything after it, then stop
            # reading so the marker is never returned as content.
            if "\nEOF\n" in line or line.endswith("\nEOF"):
                line = line.split("\nEOF", 1)[0]
                message += line + "\n"
                break
            if line == "EOF":
                break
            message += line + "\n"
        except EOFError:
            break
        if count == 1 or '\n' not in message.strip():
            if hook_message(message, hook):
                message = ""
                break
            if message.strip().lower() == "/noop":
                return ""

    message = message.strip()

    if message:
        if not hook_message(message, hook):
            _append_input_history_jsonl(message)
            return message
    return input_multi_line(tips, hook)


def input_message(tips: str = "", hook: HookInstruction = None) -> str:
    """
    Get user input based on environment configuration.

    Uses either single-line or multi-line input based on the system's
    environment configuration. Displays a separator line before prompting.

    Args:
        tips (str, optional): Prompt message to display. Defaults to empty string.
        hook (HookInstruction, optional): Hook instruction manager. Defaults to None.

    Returns:
        str: User input message

    Example:
        >>> message = input_message("What would you like to do? ")
        --------------------------------------------------------------------------------
        What would you like to do?
    """
    print(SPLIT_LINE)
    try:
        if env_tool.is_chat_multi_line():
            return input_multi_line(tips, hook)
        return input_one_line(tips, hook)
    except KeyboardInterrupt:
        if input_yes("Quit Your Turn? [yes/no] "):
            raise Exception("User Quit!")
    return ""

def call_hook_get_message_for_task_from_file():
    """ user message is a file """
    if not env_tool.EnvReaderInstance.get("TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP", formatter=int):
        os.environ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"] = "1"
    return

def get_message(hook: HookInstruction = None, need_input=True) -> str:
    """
    Get message from command line arguments or user input.

    First attempts to get message from command line arguments. If no arguments
    are provided or if the argument is "-", reads from stdin or falls back
    to interactive input.

    Args:
        hook (HookInstruction, optional): Hook instruction manager. Defaults to None.

    Returns:
        str: Message content from arguments, stdin, or user input

    Example:
        # When called with: python script.py "Hello World"
        >>> message = get_message()
        >>> print(message)
        'Hello World'

        # When called with: python script.py -
        # and stdin contains "From stdin"
        >>> message = get_message()
        >>> print(message)
        'From stdin'
    """
    # check if sub_agent
    if thread_local_tool.get_agent_object():
        return ""

    # all of argvs are files
    _flag_all_files, all_files = file_tool.get_all_files(sys.argv[1:])
    message = ""
    if _flag_all_files and all_files:
        for _file_path in all_files:
            with open(_file_path, encoding='utf-8') as fd:
                _head = "\n---\n" + f"\n> File: {_file_path} > START\n"
                _tail = "\n---\n" + f"\n> File: {_file_path} > END\n"
                message += _head + fd.read().strip() + _tail
        message += "\n---\n"
        if message:
            call_hook_get_message_for_task_from_file()

            msg_more = ""
            if env_tool.is_interactive_mode() and need_input:
                print(message)
                print("")
                msg_more = input_message("", hook=hook)

            return message + msg_more

    message = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else ""

    # message from file
    file_path = message
    if len(sys.argv) > 1 and sys.argv[1] == '-':
        file_path = "/dev/stdin"
    if file_path and os.path.exists(file_path):
        with open(file_path, encoding='utf-8') as fd:
            message = fd.read()
        # hook for message from file
        call_hook_get_message_for_task_from_file()

    message = message.strip()
    if not message and need_input:
        message = input_message(hook=hook)
    return message


def input_yes(tips: str = "Continue [yes/no] ") -> bool:
    """
    Get yes/no confirmation from user.

    Prompts the user for a yes/no response and returns True only if the
    response is exactly "yes" (case-insensitive, stripped).

    Args:
        tips (str, optional): Prompt message. Defaults to "Continue [yes/no] ".

    Returns:
        bool: True if user entered "yes", False otherwise

    Example:
        >>> should_continue = input_yes("Proceed with deletion? ")
        Proceed with deletion? yes
        >>> print(should_continue)
        True
    """
    yn = input_one_line(tips)
    return yn.strip().lower() == "yes"


def _build_pipe_path(session_id: str | None = None) -> str:
    """Build the pipe path for the current session.

    The path follows the convention:
    ``FOLDER_WORKSPACE_TASK/{session_id}.{pid}.session.pipe``.  When no
    session identifier is provided, the prefix ``topsailai`` is used so the
    filename becomes ``topsailai.{pid}.session.pipe``.

    Args:
        session_id: Optional session identifier. When omitted,
            ``env_tool.get_session_id()`` is used, falling back to
            ``"topsailai"`` when no session is configured.

    Returns:
        Absolute path to the session pipe.
    """
    if session_id is None:
        session_id = env_tool.get_session_id() or "topsailai"
    return os.path.join(
        FOLDER_WORKSPACE_TASK,
        f"{session_id}.{os.getpid()}.session.pipe",
    )


def input_from_pipe_session(
    session_id: str | None = None,
    *,
    timeout: float | None = None,
    encoding: str = "utf-8",
    eof_marker: str = "EOF",
    raise_eof_error: bool = True,
    single_line: bool = False,
    prompt: str = "",
    history_file: str = FILE_INPUT_HISTORY_JSONL,
    completion_file: str = FILE_INPUT_COMPLETIONS,
) -> str:
    """Read a message from a session-scoped named pipe.

    This is a convenience wrapper around
    :func:`topsailai.utils.input_tool.input_from_pipe` that constructs the
    pipe path from the current session and process ID, then delegates to the
    utility function.

    The FIFO is kept alive across calls so that multi-line pipe input (and
    multiple single-line messages sent to the same session) can be read from
    the same pipe. The pipe is registered for removal when the process exits.

    By default *raise_eof_error* is ``True`` so that the EOF marker is
    signaled to the workspace input loop via :class:`EOFError` rather than
    being returned as an empty string. This keeps multi-line input logic
    free of pipe-specific EOF detection.

    Parameters
    ----------
    session_id:
        Optional session identifier. Defaults to the value returned by
        :func:`topsailai.utils.env_tool.get_session_id`.
    timeout:
        Maximum time in seconds to wait for a writer. ``None`` waits
        indefinitely.
    encoding:
        Encoding used to decode bytes read from the pipe.
    eof_marker:
        Optional marker that terminates input when seen on its own line.
    raise_eof_error:
        When ``True`` (the default), an EOF marker raises :class:`EOFError`.
    single_line:
        When ``True``, return the first line of input (everything before
        the first ``\\n``). Any remaining content is discarded.
    prompt:
        Prompt displayed to the user when terminal input is used.
    history_file:
        Optional JSONL history file path used to preload readline history
        in the terminal helper subprocess.
    completion_file:
        Optional JSON file path used to configure TAB completion
        candidates in the terminal helper subprocess.

    Returns
    -------
    The decoded message read from the pipe.

    Raises
    ------
    NotImplementedError:
        If the platform does not support named pipes.
    TimeoutError:
        If *timeout* seconds pass without receiving any data.
    EOFError:
        If *raise_eof_error* is ``True`` and the EOF marker is reached.
    """
    pipe_path = _build_pipe_path(session_id)
    abs_path = os.path.abspath(pipe_path)
    register_cleanup_file(abs_path)
    try:
        return utils_input_tool.input_from_pipe(
            pipe_path,
            timeout=timeout,
            encoding=encoding,
            eof_marker=eof_marker,
            raise_eof_error=raise_eof_error,
            single_line=single_line,
            prompt=prompt,
            cleanup_pipe=False,
            history_file=history_file,
            completion_file=completion_file,
        )
    finally:
        unregister_cleanup_file(abs_path)
