"""Unit tests for logger.base_logger."""

import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

import pytest

from topsailai.logger.base_logger import (
    setup_logger,
    AgentFormatter,
    configure_root_logger,
    _resolve_log_level,
    _ensure_handler,
    get_log_folder,
    ENV_DISABLE_ROOT_LOGGER_CONFIG,
    ENV_LOG_LEVEL,
)


@pytest.fixture(autouse=True)
def cleanup_loggers():
    yield
    for name in list(logging.Logger.manager.loggerDict.keys()):
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)


@pytest.fixture
def mock_log_folder_exists():
    with patch("os.path.exists", return_value=True), patch("os.path.isdir", return_value=True):
        yield


@pytest.fixture
def mock_log_folder_not_exists():
    with patch("os.path.exists", return_value=False):
        yield


@pytest.fixture
def mock_agent_and_thread_names():
    with patch("topsailai.utils.thread_local_tool.get_agent_name", return_value=None), \
         patch("topsailai.utils.thread_local_tool.get_thread_name", return_value=None):
        yield


@pytest.fixture
def mock_agent_name():
    with patch("topsailai.utils.thread_local_tool.get_agent_name", return_value="TestAgent"):
        yield


@pytest.fixture
def mock_thread_name():
    with patch("topsailai.utils.thread_local_tool.get_thread_name", return_value="TestThread"):
        yield


@pytest.fixture
def clean_root_logger():
    root = logging.getLogger()
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)
    yield root
    for handler in root.handlers[:]:
        handler.close()
        root.removeHandler(handler)
    root.setLevel(logging.WARNING)


def test_setup_logger_with_name_only(mock_log_folder_exists):
    logger = setup_logger(name="test_logger")
    assert logger.name == "test_logger"
    assert len(logger.handlers) > 0
    # Default level is INFO unless DEBUG=1 or TOPSAILAI_LOG_LEVEL is set.
    assert logger.level == logging.INFO

def test_setup_logger_with_name_creates_file_handler(mock_log_folder_exists):
    logger = setup_logger(name="file_test_logger")
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) > 0
    assert file_handlers[0].baseFilename.endswith("file_test_logger.log")


def test_setup_logger_with_explicit_log_file(mock_log_folder_exists):
    explicit_path = "/tmp/custom_test.log"
    logger = setup_logger(name="explicit_test", log_file=explicit_path)
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) > 0
    assert file_handlers[0].baseFilename == explicit_path
def test_setup_logger_level_info(mock_log_folder_exists):
    logger = setup_logger(name="info_level_test", level=logging.INFO)
    assert logger.level == logging.INFO


def test_setup_logger_level_warning(mock_log_folder_exists):
    logger = setup_logger(name="warning_level_test", level=logging.WARNING)
    assert logger.level == logging.WARNING


def test_setup_logger_default_level_info(mock_log_folder_exists):
    logger = setup_logger(name="default_level_test")
    assert logger.level == logging.INFO

def test_setup_logger_formatter_is_agent_formatter(mock_log_folder_exists):
    logger = setup_logger(name="formatter_test")
    for handler in logger.handlers:
        assert isinstance(handler.formatter, AgentFormatter)


def test_rotating_file_handler_max_bytes(mock_log_folder_exists):
    logger = setup_logger(name="rotation_test")
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) > 0
    handler = file_handlers[0]
    assert handler.maxBytes == 100000000
    assert handler.backupCount == 1


def test_setup_logger_returns_logger_instance(mock_log_folder_exists):
    logger = setup_logger(name="return_type_test")
    assert isinstance(logger, logging.Logger)


def test_setup_logger_no_handler_duplication(mock_log_folder_exists):
    logger1 = setup_logger(name="dedup_test")
    handler_count_1 = len(logger1.handlers)
    logger2 = setup_logger(name="dedup_test")
    assert logger1 is logger2
    assert handler_count_1 == len(logger2.handlers)


def test_setup_logger_with_empty_string_name(mock_log_folder_not_exists):
    logger = setup_logger(name="", log_file=None)
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) > 0


def test_agent_formatter_format_without_agent(mock_agent_and_thread_names):
    formatter = AgentFormatter()
    record = logging.LogRecord("test", logging.INFO, "test.py", 1, "Test message", (), None)
    formatter.format(record)
    assert record.message_id == ""


