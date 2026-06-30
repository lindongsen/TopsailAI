'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-20
  Purpose: Chat logger module providing a pre-configured logger instance for chat-related logging.

  This module initializes a logger specifically designed for chat operations.
  Logs are written to a dedicated file so that stdout/stderr remain free of
  logging output.
'''

from .base_logger import setup_logger
import logging

# Logger name constant for chat operations
LOGGER_NAME = "chat"
# Pre-configured logger instance for chat logging.
# Writes to chat.log with DEBUG level so that all chat-related messages are
# captured regardless of the global log-level setting.
logger = setup_logger(LOGGER_NAME, level=logging.DEBUG)
