'''
Chat History Manager Module

This module provides a framework for managing chat history messages and sessions.
It includes base classes for message storage and implementations using different
storage backends (e.g., SQLAlchemy for database storage).

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-29
Purpose: Manage chat history messages for AI Agent context management
'''

import os
from topsailai.utils import module_tool

# Dictionary containing all available chat history manager implementations
# Key: Manager class name
# Value: Manager class reference
ALL_MANAGERS = module_tool.get_function_map(
    "topsailai.context.chat_history_manager",
    "MANAGERS",
)