def test_agent_formatter_format_with_agent_name(mock_agent_name):
    formatter = AgentFormatter()
    record = logging.LogRecord("test", logging.INFO, "test.py", 1, "Test message", (), None)
    formatter.format(record)
    assert "TestAgent" in record.message_id


def test_agent_formatter_format_with_thread_name(mock_thread_name):
    formatter = AgentFormatter()
    record = logging.LogRecord("test", logging.INFO, "test.py", 1, "Test message", (), None)
    formatter.format(record)
    assert "TestThread" in record.message_id


def test_agent_formatter_format_with_both_agent_and_thread(mock_agent_name, mock_thread_name):
    formatter = AgentFormatter()
    record = logging.LogRecord("test", logging.INFO, "test.py", 1, "Test message", (), None)
    formatter.format(record)
    assert record.message_id == "(TestAgent:TestThread)"


def test_agent_formatter_custom_format_string():
    formatter = AgentFormatter(fmt="%(levelname)s - %(message)s")
    record = logging.LogRecord("test", logging.WARNING, "test.py", 1, "Custom format test", (), None)
    formatted = formatter.format(record)
    assert "WARNING" in formatted
    assert "Custom format test" in formatted


def test_agent_formatter_custom_date_format():
    import re
    formatter = AgentFormatter(fmt="%(asctime)s %(message)s", datefmt="%Y-%m-%d")
    record = logging.LogRecord("test", logging.INFO, "test.py", 1, "Date format test", (), None)
    formatted = formatter.format(record)
    assert re.search(r"\d{4}-\d{2}-\d{2}", formatted)


def test_agent_formatter_fallback_to_env_variable(mock_agent_and_thread_names):
    with patch.dict(os.environ, {"AGENT_NAME": "EnvAgent", "AI_AGENT": ""}, clear=False):
        formatter = AgentFormatter()
        record = logging.LogRecord("test", logging.INFO, "test.py", 1, "Env test", (), None)
        formatter.format(record)
        assert "EnvAgent" in record.message_id


def test_agent_formatter_fallback_to_ai_agent_env(mock_agent_and_thread_names):
    with patch.dict(os.environ, {"AGENT_NAME": "", "AI_AGENT": "AIAgent"}, clear=False):
        formatter = AgentFormatter()
        record = logging.LogRecord("test", logging.INFO, "test.py", 1, "AI_AGENT test", (), None)
        formatter.format(record)
        assert "AIAgent" in record.message_id


def test_full_logging_pipeline_integration(mock_log_folder_exists, mock_agent_and_thread_names, tmp_path):
    log_file = str(tmp_path / "integration_test.log")
    logger = setup_logger(name="integration_test", log_file=log_file)
    test_message = "Integration test message"
    logger.info(test_message)
    for handler in logger.handlers:
        handler.flush()
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            assert test_message in f.read()


def test_logger_propagation_to_root(mock_log_folder_exists):
    logger = setup_logger(name="propagation_test")
    assert logger.propagate is True


def test_multiple_handlers_with_different_levels(mock_log_folder_exists):
    logger = setup_logger(name="multi_handler_test")
    additional_handler = logging.StreamHandler()
    additional_handler.setLevel(logging.ERROR)
    logger.addHandler(additional_handler)
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) >= 2


def _run_in_subprocess(code: str, env: dict = None) -> subprocess.CompletedProcess:
    """Run Python code in a subprocess to isolate root logger state from pytest."""
    environment = os.environ.copy()
    if env:
        environment.update(env)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd="/TopsailAI/src/topsailai",
        env=environment,
    )


