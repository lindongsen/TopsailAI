'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-20
  Purpose: Chat logger module providing a pre-configured logger instance for chat-related logging.
  
  This module initializes a logger specifically designed for chat operations,
  using the base_logger setup with console output (no file logging).
'''

from .base_logger import setup_logger

# Logger name constant for chat operations
LOGGER_NAME = "chat"

# Pre-configured logger instance for chat logging
# Uses console output (log_file=None) with DEBUG level by default
logger = setup_logger(LOGGER_NAME, None)
