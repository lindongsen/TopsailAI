"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-20
Purpose: Base logging module for TopsailAI, providing custom formatter and logger setup functionality.
"""

import logging
import os
from logging.handlers import RotatingFileHandler


# Default format used by setup_logger() for named loggers. Preserved for backward
# compatibility; do not change without updating existing consumers.
DEFAULT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s -%(thread)d- %(message)s "
    "(%(pathname)s:%(lineno)d) %(message_id)s"
)

# Format used when configuring the Python root logger via configure_root_logger().
# It mirrors DEFAULT_LOG_FORMAT but inserts the logger name and process ID before
# message_id, as required by the project style: (name:pid) goes in the
# second-to-last position.
ROOT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s -%(thread)d- %(message)s "
    "(%(pathname)s:%(lineno)d) (%(name)s:%(process)d) %(message_id)s"
)

# Name of the root log file written by configure_root_logger().
# _get_default_log_file() appends '.log', so do not include the extension here.
ROOT_LOG_FILE_NAME = "topsailai"

# Environment variable that overrides the default/root log level.
ENV_LOG_LEVEL = "TOPSAILAI_LOG_LEVEL"

# Environment variable that enables DEBUG level when TOPSAILAI_LOG_LEVEL is unset.
ENV_DEBUG = "DEBUG"

# Environment variable that disables automatic root logger configuration.
ENV_DISABLE_ROOT_LOGGER_CONFIG = "TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG"


def _resolve_log_level(level=None):
    """
    Resolve the effective log level from explicit value, environment, or defaults.

    Resolution order:
        1. If ``level`` is provided and not ``None``, return it as-is.
        2. If ``TOPSAILAI_LOG_LEVEL`` is set to a valid level name or numeric
           string, return that level.
        3. If ``DEBUG=1``, return ``logging.DEBUG``.
        4. Otherwise return ``logging.INFO``.

    Args:
        level (int or str, optional): Explicit level. If provided, it takes
            precedence over environment variables.

    Returns:
        int: A logging level constant (e.g. logging.DEBUG, logging.INFO).
    """
    if level is not None:
        return level

    env_level = os.environ.get(ENV_LOG_LEVEL, "").strip().upper()
    if env_level:
        # Support both symbolic names and numeric level values.
        if hasattr(logging, env_level):
            resolved = getattr(logging, env_level)
            if isinstance(resolved, int):
                return resolved
        try:
            numeric = int(env_level)
            return numeric
        except ValueError:
            # Invalid value: fall through to defaults.
            pass

    if os.environ.get(ENV_DEBUG, "0") == "1":
        return logging.DEBUG

    return logging.INFO


def get_log_folder():
    try:
        from topsailai.workspace.folder_constants import FOLDER_LOG
        return FOLDER_LOG + "/"
    except Exception:
        pass
    return "/topsailai/log/"


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
                Defaults to None, which uses the project-wide default format.
            datefmt (str, optional): The date format string.
                Defaults to None, which uses the standard date format.
        """
        if fmt is None:
            fmt = DEFAULT_LOG_FORMAT
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

            This method mutates the incoming ``record`` object by setting
            ``record.message_id``. This follows the standard logging.Formatter
            convention (which also sets ``record.message``, ``record.asctime``, etc.)
            and is safe because each LogRecord is created fresh per log emission.
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


def _get_default_log_file(name: str) -> str:
    """
    Build the default log file path for a named logger.

    The log folder is created automatically if it does not exist. If creation
    fails, a ``RuntimeError`` is raised instead of silently falling back to the
    current working directory.

    Args:
        name (str): Logger name.

    Returns:
        str: Path to the log file, or empty string if ``name`` is empty.

    Raises:
        RuntimeError: If the log folder cannot be created.
    """
    if not name:
        return ""
    log_folder = get_log_folder()
    if not (os.path.exists(log_folder) and os.path.isdir(log_folder)):
        try:
            os.makedirs(log_folder, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Failed to create log folder {log_folder!r}: {exc}"
            ) from exc
    return os.path.join(log_folder, f"{name}.log")


def _ensure_handler(logger_instance: logging.Logger, handler: logging.Handler):
    """
    Add a handler to a logger only if an equivalent handler is not already attached.

    Two handlers are considered equivalent when they have the same class and,
    for file-based handlers, the same base filename. If a ``RotatingFileHandler``
    with a different path is already attached, it is removed and closed so that
    the new path takes effect (one file handler per logger).

    Args:
        logger_instance (logging.Logger): The logger to configure.
        handler (logging.Handler): The handler to add.
    """
    for existing in logger_instance.handlers:
        if existing.__class__ is not handler.__class__:
            continue
        if isinstance(handler, RotatingFileHandler):
            if getattr(existing, "baseFilename", None) == handler.baseFilename:
                handler.close()
                return
            # Same logger, different file path: replace the old file handler.
            logger_instance.removeHandler(existing)
            existing.close()
            break
        else:
            handler.close()
            return
    logger_instance.addHandler(handler)