def test_configure_root_logger_adds_file_handler():
    code = """
import logging
import os
import tempfile
from topsailai.logger.base_logger import configure_root_logger, AgentFormatter, ROOT_LOG_FILE_NAME, ROOT_LOG_FORMAT
from topsailai.logger.base_logger import get_log_folder

root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["TOPSAILAI_HOME"] = tmp
    configure_root_logger(level=logging.INFO)
    file_handlers = [h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    assert len(file_handlers) == 2, f"expected two RotatingFileHandlers, got {len(file_handlers)}"

    main_handler = file_handlers[0]
    assert isinstance(main_handler.formatter, AgentFormatter), "expected AgentFormatter on main handler"
    assert main_handler.formatter._fmt == ROOT_LOG_FORMAT, f"expected {ROOT_LOG_FORMAT!r}, got {main_handler.formatter._fmt!r}"
    expected_main_path = os.path.join(get_log_folder(), ROOT_LOG_FILE_NAME + ".log")
    assert main_handler.baseFilename == expected_main_path, f"expected {expected_main_path}, got {main_handler.baseFilename}"

    ec_handler = file_handlers[1]
    assert isinstance(ec_handler.formatter, AgentFormatter), "expected AgentFormatter on .ec handler"
    assert ec_handler.formatter._fmt == ROOT_LOG_FORMAT, f"expected {ROOT_LOG_FORMAT!r}, got {ec_handler.formatter._fmt!r}"
    expected_ec_path = expected_main_path + ".ec"
    assert ec_handler.baseFilename == expected_ec_path, f"expected {expected_ec_path}, got {ec_handler.baseFilename}"
    assert ec_handler.level == logging.ERROR, f"expected ERROR level, got {ec_handler.level}"

    assert root.level == logging.INFO, f"expected INFO, got {root.level}"
print("ok")
"""
    result = _run_in_subprocess(code)
    assert result.returncode == 0, result.stderr or result.stdout


def test_standard_getlogger_inherits_root_format():
    code = """
import logging
from topsailai.logger.base_logger import configure_root_logger, AgentFormatter
root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)
configure_root_logger(level=logging.INFO)
std_logger = logging.getLogger("standard.test.module")
std_logger.setLevel(logging.DEBUG)
assert std_logger.level == logging.DEBUG
assert root.level == logging.INFO
print("ok")
"""
    result = _run_in_subprocess(code)
    assert result.returncode == 0, result.stderr or result.stdout


def test_configure_root_logger_default_is_info():
    code = """
import logging
from topsailai.logger.base_logger import configure_root_logger
root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)
configure_root_logger()
assert root.level == logging.INFO, f"expected INFO, got {root.level}"
print("ok")
"""
    result = _run_in_subprocess(code, env={"DEBUG": "0"})
    assert result.returncode == 0, result.stderr or result.stdout


def test_configure_root_logger_debug_env():
    code = """
import logging
import os
from topsailai.logger.base_logger import configure_root_logger
# The project loads .env on import, which may set TOPSAILAI_LOG_LEVEL.
# For this test we want DEBUG=1 to be the active signal, so clear any
# externally configured log level before resolving the level.
os.environ.pop("TOPSAILAI_LOG_LEVEL", None)
root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)
configure_root_logger()
assert root.level == logging.DEBUG, f"expected DEBUG, got {root.level}"
print("ok")
"""
    result = _run_in_subprocess(code, env={"DEBUG": "1"})
    assert result.returncode == 0, result.stderr or result.stdout


def test_configure_root_logger_respects_external_config(clean_root_logger):
    clean_root_logger.setLevel(logging.ERROR)
    external_handler = logging.StreamHandler()
    external_handler.setLevel(logging.ERROR)
    clean_root_logger.addHandler(external_handler)
    configure_root_logger(level=logging.INFO)
    assert clean_root_logger.level == logging.ERROR
    assert external_handler in clean_root_logger.handlers


def test_configure_root_logger_no_third_party_flood():
    code = """
import logging
import io
from topsailai.logger.base_logger import configure_root_logger
root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)
configure_root_logger()
# Capture everything the root handler would emit.
captured = io.StringIO()
root.handlers[0].stream = captured
# Simulate a third-party library that does not set its own level and therefore
# inherits the root logger's level. With the root at INFO, DEBUG records must
# not be emitted, while INFO/WARNING records are.
third_party = logging.getLogger("third_party_lib")
third_party.debug("third party debug message")
third_party.info("third party info message")
third_party.warning("third party warning message")
assert root.level == logging.INFO, f"expected root INFO, got {root.level}"
output = captured.getvalue()
assert "third party debug message" not in output, "third party DEBUG should not be emitted"
assert "third party info message" in output, "third party INFO should be emitted"
assert "third party warning message" in output, "third party WARNING should be emitted"
print("ok")
"""
    result = _run_in_subprocess(code, env={"DEBUG": "0"})
    assert result.returncode == 0, result.stderr or result.stdout


