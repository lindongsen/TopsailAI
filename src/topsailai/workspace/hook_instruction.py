'''
Hook Instruction System

This module provides a flexible hook system for managing and executing instruction-based hooks.
It allows registering functions to be called when specific trigger characters (like "/" or "@")
are detected in messages.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-12-25
Purpose: Provide a hook-based instruction system for command processing
'''

from topsailai.utils import (
    json_tool,
    print_tool,
    format_tool,
)
from topsailai.workspace.plugin_instruction import (
    INSTRUCTIONS,
)


# Characters that trigger hook processing when found at the beginning of a message
TRIGGER_CHARS = "/@"

SPLIT_LINE = "-" * 73

class HookFunc(object):
    """
    A wrapper class for hook functions with metadata.

    This class encapsulates a function along with its description and default arguments,
    making it easier to manage and call hook functions with predefined parameters.

    Attributes:
        description (str): A brief description of what the hook function does
        func (callable): The actual function to be executed
        args (tuple, optional): Default positional arguments for the function
        kwargs (dict, optional): Default keyword arguments for the function
    """

    def __init__(self, description, func, args=None, kwargs=None):
        """
        Initialize a HookFunc instance.

        Args:
            description (str): A brief description of the hook function's purpose
            func (callable): The function to be wrapped
            args (tuple, optional): Default positional arguments. Defaults to None.
            kwargs (dict, optional): Default keyword arguments. Defaults to None.
        """
        self.description = description or (
            "\n" + print_tool.add_indent_to_lines(func.__doc__, indent=8)
        )
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def __call__(self, *args, **kwargs):
        """
        Execute the wrapped function with provided or default arguments.

        If no arguments are provided, uses the default arguments stored in the instance.
        Otherwise, uses the provided arguments.

        Args:
            *args: Positional arguments to pass to the function
            **kwargs: Keyword arguments to pass to the function

        Returns:
            The return value of the wrapped function
        """
        if not args:
            args = self.args or tuple()
        if not kwargs:
            kwargs = self.kwargs or dict()
        return self.func(*args, **kwargs)


class HookBaseUtils(object):
    pass


