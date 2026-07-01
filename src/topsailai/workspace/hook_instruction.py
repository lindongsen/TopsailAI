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

import json
import logging
import os
import readline

from topsailai.utils import (
    json_tool,
    print_tool,
    format_tool,
)
from topsailai.workspace.folder_constants import FILE_INPUT_COMPLETIONS
from topsailai.workspace.plugin_instruction.base.init import (
    INSTRUCTIONS,
)

logger = logging.getLogger(__name__)


# Characters that trigger hook processing when found at the beginning of a message
TRIGGER_CHARS = "/"

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
        self.hook_map = {}
        self.add_hook("/help", self.show_help, "show help info")

        # add plugin hooks
        self.load_instructions(INSTRUCTIONS)

        # generate input completions for terminal TAB completion
        self.generate_input_completions()

        # tab completion
        self.setup_readline_completion()
        return

    def _extract_completion_doc(self, func) -> str:
        """Return the first non-empty line of *func*'s docstring, if any."""
        doc = getattr(func, "__doc__", None) or ""
        doc = doc.strip()
        if not doc:
            return ""
        for line in doc.splitlines():
            line = line.strip()
            if line:
                return line
        return ""

    def _load_existing_completions(self) -> dict[str, list[str]]:
        """Load alias mappings from the existing completions file.

        Returns a dict mapping command text (e.g. "/help") to its list of
        aliases.  This preserves manually-curated aliases across
        regenerations.
        """
        if not os.path.exists(FILE_INPUT_COMPLETIONS):
            return {}
        try:
            with open(FILE_INPUT_COMPLETIONS, "r", encoding="utf-8") as fd:
                data = json.load(fd)
        except Exception as exc:
            logger.debug(
                "Could not load existing input completions %s: %s",
                FILE_INPUT_COMPLETIONS,
                exc,
            )
            return {}

        aliases: dict[str, list[str]] = {}
        if isinstance(data, dict) and isinstance(data.get("completions"), list):
            for entry in data.get("completions", []):
                if not isinstance(entry, dict):
                    continue
                text = entry.get("text")
                if not isinstance(text, str):
                    continue
                aliases[text] = [
                    a for a in entry.get("aliases", [])
                    if isinstance(a, str)
                ]
        return aliases

    def generate_input_completions(self) -> None:
        """Write all registered hook commands to FILE_INPUT_COMPLETIONS.

        The generated JSON follows the format expected by the terminal helper
        in utils/input_tool.py:

            {"completions": [
                {"text": "/help", "aliases": ["/h"], "doc": "..."},
                ...
            ]}

        Aliases are preserved from the existing completions file and may also
        be declared via a function-level ``aliases`` attribute on the hook
        function.  Completion entries whose ``text`` is no longer present in
        ``self.hook_map`` are removed so stale commands do not persist.
        """
        existing_aliases = self._load_existing_completions()
        # Drop aliases for commands that are no longer registered.
        stale = set(existing_aliases.keys()) - set(self.hook_map.keys())
        for key in stale:
            del existing_aliases[key]

        completions: list[dict] = []

        for hook_name in sorted(self.hook_map.keys()):
            hook_funcs = self.hook_map[hook_name]
            hook_func = hook_funcs[0] if hook_funcs else None

            doc = ""
            func_aliases: list[str] = []
            if hook_func is not None:
                doc = self._extract_completion_doc(hook_func.func)
                raw_aliases = getattr(hook_func.func, "aliases", None)
                if isinstance(raw_aliases, (list, tuple)):
                    func_aliases = [a for a in raw_aliases if isinstance(a, str)]

            aliases = list(existing_aliases.get(hook_name, []))
            for alias in func_aliases:
                if alias not in aliases:
                    aliases.append(alias)

            completions.append({
                "text": hook_name,
                "aliases": aliases,
                "doc": doc,
            })

        data = {"completions": completions}
        try:
            parent = os.path.dirname(FILE_INPUT_COMPLETIONS)
            if parent and not os.path.exists(parent):
                os.makedirs(parent, exist_ok=True)
            with open(FILE_INPUT_COMPLETIONS, "w", encoding="utf-8") as fd:
                json.dump(data, fd, ensure_ascii=False, indent=2)
                fd.write("\n")
        except OSError as exc:
            logger.debug(
                "Could not write input completions %s: %s",
                FILE_INPUT_COMPLETIONS,
                exc,
            )
        return

    def refresh_input_completions(self) -> None:
        """Regenerate and re-apply input completions safely.

        This method is the single entry point for refreshing completions after
        any change to ``self.hook_map``.  All exceptions are caught and logged
        internally so callers never need to handle refresh failures.
        """
        try:
            self.generate_input_completions()
            self.setup_readline_completion()
        except Exception as exc:
            logger.debug(
                "Failed to refresh input completions: %s",
                exc,
                exc_info=True,
            )
        return

    def load_instructions(self, instructions:dict):
        """ add instructions to hook_map """
        for key, func in instructions.items():
            self.add_hook(key, func, "")
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

    def _hook_completer(self, text, state):
        """
        readline completer callback for hook names.

        Dynamically generates completion candidates from the current keys
        in self.hook_map. When text starts with a trigger character (e.g., "/"),
        returns matching hook names; when text is empty, returns all hook names.

        Args:
            text (str): The current input text to complete.
            state (int): The index of the completion candidate to return.

        Returns:
            str or None: The matching hook name at the given state index,
                         or None if no more matches.
        """
        if state == 0:
            if not text:
                self._completions = sorted(self.hook_map.keys())
            else:
                self._completions = sorted(
                    k for k in self.hook_map.keys() if k.startswith(text)
                )
        try:
            return self._completions[state]
        except IndexError:
            return None

    def setup_readline_completion(self):
        """
        Enable readline tab-completion for hook names.

        Configures the readline module so that pressing Tab in the terminal
        will auto-complete against the current keys in self.hook_map.
        The completion list is dynamic and reflects add_hook / del_hook changes.

        Returns:
            None
        """
        readline.set_completer(self._hook_completer)
        readline.parse_and_bind("tab: complete")
        # Remove trigger characters from completer delimiters so that
        # "/hel<Tab>" can complete to "/help" instead of treating "/" as a word break.
        delims = readline.get_completer_delims()
        for ch in TRIGGER_CHARS:
            delims = delims.replace(ch, "")
        readline.set_completer_delims(delims)
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
        self.refresh_input_completions()
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
        self.refresh_input_completions()
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

        if not hook_name:
            return

        if hook_name not in self.hook_map:
            self.show_help(hook_name)
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
                print_tool.print_error(f"hook is failed [{hook_name}]: args={args} kwargs={kwargs} {e}", exception=True)
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
