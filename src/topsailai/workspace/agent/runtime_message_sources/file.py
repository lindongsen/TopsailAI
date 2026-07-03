import atexit
import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from topsailai.ai_base.agent2llm_message_source import Agent2LLMMessageSource
from topsailai.ai_base.constants import ROLE_USER, STEP_NAME_OBSERVATION
from topsailai.utils import env_tool
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK

logger = logging.getLogger(__name__)


def _now_iso_ts() -> str:
    """Return the current UTC time as an ISO 8601 timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def get_default_inject_message_file_path(session_id: str | None = None) -> str:
    """Return the default session-scoped path for the file message source.

    The path follows the same convention as the session stdout tee file and
    input pipe so concurrent processes do not collide:
    ``{FOLDER_WORKSPACE_TASK}/{session_id}.{pid}.session.agent2llm_inject_messages.jsonl``.

    Args:
        session_id: Optional session ID. When omitted or empty, falls back to
            ``env_tool.get_session_id() or "topsailai"``.

    Returns:
        Absolute path to the default inject message file.
    """
    if not session_id:
        session_id = env_tool.get_session_id() or "topsailai"
    return os.path.join(
        FOLDER_WORKSPACE_TASK,
        f"{session_id}.{os.getpid()}.session.agent2llm_inject_messages.jsonl",
    )


def write_message(
    file_path: str,
    content: str | dict,
    role: str = ROLE_USER,
    step_name: str = STEP_NAME_OBSERVATION,
) -> bool:
    """Append a runtime message to the JSONL inject file.

    Supports both simple and structured content formats:

    * If ``content`` is a string, it is wrapped into the structured format
      using ``Agent2LLMMessageSource.build_message``.
    * If ``content`` is a dict, it is written as-is, allowing callers to
      inject pre-structured messages.

    A top-level ``ts`` field containing an ISO 8601 UTC creation timestamp is
    added to every JSONL line. This field is for representation/logging only
    and is stripped by the consumer before the message is injected into the
    Agent2LLM context.

    Args:
        file_path: Path to the JSONL file.
        content: Message payload (string or dict).
        role: Message role. Defaults to ``ROLE_USER``.
        step_name: Value for ``step_name`` when wrapping string content.
            Defaults to ``STEP_NAME_OBSERVATION``.

    Returns:
        bool: ``True`` if the message was appended successfully.
    """
    if isinstance(content, dict):
        msg = {"role": role, "content": content}
    else:
        msg = Agent2LLMMessageSource.build_message(
            content, role=role, step_name=step_name
        )

    msg["ts"] = _now_iso_ts()

    parent_dir = os.path.dirname(file_path)
    if parent_dir and not os.path.exists(parent_dir):
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except Exception as e:
            logger.exception(
                "failed to create inject message directory [%s]: %s", parent_dir, e
            )
            return False

    try:
        with open(file_path, "a", encoding="utf-8") as fd:
            fd.write(json.dumps(msg, ensure_ascii=False) + "\n")
            fd.flush()
            os.fsync(fd.fileno())
        return True
    except Exception as e:
        logger.exception("failed to write inject message to [%s]: %s", file_path, e)
        return False


class FileAgent2LLMMessageSource(Agent2LLMMessageSource):
    """Read runtime messages from a JSONL file.

    The file is expected to contain one JSON object per line. Each object
    should have ``role`` and ``content`` keys. After a successful read the
    file is cleared so messages are not injected twice.

    Warning:
        Concurrent writes between the read and the clear can be lost. External
        writers should write to a temporary file and atomically rename it into
        the target path.
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._last_digest = None
        # Register cleanup so the inject file is removed when the process
        # exits. This avoids leaving stale JSONL files behind after each run.
        atexit.register(self._delete_file_on_exit)

    def _delete_file_on_exit(self):
        """Delete the inject file if it exists. Called via atexit."""
        if self.file_path and os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
                logger.debug("removed inject message file on exit [%s]", self.file_path)
            except Exception as e:
                logger.warning(
                    "failed to remove inject message file on exit [%s]: %s",
                    self.file_path,
                    e,
                )

    def produce_message(
        self,
        content: str | dict,
        role: str = ROLE_USER,
        step_name: str = STEP_NAME_OBSERVATION,
    ) -> bool:
        """Append a runtime message to the JSONL inject file.

        Supports both simple and structured content formats:

        * If ``content`` is a string, it is wrapped into the structured format.
        * If ``content`` is a dict, it is written as-is.

        Args:
            content: Message payload (string or dict).
            role: Message role. Defaults to ``ROLE_USER``.
            step_name: Value for ``step_name`` when wrapping string content.
                Defaults to ``STEP_NAME_OBSERVATION``.

        Returns:
            bool: ``True`` if the message was appended successfully.
        """
        return write_message(self.file_path, content, role=role, step_name=step_name)

    def consume_messages(self) -> list[dict]:
        """Read, parse, and clear the file; return parsed messages."""
        if not self.file_path or not os.path.exists(self.file_path):
            return []

        try:
            with open(self.file_path, "r", encoding="utf-8") as fd:
                raw = fd.read()
        except Exception as e:
            logger.exception("failed to read inject message file [%s]: %s", self.file_path, e)
            return []

        if not raw.strip():
            return []

        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if digest == self._last_digest:
            logger.warning("detected duplicate inject payload, skip injection")
            # Ensure the file is still cleared even when we skip injection,
            # so a stale payload is not re-evaluated on every loop.
            self._clear_file()
            return []

        messages = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if isinstance(msg, dict):
                    messages.append(msg)
                else:
                    logger.warning("skip non-dict inject message line: %s", line)
            except json.JSONDecodeError:
                logger.warning("skip invalid JSONL inject message line: %s", line)

        # Clear the file after consuming the payload. If clearing fails, do not
        # inject anything; otherwise the same messages would be injected again
        # on the next loop. This also removes invalid payloads so they are not
        # re-parsed repeatedly.
        # Concurrent writes between the read and the clear can be lost; external
        # writers should use a temporary file followed by an atomic rename into
        # the target path.
        if not self._clear_file():
            return []

        self._last_digest = digest
        return messages

    def _clear_file(self) -> bool:
        """Truncate the file to empty. Return True on success."""
        try:
            with open(self.file_path, "w", encoding="utf-8") as fd:
                fd.write("")
            return True
        except Exception as e:
            logger.exception("failed to clear inject message file [%s]: %s", self.file_path, e)
            return False
