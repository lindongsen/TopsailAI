'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose:
'''

from topsailai.logger.base_logger import setup_logger

# Logger name constant for chat operations
LOGGER_NAME = "agent_daemon"

# Pre-configured logger instance for chat logging
# Uses console output (log_file=None) with DEBUG level by default
logger = setup_logger(LOGGER_NAME, None)

# default log file: /topsailai/log/{LOGGER_NAME}.log