def test_setup_logger_creates_missing_log_folder(tmp_path):
    log_folder = tmp_path / "missing_log_folder"
    assert not log_folder.exists()
    with patch("topsailai.logger.base_logger.get_log_folder", return_value=str(log_folder) + "/"):
        logger = setup_logger(name="missing_folder_test")
    assert log_folder.exists()
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename.startswith(str(log_folder))


def test_setup_logger_raises_when_log_folder_not_creatable(tmp_path):
    parent_file = tmp_path / "not_a_directory"
    parent_file.write_text("I am a file")
    impossible_folder = parent_file / "log_folder"
    with patch("topsailai.logger.base_logger.get_log_folder", return_value=str(impossible_folder) + "/"):
        with pytest.raises(RuntimeError):
            setup_logger(name="cannot_create_test")


def test_setup_logger_replaces_different_log_file(tmp_path):
    first_path = str(tmp_path / "first.log")
    second_path = str(tmp_path / "second.log")
    logger1 = setup_logger(name="replace_test", log_file=first_path)
    file_handlers_1 = [h for h in logger1.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers_1) == 1
    assert file_handlers_1[0].baseFilename == first_path
    logger2 = setup_logger(name="replace_test", log_file=second_path)
    assert logger1 is logger2
    file_handlers_2 = [h for h in logger2.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers_2) == 1
    assert file_handlers_2[0].baseFilename == second_path


def test_disable_root_logger_config_env_var():
    code = """
import logging
import os
os.environ["TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG"] = "1"
# Importing topsailai.logger.base_logger must not configure the root logger.
from topsailai.logger.base_logger import configure_root_logger
root = logging.getLogger()
# The module import should not have added handlers. If something else added a
# handler (e.g. another import), remove it so we can verify our function is a no-op.
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)
configure_root_logger()
assert len(root.handlers) == 0, f"expected 0 handlers, got {len(root.handlers)}"
assert root.level == logging.WARNING, f"expected WARNING, got {root.level}"
print("ok")
"""
    result = _run_in_subprocess(code)
    assert result.returncode == 0, result.stderr or result.stdout


def test_setup_logger_respects_log_level_env_warning(mock_log_folder_exists):
    with patch.dict(os.environ, {"TOPSAILAI_LOG_LEVEL": "WARNING"}, clear=False):
        logger = setup_logger(name="env_warning_test")
    assert logger.level == logging.WARNING


def test_setup_logger_debug_env_sets_debug_level(mock_log_folder_exists):
    with patch.dict(os.environ, {"DEBUG": "1"}, clear=False):
        logger = setup_logger(name="env_debug_test")
    assert logger.level == logging.DEBUG


def test_configure_root_logger_respects_log_level_env_warning():
    code = """
import logging
import os
import tempfile
from topsailai.logger.base_logger import configure_root_logger

root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["TOPSAILAI_HOME"] = tmp
    os.environ["TOPSAILAI_LOG_LEVEL"] = "WARNING"
    configure_root_logger()
    assert root.level == logging.WARNING, f"expected WARNING, got {root.level}"
print("ok")
"""
    result = _run_in_subprocess(code, env={"DEBUG": "0"})
    assert result.returncode == 0, result.stderr or result.stdout


def test_configure_root_logger_no_stdout_output():
    code = """
import logging
import os
import sys
import tempfile
from topsailai.logger.base_logger import configure_root_logger

root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["TOPSAILAI_HOME"] = tmp
    configure_root_logger(level=logging.INFO)
    # Redirect stdout/stderr to capture any console output.
    old_stdout, old_stderr = sys.stdout, sys.stderr
    captured_stdout = []
    captured_stderr = []
    class Capture:
        def __init__(self, buf):
            self.buf = buf
        def write(self, text):
            self.buf.append(text)
        def flush(self):
            pass
    sys.stdout = Capture(captured_stdout)
    sys.stderr = Capture(captured_stderr)
    try:
        logger = logging.getLogger("stdout.test")
        logger.info("this should not appear on stdout or stderr")
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

stdout_text = "".join(captured_stdout)
stderr_text = "".join(captured_stderr)
assert "this should not appear" not in stdout_text, f"unexpected stdout: {stdout_text!r}"
assert "this should not appear" not in stderr_text, f"unexpected stderr: {stderr_text!r}"
print("ok")
"""
    result = _run_in_subprocess(code)
    assert result.returncode == 0, result.stderr or result.stdout