def setup_logger(name: str = None, log_file: str = None, level=None):
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
        level (int or str, optional): The logging level. Defaults to None, which
            resolves from the ``TOPSAILAI_LOG_LEVEL`` environment variable, then
            ``DEBUG=1`` (DEBUG), otherwise INFO. Common levels: DEBUG, INFO,
            WARNING, ERROR, CRITICAL.

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

        This function is idempotent for the same ``name`` and ``log_file``: calling it
        repeatedly with identical arguments does not add duplicate handlers. If
        ``log_file`` changes for a given ``name``, the previous ``RotatingFileHandler``
        is removed and closed, and the new path takes effect.
    """
    # Resolve level from environment unless explicitly provided.
    effective_level = _resolve_log_level(level)

    # Create custom formatter with agent and thread information
    formatter = AgentFormatter()

    # Get or create logger instance
    _logger = logging.getLogger(name)

    # Determine log file path if not explicitly provided
    if log_file is None:
        log_file = _get_default_log_file(name)

    # Configure handler based on output destination
    if log_file:
        # File-based logging with rotation (100MB max size, 1 backup)
        file_handler = RotatingFileHandler(log_file, maxBytes=100000000, backupCount=1)
        file_handler.setFormatter(formatter)
        _ensure_handler(_logger, file_handler)
    else:
        # Console output
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        _ensure_handler(_logger, stream_handler)

    # Set logging level
    _logger.setLevel(effective_level)

    return _logger


def configure_root_logger(level=None):
    """
    Configure the Python root logger with the project-wide formatter and level.

    After calling this function, any logger obtained via ``logging.getLogger(__name__)``
    will inherit the root logger's handler and produce output in the TopsailAI format.

    Behavior:
        - If the environment variable ``TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG`` is set
          to ``"1"``, this function is a no-op and returns the root logger unchanged.
        - If ``level`` is ``None``, the level is resolved from the environment:
          ``TOPSAILAI_LOG_LEVEL`` takes precedence, then ``DEBUG=1`` enables
          ``logging.DEBUG``; otherwise ``logging.INFO`` is used.
        - The root logger's level is set only when it still has the default
          ``WARNING`` level (i.e. has not been explicitly configured by an external
          framework such as pytest, Django, or Flask). This avoids overriding an
          externally configured root logger.
        - Default **file** handlers (``RotatingFileHandler``) are added only when the
          root logger has no handlers. Logs are written to the folder returned by
          ``get_log_folder()``. The main log file is ``topsailai.log``; a secondary
          file with the ``.ec`` extension receives only ``ERROR`` and ``CRITICAL``
          messages so that failures can be located quickly.
        - Existing root handlers are left in place; if they have no formatter, the
          project ``AgentFormatter`` is applied.

    Args:
        level (int or str, optional): The logging level for the root logger.
            Defaults to ``None``, which resolves from environment variables.

    Returns:
        logging.Logger: The configured root logger instance.
    """
    root = logging.getLogger()

    if os.environ.get(ENV_DISABLE_ROOT_LOGGER_CONFIG) == "1":
        return root

    effective_level = _resolve_log_level(level)

    # Only configure level when the root logger has not been explicitly configured.
    # Python's default root level is WARNING; if an external framework has set a
    # different level, we leave it alone.
    if root.level == logging.WARNING:
        root.setLevel(effective_level)

    if not root.handlers:
        log_file = _get_default_log_file(ROOT_LOG_FILE_NAME)
        if log_file:
            handler = RotatingFileHandler(log_file, maxBytes=100000000, backupCount=1)
            handler.setFormatter(AgentFormatter(fmt=ROOT_LOG_FORMAT))
            root.addHandler(handler)

            # Separate handler for ERROR/CRITICAL messages.
            # This makes it easy to spot failures without scanning the full log.
            ec_log_file = log_file + ".ec"
            ec_handler = RotatingFileHandler(ec_log_file, maxBytes=100000000, backupCount=1)
            ec_handler.setLevel(logging.ERROR)
            ec_handler.setFormatter(AgentFormatter(fmt=ROOT_LOG_FORMAT))
            root.addHandler(ec_handler)
    else:
        # Ensure existing root handlers use AgentFormatter if they have no custom formatter.
        for handler in root.handlers:
            if handler.formatter is None:
                handler.setFormatter(AgentFormatter(fmt=ROOT_LOG_FORMAT))

    return root


# Configure the root logger when this module is imported so that standard
# ``logging.getLogger(__name__)`` loggers automatically use the project format.
# This can be disabled by setting ``TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG=1``.
configure_root_logger()
