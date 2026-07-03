"""Message/session retrieval helpers for the TopsailAI CLI."""

import json
import os
import subprocess
from typing import Any, Dict, List, Optional

from cli_topsailai.colors import Colors, print_error, print_info
from cli_topsailai.constants import DEFAULT_LIMIT
from cli_topsailai.formatting import print_header
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.process import register_process, unregister_process

def load_session_index(sessions_dir: Optional[str] = None) -> Dict[str, Any]:
    """Load the session index JSON file."""
    if sessions_dir is None:
        sessions_dir = os.path.join(get_topsailai_home(), "sessions")
    index_path = os.path.join(sessions_dir, "index.json")
    if not os.path.isfile(index_path):
        return {}
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def save_session_index(
    index: Dict[str, Any], sessions_dir: Optional[str] = None
) -> None:
    """Save the session index JSON file."""
    if sessions_dir is None:
        sessions_dir = os.path.join(get_topsailai_home(), "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    index_path = os.path.join(sessions_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=2, ensure_ascii=False)


def list_sessions(
    sessions_dir: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    List sessions from the session index.

    Args:
        sessions_dir: Directory containing session files.
        limit: Maximum number of sessions to return.
        offset: Number of sessions to skip.

    Returns:
        List of session metadata dictionaries.
    """
    index = load_session_index(sessions_dir)
    sessions = list(index.values())
    sessions.sort(key=lambda s: s.get("update_at_ms", 0), reverse=True)
    return sessions[offset : offset + limit]


def get_session_messages(
    session_id: str,
    sessions_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve messages for a session.

    Args:
        session_id: Session identifier.
        sessions_dir: Directory containing session files.

    Returns:
        List of message dictionaries.
    """
    if sessions_dir is None:
        sessions_dir = os.path.join(get_topsailai_home(), "sessions")
    messages_path = os.path.join(sessions_dir, f"{session_id}.json")
    if not os.path.isfile(messages_path):
        return []
    try:
        with open(messages_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("messages", [])
        return []
    except (json.JSONDecodeError, OSError):
        return []


def print_messages(messages: List[Dict[str, Any]], raw: bool = False) -> None:
    """Print messages in human-readable or raw JSON form."""
    if raw:
        print(json.dumps(messages, indent=2, ensure_ascii=False))
        return
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        print_info(f"[{role}]")
        print(content)


def retrieve_session(session_id: str) -> None:
    """
    Retrieve session content via the ``topsailai_retrieve_messages`` command.

    The subprocess is tracked and will be cleaned up on script exit.

    Args:
        session_id: Session identifier to retrieve.
    """
    print_header(f"Session Content: {session_id}")
    proc = None
    try:
        proc = subprocess.Popen(
            ["topsailai_retrieve_messages", session_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        register_process(proc)
        stdout, stderr = proc.communicate(timeout=30)
        if proc.returncode == 0:
            print(f"{Colors.WHITE}{stdout}{Colors.RESET}")
        else:
            print(
                f"{Colors.RED}[ERROR] topsailai_retrieve_messages failed: "
                f"{stderr.strip()}{Colors.RESET}"
            )
    except FileNotFoundError:
        print(
            f"{Colors.RED}[ERROR] Command 'topsailai_retrieve_messages' not found. "
            f"Please ensure it is installed and in PATH.{Colors.RESET}"
        )
    except subprocess.TimeoutExpired:
        print(f"{Colors.RED}[ERROR] Command timed out after 30s.{Colors.RESET}")
        if proc and proc.poll() is None:
            proc.kill()
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to retrieve session: {e}{Colors.RESET}")
    finally:
        if proc:
            unregister_process(proc)
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