def test_configure_root_logger_writes_to_file():
    code = """
import logging
import os
import tempfile
from topsailai.logger.base_logger import configure_root_logger

root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["TOPSAILAI_HOME"] = tmp
    configure_root_logger(level=logging.INFO)
    logger = logging.getLogger("file.test")
    logger.info("hello from file test")
    for h in root.handlers:
        h.flush()
    log_file = root.handlers[0].baseFilename
    assert os.path.exists(log_file), f"log file not found: {log_file}"
    with open(log_file, "r") as f:
        content = f.read()
    assert "hello from file test" in content, f"message not in log file: {content!r}"
print("ok")
"""
    result = _run_in_subprocess(code)
    assert result.returncode == 0, result.stderr or result.stdout



def test_resolve_log_level_invalid_env_falls_back_to_info():
    with patch.dict(os.environ, {ENV_LOG_LEVEL: "NOT_A_LEVEL"}, clear=False):
        assert _resolve_log_level(None) == logging.INFO


def test_resolve_log_level_numeric_env():
    with patch.dict(os.environ, {ENV_LOG_LEVEL: "25"}, clear=False):
        assert _resolve_log_level(None) == 25


def test_get_log_folder_fallback_when_import_fails():
    code = """
import logging
from topsailai.logger.base_logger import get_log_folder

# The module is already imported; patch the cached module so the next
# import inside get_log_folder raises ImportError and triggers fallback.
import sys
sys.modules["topsailai.workspace.folder_constants"] = None
try:
    folder = get_log_folder()
    print(folder)
except Exception as e:
    print(f"ERROR: {e}")
"""
    result = _run_in_subprocess(code)
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip() == "/topsailai/log/"


def test_ensure_handler_closes_duplicate_non_file_handler(mock_log_folder_exists):
    logger = logging.getLogger("ensure_handler_non_file_test")
    for h in logger.handlers[:]:
        h.close()
        logger.removeHandler(h)
    first = logging.StreamHandler()
    logger.addHandler(first)
    second = logging.StreamHandler()
    _ensure_handler(logger, second)
    assert len(logger.handlers) == 1
    assert logger.handlers[0] is first


def test_configure_root_logger_disabled_in_subprocess():
    code = """
import logging
import os
from topsailai.logger.base_logger import configure_root_logger, ENV_DISABLE_ROOT_LOGGER_CONFIG

os.environ[ENV_DISABLE_ROOT_LOGGER_CONFIG] = "1"
root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)

configure_root_logger(level=logging.INFO)

print(root.level)
print(len(root.handlers))
"""
    result = _run_in_subprocess(code)
    assert result.returncode == 0, result.stderr or result.stdout
    lines = result.stdout.strip().splitlines()
    assert lines[-2] == str(logging.WARNING)
    assert lines[-1] == "0"


def test_configure_root_logger_adds_file_handler_in_subprocess():
    code = """
import logging
import os
import tempfile
from logging.handlers import RotatingFileHandler
from topsailai.logger.base_logger import configure_root_logger

root = logging.getLogger()
for h in root.handlers[:]:
    root.removeHandler(h)
root.setLevel(logging.WARNING)

with tempfile.TemporaryDirectory() as tmp:
    os.environ["TOPSAILAI_HOME"] = tmp
    configure_root_logger(level=logging.INFO)
    print(root.level)
    print(len(root.handlers))
    main_handler = root.handlers[0]
    ec_handler = root.handlers[1]
    print(isinstance(main_handler, RotatingFileHandler))
    print(main_handler.baseFilename.endswith("topsailai.log"))
    print(isinstance(ec_handler, RotatingFileHandler))
    print(ec_handler.baseFilename.endswith("topsailai.log.ec"))
    print(ec_handler.level == logging.ERROR)
"""
    result = _run_in_subprocess(code)
    assert result.returncode == 0, result.stderr or result.stdout
    lines = result.stdout.strip().splitlines()
    assert lines[-7] == str(logging.INFO)
    assert lines[-6] == "2"
    assert lines[-5] == "True"
    assert lines[-4] == "True"
    assert lines[-3] == "True"
    assert lines[-2] == "True"
    assert lines[-1] == "True"