class HookInstruction(HookBaseUtils):
    """
    A manager class for hook-based instructions.

    This class maintains a registry of hook functions mapped to trigger strings.
    It provides methods to add, remove, check for, and execute hooks based on
    trigger characters at the beginning of messages.

    Example:
        hook_instruction = HookInstruction()
        def _clear():
            ...
        def _story():
            ...
        hook_instruction.add_hook("/clear", _clear)
        hook_instruction.add_hook("/story", _story)
        ...
        if hook_instruction.exist_hook(message):
            hook_instruction.call_hook(message)
    """

    def __init__(self):
        """
        Initialize the HookInstruction manager.

        Creates an empty hook map and registers a default "/help" hook
        that displays help information about all registered hooks.
        """
        # Dictionary mapping hook names to lists of HookFunc objects
        # Structure: {hook_name: [HookFunc1, HookFunc2, ...]}
        self.hook_map = {
            "/help": [HookFunc("show help info", self.show_help)],
        }

        # add plugin hooks
        self.load_instructions(INSTRUCTIONS)

        return

    def load_instructions(self, instructions:dict):
        """ add instructions to hook_map """
        for key, func in instructions.items():
            if key[0] not in TRIGGER_CHARS:
                key = TRIGGER_CHARS[0] + key
            self.hook_map[key] = [
                HookFunc("", func),
            ]
        return

    def __print_hook(self, hook_name:str):
        hook_set = self.hook_map[hook_name]
        print(f"\n  {hook_name}")
        for hook_func in hook_set:
            print(f"    - {hook_func.func.__name__}, {hook_func.description}")
        return

    def show_help(self, hook_name:str=None):
        """
        Display help information for all registered hooks.

        Prints a formatted list of all available hook commands and their
        descriptions in a user-friendly format.

        Returns:
            None
        """
        print(SPLIT_LINE)
        print("Instructions:")
        # all
        for _hook_name in self.hook_map:
            if hook_name and hook_name not in _hook_name:
                continue
            self.__print_hook(_hook_name)
        print(SPLIT_LINE)
        return

    def add_hook(self, hook_name, hook_func: HookFunc, description=""):
        """
        Register a new hook function.

        Adds a hook function to the registry under the specified hook name.
        If the hook name doesn't exist, creates a new entry for it.

        Args:
            hook_name (str): The trigger string for the hook (e.g., "/clear")
            hook_func (HookFunc or callable): The function to register
            description (str, optional): Description of the hook function. Defaults to "".

        Returns:
            None

        Raises:
            AssertionError: If hook_func is not callable
        """
        assert callable(hook_func)

        if hook_name[0] not in TRIGGER_CHARS:
            hook_name = TRIGGER_CHARS[0] + hook_name

        if hook_name not in self.hook_map:
            self.hook_map[hook_name] = []

        if not isinstance(hook_func, HookFunc):
            hook_func = HookFunc(
                description=description,
                func=hook_func,
            )

        self.hook_map[hook_name].append(hook_func)
        return

    def del_hook(self, hook_name, hook_func: HookFunc):
        """
        Remove a hook function from the registry.

        Removes the specified hook function from the given hook name's list.
        If the hook function is not found, does nothing.

        Args:
            hook_name (str): The hook name to remove from
            hook_func (HookFunc): The specific hook function to remove

        Returns:
            None
        """
        if hook_name in self.hook_map:
            if hook_func in self.hook_map[hook_name]:
                self.hook_map[hook_name].remove(hook_func)
        return

    def __is_help(self, s) -> bool:
        """ check str if is 'help' """
        if isinstance(s, str) and s in [
            "help",
            "--help",
            "-h",
            "/help",
            "@help",
        ]:
            return True
        return False

    def call_hook(self, hook_name, kwargs:str|dict=None):
        """
        Execute all hook functions registered under a given hook name.

        Calls each hook function in the order they were registered.
        If the hook name doesn't exist, returns without doing anything.

        Args:
            hook_name (str): The hook name to execute

        Returns:
            None
        """
        if self.__is_help(kwargs):
            self.show_help(hook_name)
            return

        # case: /xxx kwargs
        if not kwargs and ' ' in hook_name:
            hook_name, kwargs = hook_name.split(' ', 1)

        hook_name = hook_name.strip()

        if self.__is_help(kwargs):
            self.show_help(hook_name)
            return

        if hook_name not in self.hook_map:
            return

        args = []
        if isinstance(kwargs, str):
            new_kwargs = json_tool.safe_json_load(kwargs)
            if not isinstance(new_kwargs, dict):
                new_kwargs = None

            if not new_kwargs:
                if '=' in kwargs:
                    new_kwargs = format_tool.parse_str_to_dict(kwargs)
                elif ' ' in kwargs:
                    args = kwargs.split(' ')
                else:
                    args = [kwargs]

            if new_kwargs:
                kwargs = new_kwargs

        if not kwargs or not isinstance(kwargs, dict):
            kwargs = {}

        for hook_func in self.hook_map[hook_name]:
            try:
                ret = hook_func(*args, **kwargs)
                if ret:
                    print(ret)
            except Exception as e:
                print_tool.print_error(f"hook is failed [{hook_name}]: args={args} kwargs={kwargs} {e}")
        return

    def exist_hook(self, hook_name) -> bool:
        """
        Check if a hook name exists in the registry.

        Verifies if the given string starts with a trigger character and
        if it matches a registered hook name.

        Args:
            hook_name (str): The string to check for hook existence

        Returns:
            bool: True if the hook exists, False otherwise
        """
        if hook_name[0] in TRIGGER_CHARS:
            if hook_name in self.hook_map:
                return True

            # /xxx kwargs
            hook_name = hook_name.split(' ', 1)[0]
            if hook_name in self.hook_map:
                return True

        return False
