import logging
from abc import ABC, abstractmethod
from typing import Iterable

from topsailai.ai_base.constants import (
    ROLE_USER,
    STEP_NAME_OBSERVATION,
    MSG_KEY_STEP_NAME,
    MSG_KEY_RAW_TEXT,
)
from topsailai.utils import thread_local_tool

logger = logging.getLogger(__name__)


class Agent2LLMMessageSource(ABC):
    """Abstract source of runtime messages to inject into the Agent2LLM context."""

    @abstractmethod
    def consume_messages(self) -> Iterable[dict]:
        """Return messages to inject into the Agent2LLM context.

        Each yielded message must be a dict with at least a ``content`` key and
        optionally a ``role`` key. The caller is responsible for converting the
        payload into the project's content-dict format.

        The source must consume/remove the underlying payload so that the same
        message is not returned twice.

        Note:
            Currently only ``role="user"`` is fully supported. Other roles
            (``assistant``, ``tool``) are accepted but will be coerced to
            ``user`` with a warning. This keeps the injected messages in a
            valid position within the Agent2LLM context.

        Yields:
            dict: ``{"role": "user"|"assistant"|"tool", "content": str|dict}``
        """
        raise NotImplementedError

    @abstractmethod
    def produce_message(
        self,
        content: str | dict,
        role: str = ROLE_USER,
        step_name: str = STEP_NAME_OBSERVATION,
    ) -> bool:
        """Produce/write a runtime message to this source.

        The source is responsible for persisting the message so that a later
        call to ``consume_messages()`` can retrieve it. The exact storage
        mechanism is implementation-specific.

        Args:
            content: The message payload. Strings are wrapped into the project's
                structured content format; dicts are passed through as-is.
            role: Message role. Defaults to ``ROLE_USER``.
            step_name: Value for the ``step_name`` key when wrapping string
                content. Defaults to ``STEP_NAME_OBSERVATION``.

        Returns:
            bool: ``True`` if the message was produced successfully.
        """
        raise NotImplementedError

    @staticmethod
    def build_message(
        content: str | dict,
        role: str = ROLE_USER,
        step_name: str = STEP_NAME_OBSERVATION,
    ) -> dict:
        """Build a standard runtime message dict.

        The returned dict uses the project's content-dict format with
        ``step_name`` and ``raw_text`` keys. Callers that need a simpler
        ``{"role": ..., "content": ...}`` payload (for example when writing to
        the file source) can use ``build_simple_message`` instead.

        Args:
            content: The message payload. Strings are wrapped in the content
                dict; dicts are used as-is.
            role: Message role. Defaults to ``ROLE_USER``.
            step_name: Value for the ``step_name`` key. Defaults to
                ``STEP_NAME_OBSERVATION``.

        Returns:
            dict: ``{"role": role, "content": {"step_name": ..., "raw_text": ...}}``
        """
        if isinstance(content, dict):
            content_dict = content
        else:
            content_dict = {
                MSG_KEY_STEP_NAME: step_name,
                MSG_KEY_RAW_TEXT: str(content),
            }
        return {"role": role, "content": content_dict}

    @staticmethod
    def build_simple_message(
        content: str | dict,
        role: str = ROLE_USER,
    ) -> dict:
        """Build a simple ``{"role": ..., "content": ...}`` message dict.

        This format is convenient for external writers such as the file-based
        source, where the consumer later converts the payload into the project's
        content-dict format.

        Args:
            content: The message payload.
            role: Message role. Defaults to ``ROLE_USER``.

        Returns:
            dict: ``{"role": role, "content": content}``
        """
        return {"role": role, "content": content}


def set_agent2llm_message_source(source):
    """Register (or clear) the runtime message source in thread-local storage.

    Args:
        source: An ``Agent2LLMMessageSource`` instance, or ``None`` to clear.
    """
    thread_local_tool.set_thread_var(
        thread_local_tool.KEY_AGENT2LLM_MESSAGE_SOURCE, source
    )


def get_agent2llm_message_source():
    """Return the registered runtime message source, or ``None``."""
    return thread_local_tool.get_thread_var(
        thread_local_tool.KEY_AGENT2LLM_MESSAGE_SOURCE
    )


def unset_agent2llm_message_source():
    """Remove the runtime message source from thread-local storage."""
    thread_local_tool.unset_thread_var(
        thread_local_tool.KEY_AGENT2LLM_MESSAGE_SOURCE
    )


def apply_agent2llm_message_source(agent) -> int:
    """Inject runtime messages from the registered source into ``agent.messages``.

    This is called from ``ai_base`` before each LLM chat call. Messages are
    appended at the tail of ``agent.messages`` as user-role observation content
    dicts.

    The source may yield messages in two formats:

    * Simple format: ``{"role": "user", "content": "plain text"}``
    * Structured format: ``{"role": "user", "content": {"step_name": "observation", "raw_text": "..."}}``

    Simple-format content is wrapped into the structured format using
    ``Agent2LLMMessageSource.build_message``. Structured content is used as-is
    when it contains the expected keys; otherwise it is coerced safely and a
    warning is logged.

    Args:
        agent: The current ``AgentBase`` instance.

    Returns:
        int: Number of messages injected.
    """
    source = get_agent2llm_message_source()
    if source is None:
        return 0

    count = 0
    for msg in source.consume_messages():
        if not isinstance(msg, dict):
            logger.warning("skip non-dict runtime message from source: %s", type(msg))
            continue

        role = msg.get("role", ROLE_USER)
        content = msg.get("content", "")

        if content is None:
            logger.warning("skip runtime message with None content from source")
            continue

        if isinstance(content, dict):
            if not content:
                logger.warning("skip empty runtime message from source")
                continue
            if MSG_KEY_STEP_NAME not in content or MSG_KEY_RAW_TEXT not in content:
                logger.warning(
                    "structured content missing required keys %s/%s, coercing",
                    MSG_KEY_STEP_NAME,
                    MSG_KEY_RAW_TEXT,
                )
                content_dict = Agent2LLMMessageSource.build_message(
                    str(content), role=role, step_name=STEP_NAME_OBSERVATION
                )["content"]
            elif not content[MSG_KEY_RAW_TEXT]:
                logger.warning("skip runtime message with empty raw_text from source")
                continue
            else:
                content_dict = content
        elif isinstance(content, str):
            if not content:
                logger.warning("skip empty runtime message from source")
                continue
            content_dict = Agent2LLMMessageSource.build_message(
                content, role=role, step_name=STEP_NAME_OBSERVATION
            )["content"]
        else:
            text = str(content)
            if not text:
                logger.warning("skip empty runtime message from source")
                continue
            content_dict = Agent2LLMMessageSource.build_message(
                text, role=role, step_name=STEP_NAME_OBSERVATION
            )["content"]

        if role == ROLE_USER:
            agent.add_user_message(content_dict, need_print=False)
        else:
            # Default to user role for unknown roles to keep the context valid.
            logger.warning("unsupported runtime message role '%s', defaulting to user", role)
            agent.add_user_message(content_dict, need_print=False)

        count += 1

    if count:
        logger.info("injected %d runtime message(s) into Agent2LLM context", count)
    return count
