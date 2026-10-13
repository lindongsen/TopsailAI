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

from topsailai.utils.instruction_tool import (
    HookBaseUtils,
    HookFunc,
    HookInstruction as HookInstructionBase,
    TRIGGER_CHARS,
    SPLIT_LINE,
)
from topsailai.utils import env_tool
from topsailai.workspace.plugin_instruction.hosting import bind_hosting
from topsailai.workspace.folder_constants import FILE_INPUT_COMPLETIONS
from topsailai.workspace.plugin_instruction.base.init import (
    INSTRUCTIONS,
)

class HookInstruction(HookInstructionBase):
    def __init__(self, *, session_getter=None):
        """Register hosting without extending the instruction lifecycle."""
        super().__init__(file_input_completions=FILE_INPUT_COMPLETIONS, instructions=INSTRUCTIONS)
        self.add_hook("/hosting", bind_hosting(session_getter or env_tool.get_session_id))
