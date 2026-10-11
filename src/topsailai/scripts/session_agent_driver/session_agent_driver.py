#!/usr/bin/env python3
"""
Session Agent Driver: periodically check a target session and drive it.

The script enters a polling loop and checks the target session status:

- ``input``: the session process is alive and holds its session pipe (waiting
  for input). The script starts an analysis agent (times=1) that inspects the
  session context and either injects suggested input via the ``inject_input``
  plugin tool or requests exit via the ``exit_process`` plugin tool.
- ``running``: the session process is alive but not waiting for input. The
  script waits for the next poll.
- ``idle``: the session process has exited. The script exits its loop.

When ``inject_input`` fails, the tool raises ``AgentEndProcess`` so the
analysis agent shuts down completely and the script continues polling.

Author: DawsonLin
"""

import argparse
import logging
import os
import signal
import string
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPT_ENV_FILE = SCRIPT_DIR / (Path(__file__).stem + ".env")
PROMPT_TEMPLATE_FILE = SCRIPT_DIR / "prompts" / "analysis_prompt.md"

POLL_INTERVAL_ENV = "TOPSAILAI_SESSION_DRIVER_POLL_INTERVAL"
TIMEOUT_ENV = "TOPSAILAI_SESSION_DRIVER_TIMEOUT"
TASK_GOAL_ENV = "TOPSAILAI_SESSION_DRIVER_TASK_GOAL"
SESSION_ID_ENV = "TOPSAILAI_SESSION_ID"
PLUGIN_TOOLS_ENV = "TOPSAILAI_PLUGIN_TOOLS"
PLUGIN_SKILLS_ENV = "TOPSAILAI_PLUGIN_SKILLS"
DEFAULT_POLL_INTERVAL = 5
DEFAULT_TIMEOUT = 120
LOG_TAIL_LINES = 100
MESSAGES_SUMMARY_MAX_CHARS = 8000
MESSAGES_SUMMARY_MAX_ITEMS = 20
ANALYSIS_SESSION_PREFIX = "session_agent_driver_"

DEFAULT_PROMPT = """# Session Analysis Task

You are the analysis agent of the Session Agent Driver. Inspect the target
session and decide what input it needs.

## Target Session Information
- session_id: $session_id
- pid: $pid
- status: $status
- project_workspace: $project_workspace
- created_at: $created_at

## Task Goal
$task_goal

## Session Messages Summary
$messages_summary

## Session Log Tail
$log_tail

## Instructions
1. If the session is waiting for input and needs more input to make progress,
   call inject_input with the suggested input content.
2. If the session has achieved its final goal and no further input is needed,
   call exit_process.
3. If the session is still running (not waiting for input), do nothing and
   report the current state.
4. Do not call agent_tool or start any nested agent.
5. Keep your final answer concise: state what you decided and why.
"""


def _load_script_env(env_file: Path = SCRIPT_ENV_FILE) -> None:
    """Load the script-specific dotenv file without overriding process values."""
    if not env_file.is_file():
        return
    try:
        load_dotenv(env_file, override=False)
    except Exception as error:  # noqa: BLE001 - a broken env file must not kill the script
        logger.warning("failed to load script environment file %s: %s", env_file, error)


def _configure_noninteractive_agent() -> None:
    """Disable interaction and preserve additional configured tool exclusions."""
    os.environ["TOPSAILAI_INTERACTIVE_MODE"] = "0"
    name = "TOPSAILAI_CLI_AGENT_CHAT_DISABLED_TOOLS"
    excluded = [item.strip() for item in os.environ.get(name, "").split(";")]
    excluded = [item for item in excluded if item]
    for tool in ("agent_tool", "human_tool"):
        if tool not in excluded:
            excluded.append(tool)
    os.environ[name] = ";".join(excluded)


_load_script_env()
_configure_noninteractive_agent()

# P1: plugin tools and skills MUST be configured before importing topsailai,
# because tools/base/__init__.py runs expand_plugin_tools() at import time.
os.environ.setdefault(PLUGIN_TOOLS_ENV, "plugins.tools")
os.environ.setdefault(
    PLUGIN_SKILLS_ENV,
    str(SCRIPT_DIR / "plugins" / "skills"),
)

