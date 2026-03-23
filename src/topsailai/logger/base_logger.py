'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-20
  Purpose: Base logging module for TopsailAI, providing custom formatter and logger setup functionality.
'''

import os
import logging
from logging.handlers import RotatingFileHandler


class AgentFormatter(logging.Formatter):
    """
    Custom log formatter that adds agent and thread information to log records.
    
    This formatter extends the standard logging.Formatter to include:
    - Agent name from thread-local storage or environment variables
    - Thread name from thread-local storage
    - A message_id combining agent and thread information
    
    Attributes:
        fmt (str): The format string for log messages.
        datefmt (str): The date format string.
    """
    
    def __init__(self, fmt=None, datefmt=None):
        """
        Initialize the AgentFormatter with format strings.
        
        Args:
            fmt (str, optional): The format string for log messages. 
                Defaults to None, which uses the standard format.
            datefmt (str, optional): The date format string. 
                Defaults to None, which uses the standard date format.
        """
        logging.Formatter.__init__(self, fmt, datefmt)

    def format(self, record):
        """
        Format the log record with agent and thread information.
        
        This method retrieves agent name and thread name from thread-local storage
        or environment variables, constructs a message_id, and adds it to the record
        before formatting.
        
        Args:
            record (logging.LogRecord): The log record to format.
        
        Returns:
            str: The formatted log message string.
        
        Note:
            The message_id attribute is dynamically added to the record in the format:
            "(agent_name:thread_name)" if either is present, otherwise empty string.
        """
        # Import thread-local utilities (kept inside to avoid circular imports)
        from topsailai.utils.thread_local_tool import (
            get_agent_name,
            get_thread_name,
        )

        # Retrieve agent name from thread-local storage or environment variables
        agent_name = get_agent_name()
        if not agent_name:
            # Fallback to environment variables
            agent_name = os.environ.get("AGENT_NAME", "") or os.environ.get("AI_AGENT", "")
        if not agent_name:
            agent_name = ""

        # Retrieve thread name from thread-local storage
        thread_name = get_thread_name() or ""

        # Generate message_id combining agent and thread information
        message_id = ""
        if agent_name or thread_name:
            message_id = f"({agent_name}:{thread_name})"
        record.message_id = message_id

        # Apply standard formatting
        return logging.Formatter.format(self, record)


def setup_logger(name: str = None, log_file: str = None, level=logging.DEBUG):
    """
    Create and configure a logger with custom formatting and output handling.
    
    This function sets up a logger with the AgentFormatter for consistent formatting
    across the application. It supports both file-based logging (with rotation) and
    console output.
    
    Args:
        name (str, optional): The name of the logger. If provided and log_file is not
            specified, the log file will be named "{name}.log". Defaults to None.
        log_file (str, optional): Path to the log file. If provided, enables file-based
            logging with rotation. If None and name is provided, defaults to "{name}.log".
            If both are None, uses console output. Defaults to None.
        level (int, optional): The logging level. Defaults to logging.DEBUG.
            Common levels: DEBUG, INFO, WARNING, ERROR, CRITICAL.
    
    Returns:
        logging.Logger: The configured logger instance.
    
    Examples:
        >>> # Create a console logger
        >>> logger = setup_logger("my_app")
        >>> 
        >>> # Create a file logger with rotation
        >>> logger = setup_logger("my_app", "/var/log/my_app.log")
        >>> 
        >>> # Create a logger with custom level
        >>> logger = setup_logger("my_app", level=logging.INFO)
    
    Note:
        When log_file is specified, uses RotatingFileHandler with:
        - maxBytes: 100MB (100000000 bytes)
        - backupCount: 1 (keeps one backup file)
    """
    # Create custom formatter with agent and thread information
    formatter = AgentFormatter(
        '%(asctime)s %(levelname)s -%(thread)d- %(message)s (%(pathname)s:%(lineno)d) %(message_id)s'
    )
    
    # Get or create logger instance
    _logger = logging.getLogger(name)

    # Determine log file path if not explicitly provided
    if not log_file:
        if name:
            log_file = name + ".log"

    # Configure handler based on output destination
    if log_file:
        # File-based logging with rotation (100MB max size, 1 backup)
        file_handler = RotatingFileHandler(log_file, maxBytes=100000000, backupCount=1)
        file_handler.setFormatter(formatter)
        _logger.addHandler(file_handler)
    else:
        # Console output
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        _logger.addHandler(stream_handler)

    # Set logging level
    _logger.setLevel(level)
    
    return _logger
