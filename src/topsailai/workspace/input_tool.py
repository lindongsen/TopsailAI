'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-19
  Purpose: Input handling utilities for TopsailAI system
'''

import os
import sys

# DONOT DELETE THIS FOR FUNCTION 'input'
import readline

from topsailai.utils import (
    env_tool,
    file_tool,
)
from topsailai.workspace.hook_instruction import (
    HookInstruction,
    TRIGGER_CHARS,
)

SPLIT_LINE = "--------------------------------------------------------------------------------"
INPUT_TIPS = ">>> Your Turn: "

DESCRIPTION_EXIT_SET = ["exit", "quit", "/exit", "/quit"]


def hook_message(message: str, hook: HookInstruction) -> bool:
    """
    Process a message through hook instructions if applicable.

    Checks if the message matches any registered hook instructions and executes
    them if found. Also handles exit commands.

    Args:
        message (str): The input message to process
        hook (HookInstruction): Hook instruction manager instance

    Returns:
        bool: True if a hook was called, False otherwise

    Example:
        >>> hook = HookInstruction()
        >>> hook_message("/help", hook)
        True  # If /help hook exists
        >>> hook_message("hello", hook)
        False
    """
    message = message.strip()
    if not message:
        return False

    if message in DESCRIPTION_EXIT_SET:
        sys.exit(0)

    if hook is None:
        return False

    if hook.exist_hook(message):
        hook.call_hook(message)
        return True
    elif message[0] in TRIGGER_CHARS:
        if message.lower() == "/noop":
            return False
        hook.call_hook("/help " + message)
        return True
    return False


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
        message = input(tips)
        message = message.strip()
        if not message:
            continue
        if hook_message(message, hook):
            continue
        break
    if message.lower() == "/noop":
        return ""
    return message


def input_multi_line(tips: str = "", hook: HookInstruction = None) -> str:
    """
    Get multi-line input from user with hook processing.

    Allows user to enter multiple lines of text terminated by EOF (Ctrl+D)
    or the string "EOF". Processes hooks after first line is entered.

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
            line = input()
            if line == "EOF":
                break
            message += line + "\n"
        except EOFError:
            break

        if count == 1 or '\n' not in message.strip():
            if hook_message(message, hook):
                message = ""
                break
            if message.strip().lower() ==  "/noop":
                return ""

    message = message.strip()
    if message:
        if not hook_message(message, hook):
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
    except KeyboardInterrupt as e:
        if input_yes("Quit Your Turn? [yes/no] "):
            raise e
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
    # all of argvs are files
    _flag_all_files, all_files = file_tool.get_all_files(sys.argv[1:])
    message = ""
    if _flag_all_files and all_files:
        for _file_path in all_files:
            with open(_file_path, encoding='utf-8') as fd:
                message += fd.read().strip() + "\n---\n"
        if message:
            call_hook_get_message_for_task_from_file()

            msg_more = ""
            if env_tool.is_interactive_mode():
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
    yn = input(tips)
    return yn.strip().lower() == "yes"