SRC_DIR = str(SCRIPT_DIR.parent.parent.parent)  # /TopsailAI/src/
PROJECT_DIR = str(SCRIPT_DIR.parent.parent)  # /TopsailAI/src/topsailai/
CLI_DIR = str(SCRIPT_DIR.parent.parent / "cli")  # /TopsailAI/src/topsailai/cli/
for _path in (SRC_DIR, PROJECT_DIR, CLI_DIR, str(SCRIPT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from topsailai.context import ctx_manager  # noqa: E402
from topsailai.workspace.agent_shell import get_agent_chat  # noqa: E402
from ai_base.agent_types.exception import AgentEndProcess  # noqa: E402
from cli_topsailai.log_files import discover_log_files, is_session_pipe_open  # noqa: E402
from cli_topsailai.paths import get_topsailai_home  # noqa: E402
from cli_topsailai.runtime_logs import resolve_log_target, read_log_tail  # noqa: E402
from plugins.tools import exit_process  # noqa: E402


class _AnalysisTimeout(Exception):
    """Raised when a single analysis run exceeds the configured timeout."""


def _timeout_handler(signum, frame):  # noqa: ARG001 - signal handler signature
    """Raise the analysis timeout from the SIGALRM handler."""
    raise _AnalysisTimeout("analysis agent timed out")


def _read_int_env(name: str, default: int) -> int:
    """Read an integer environment variable with a safe fallback."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _task_dir() -> Path:
    """Return the task directory where session pipes and logs live."""
    return Path(get_topsailai_home()) / "workspace" / "task"


def _is_pid_alive(pid) -> bool:
    """Return whether the process with *pid* is alive (signal zero probe)."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _session_records(session_id: str) -> list:
    """Return non-task log records for the target session (ctime ascending)."""
    try:
        log_files = discover_log_files(str(_task_dir()))
    except Exception as error:  # noqa: BLE001
        logger.error("failed to discover log files: %s", error)
        return []
    return [
        item for item in log_files
        if item.get("session_id") == session_id and not item.get("is_task")
    ]


def _current_record(session_id: str):
    """Select the current active record: living pid, newest ctime wins (P6)."""
    records = _session_records(session_id)
    alive = [item for item in records if _is_pid_alive(item.get("pid"))]
    if not alive:
        return None
    alive.sort(key=lambda item: item.get("ctime", 0), reverse=True)
    return alive[0]


def check_session_status(session_id: str) -> str:
    """Return the workspace-scope status: input / running / idle."""
    record = _current_record(session_id)
    if record is None:
        return "idle"
    if is_session_pipe_open(record):
        return "input"
    return "running"


def format_messages_summary(messages) -> str:
    """Format recent session messages into a bounded text summary."""
    if not messages:
        return "(no messages)"
    lines = []
    for message in messages[-MESSAGES_SUMMARY_MAX_ITEMS:]:
        role = message.get("role", "?")
        content = message.get("content", "")
        if isinstance(content, str):
            content = content.replace("\n", " ")[:500]
        lines.append(f"[{role}] {content}")
    summary = "\n".join(lines)
    if len(summary) > MESSAGES_SUMMARY_MAX_CHARS:
        summary = summary[:MESSAGES_SUMMARY_MAX_CHARS] + "\n...(truncated)"
    return summary


def get_session_info(session_id: str) -> dict | None:
    """Collect session information through topsailai; None on failure (P13)."""
    record = _current_record(session_id)
    if record is None:
        logger.info("session %s has no living process", session_id)
        return None
    pid = record.get("pid")
    status = check_session_status(session_id)

    log_tail = "(log unavailable)"
    try:
        target = resolve_log_target(_task_dir(), session_id=session_id, pid=pid)
        tail = read_log_tail(target, count=LOG_TAIL_LINES)
        log_tail = "\n".join(tail.lines)
    except Exception as error:  # noqa: BLE001
        log_tail = f"(log unavailable: {error})"

    messages_summary = "(messages unavailable)"
    try:
        manager = ctx_manager.get_session_manager()
        messages = manager.retrieve_messages(session_id)
        messages_summary = format_messages_summary(messages)
    except Exception as error:  # noqa: BLE001
        logger.warning("failed to retrieve messages for %s: %s", session_id, error)

    return {
        "session_id": session_id,
        "pid": pid,
        "status": status,
        "project_workspace": os.environ.get("TOPSAILAI_PROJECT_WORKSPACE", ""),
        "created_at": record.get("ctime", ""),
        "task_goal": os.environ.get(
            TASK_GOAL_ENV, "Drive the target session to completion."
        ),
        "messages_summary": messages_summary,
        "log_tail": log_tail,
    }


def render_analysis_prompt(session_info: dict) -> str:
    """Render the prompt template with session info (string.Template, P12)."""
    template_text = DEFAULT_PROMPT
    try:
        if PROMPT_TEMPLATE_FILE.is_file():
            template_text = PROMPT_TEMPLATE_FILE.read_text(encoding="utf-8")
    except Exception as error:  # noqa: BLE001
        logger.warning("failed to read prompt template %s: %s", PROMPT_TEMPLATE_FILE, error)
    try:
        return string.Template(template_text).safe_substitute(**session_info)
    except Exception as error:  # noqa: BLE001
        logger.warning("failed to render prompt template: %s", error)
        return string.Template(DEFAULT_PROMPT).safe_substitute(**session_info)


def cleanup_analysis_session(session_id: str) -> None:
    """Delete the analysis session data (P8: data lifecycle management)."""
    try:
        manager = ctx_manager.get_session_manager()
        if manager and manager.exists_session(session_id):
            manager.delete_session(session_id)
            logger.info("cleaned analysis session %s", session_id)
    except Exception as error:  # noqa: BLE001
        logger.warning("failed to clean analysis session %s: %s", session_id, error)


def run_analysis_agent(session_id: str) -> None:
    """Start the analysis agent (times=1) to drive the target session."""
    # P9: re-check the status right before starting the analysis agent.
    if check_session_status(session_id) != "input":
        logger.info("session %s is no longer input, skip analysis", session_id)
        return
    session_info = get_session_info(session_id)
    if session_info is None:
        return
    prompt = render_analysis_prompt(session_info)
    analysis_session_id = ANALYSIS_SESSION_PREFIX + uuid.uuid4().hex
    timeout = _read_int_env(TIMEOUT_ENV, DEFAULT_TIMEOUT)
    logger.info(
        "starting analysis agent %s for session %s (status=%s)",
        analysis_session_id, session_id, session_info["status"],
    )
    try:
        # P15: isolate the driver argv from the analysis agent. get_message()
        # reads sys.argv[1:] and would otherwise prepend the driver CLI args
        # (e.g. "-s <session> --poll-interval 5") to the analysis prompt.
        saved_argv = sys.argv
        sys.argv = [saved_argv[0]]
        try:
            agent_chat = get_agent_chat(
                session_id=analysis_session_id,
                message=prompt,
                disabled_tools=["agent_tool", "human_tool"],
                need_project_workspace_lock=False,  # P2: avoid lock contention
                need_input_message=False,
            )
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(timeout)
            try:
                agent_chat.run(times=1, need_interactive=False)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        finally:
            sys.argv = saved_argv
    except AgentEndProcess as error:
        # P14: injection failed -> analysis agent aborted; keep polling.
        logger.warning("analysis agent aborted: %s", error)
    except _AnalysisTimeout as error:
        logger.error("analysis agent timed out: %s", error)
    except Exception as error:  # noqa: BLE001 - P7: never crash the loop
        logger.error("analysis agent failed: %s", error)
    finally:
        cleanup_analysis_session(analysis_session_id)


def _parse_args(argv=None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="session_agent_driver",
        description="Periodically check a target session and drive it with input.",
    )
    parser.add_argument(
        "-s", "--session", dest="session_id",
        help="target session id (or set %s)" % SESSION_ID_ENV,
    )
    parser.add_argument(
        "--poll-interval", type=int, default=None,
        help="poll interval in seconds (default: %s)" % DEFAULT_POLL_INTERVAL,
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help="single analysis timeout in seconds (default: %s)" % DEFAULT_TIMEOUT,
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    """Run the session agent driver polling loop."""
    args = _parse_args(argv)
    session_id = args.session_id or os.environ.get(SESSION_ID_ENV)
    if not session_id:
        print(
            "error: target session id is required (--session or %s)" % SESSION_ID_ENV,
            file=sys.stderr,
        )
        return 2

    poll_interval = args.poll_interval
    if poll_interval is None:
        poll_interval = _read_int_env(POLL_INTERVAL_ENV, DEFAULT_POLL_INTERVAL)
    if poll_interval <= 0:
        poll_interval = DEFAULT_POLL_INTERVAL

    exit_process.reset_exit_flag()
    logger.info(
        "session agent driver started: session=%s poll_interval=%ss",
        session_id, poll_interval,
    )

    def _on_signal(signum, frame):  # noqa: ARG001
        """Exit gracefully on SIGINT/SIGTERM."""
        logger.info("received signal %s, exiting", signum)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    while not exit_process.is_exit_requested():
        try:
            status = check_session_status(session_id)
            logger.info("session %s status: %s", session_id, status)
            if status == "idle":
                logger.info("session %s is idle (process exited), driver exits", session_id)
                break
            if status == "input":
                run_analysis_agent(session_id)
            else:
                logger.debug("session %s is running, waiting", session_id)
        except SystemExit:
            raise
        except Exception as error:  # noqa: BLE001 - P7: keep the loop alive
            logger.error("polling loop error: %s", error)
        time.sleep(poll_interval)

    logger.info("session agent driver exiting")
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(main())
