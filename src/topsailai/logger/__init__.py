"""
TopsailAI Logger Package

This package provides logging functionality for the TopsailAI system,
including custom formatters with agent/thread information and pre-configured
logger instances.

Modules:
    base_logger: Core logging infrastructure with AgentFormatter and setup_logger function.
    log_chat: Pre-configured logger instance for chat operations.

Exports:
    logger: The chat logger instance for convenient import.

Example:
    >>> from topsailai.logger import logger
    >>> logger.info("Application started")
"""

from .log_chat import logger
