"""
TopsailAI Logger Package

This package provides logging functionality for the TopsailAI system,
including custom formatters with agent/thread information and pre-configured
logger instances.

Importing this package automatically configures the Python root logger so that
standard ``logging.getLogger(__name__)`` loggers inherit the project-wide format
without requiring an explicit import of ``topsailai.logger``.

The automatic root logger configuration can be disabled by setting the
environment variable ``TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG=1`` before importing
this package.

The default log level is ``INFO`` (``DEBUG`` when ``DEBUG=1``). It can be
overridden by setting ``TOPSAILAI_LOG_LEVEL`` to one of ``DEBUG``, ``INFO``,
``WARNING``, ``ERROR``, or ``CRITICAL`` (case-insensitive).

Logs from the root logger are written to rotating files under the TopsailAI log
folder. The main log file is ``topsailai.log``; a secondary file named
``topsailai.log.ec`` receives only ``ERROR`` and ``CRITICAL`` messages so that
failures can be located quickly. Standard output remains free of logging
content. Named loggers created via ``setup_logger()`` also write to files by
default.

Modules:
    base_logger: Core logging infrastructure with AgentFormatter, setup_logger,
        configure_root_logger, and log-level resolution functions.
    log_chat: Pre-configured logger instance for chat-related logging.

Exports:
    logger: The chat logger instance for convenient import.
    setup_logger: Helper to configure a named logger.
    AgentFormatter: Custom formatter adding agent/thread context.
    configure_root_logger: Applies the project format and file handlers to the
        root logger.

Example:
    >>> import logging
    >>> logger = logging.getLogger(__name__)
    >>> logger.info("Application started")

    >>> # Or use the pre-configured chat logger
    >>> from topsailai.logger import logger
    >>> logger.info("Chat event")

    >>> # Disable automatic root logger configuration
    >>> import os
    >>> os.environ["TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG"] = "1"
    >>> from topsailai import logger  # root logger will not be modified
"""

from .base_logger import setup_logger, AgentFormatter, configure_root_logger
from .log_chat import logger
