"""
Message consumer job for cron.
Consumes unprocessed messages by triggering the processor.
"""
import time
from datetime import datetime, timedelta
from typing import Optional
from topsailai_server.agent_daemon.storage.processor_helper import format_pending_messages
from topsailai_server.agent_daemon import logger

from topsailai_server.agent_daemon.croner.jobs.utils import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    retry_with_backoff,
)
from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase
from topsailai_server.agent_daemon.storage import Storage

# Circuit breaker for processor failures
_processor_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)


class MessageConsumer(CronJobBase):
    """
    Cron job that consumes unprocessed messages.
    Triggers the processor for sessions with pending messages.
    """

    def __init__(
        self,
        interval_seconds: int = 60,
        storage: Optional[Storage] = None,
        worker_manager=None
    ):
        """
        Initialize the message consumer job.

        Args:
            interval_seconds: How often to check for messages (default: 60 seconds)
            storage: Storage instance (optional, will create if not provided)
            worker_manager: WorkerManager instance (optional)
        """
        super().__init__(interval_seconds=interval_seconds, storage=storage)
        self.worker_manager = worker_manager

    def run(self) -> None:
        """
        Execute the message consumer job.
        """
        self._consume_messages()

    def _consume_messages(self):
        """Consume unprocessed messages using the storage instance."""
        start_time = time.time()
        logger.info("Message consumer job started")

        try:
            # Use the storage instance from the base class
            storage = self.storage
            if storage is None:
                logger.error("Storage not configured")
                return

            # Find recent messages (last 10 minutes)
            cutoff_time = datetime.now() - timedelta(minutes=10)
            recent_messages = storage.message.get_messages_since(cutoff_time)

            if not recent_messages:
                logger.info("No recent messages found")
                return

            # Get unique session IDs
            session_ids = list(set(msg.session_id for msg in recent_messages))
            logger.info("Found %d sessions with recent messages", len(session_ids))

            # Get processor script from environment (lazy import to avoid test issues)
            from topsailai_server.agent_daemon.configer.env_config import EnvConfig
            env_config = EnvConfig()
            processor_script = env_config.processor_script
            if not processor_script:
                logger.error("Processor script not configured")
                return

            # Process each session
            for session_id in session_ids:
                self._process_session_with_metrics(
                    session_id, processor_script, storage
                )

        except Exception as e:
            logger.exception("Message consumer job failed: %s", e)
        finally:
            self._log_execution_duration("Message consumer job", start_time)

    def _process_session_with_metrics(self, session_id, processor_script, storage):
        """
        Process a single session with execution metrics.

        Args:
            session_id: Session ID to process
            processor_script: Path to processor script
            storage: Storage instance
        """
        session_start_time = time.time()
        logger.info("Processing session: %s", session_id)

        try:
            # Check if session has unprocessed messages
            session = storage.session.get(session_id)
            if not session:
                logger.warning("Session not found: %s", session_id)
                return

            latest_message = storage.message.get_latest_message(session_id)
            if not latest_message:
                logger.info("No messages in session: %s", session_id)
                return

            # Use direct attribute access for SQLAlchemy model
            processed_msg_id = session.processed_msg_id

            # Check if processing is needed
            if processed_msg_id == latest_message.msg_id:
                logger.info("Session %s is up to date, no processing needed", session_id)
                return

            # Check if all messages between processed and latest are assistant messages
            unprocessed = storage.message.get_unprocessed_messages(
                session_id, processed_msg_id
            )

            if not unprocessed:
                logger.info("No unprocessed messages for session: %s", session_id)
                return

            # Check if all unprocessed are assistant messages (avoid infinite loop)
            all_assistant = all(msg.role == "assistant" for msg in unprocessed)
            if all_assistant:
                logger.info("All unprocessed messages are from assistant, skipping session: %s",
                            session_id)
                return

            # Check session state before processing
            if self.worker_manager is not None:
                session_state = self.worker_manager.check_session_state(session_id)
                logger.info("Session %s state: %s", session_id, session_state)
                if session_state != 'idle':
                    logger.info("Session %s is already processing, skipping", session_id)
                    return

            # Execute with resilience (retry + circuit breaker)
            success = self._execute_with_resilience(
                session_id, processor_script, unprocessed
            )

            if success:
                logger.info("Successfully triggered processor for session: %s", session_id)
            else:
                logger.warning("Failed to trigger processor for session: %s", session_id)

        except Exception as e:
            logger.exception("Error processing session %s: %s", session_id, e)
        finally:
            duration_ms = (time.time() - session_start_time) * 1000
            if duration_ms > 30000:
                logger.warning("Slow session processing: session=%s, duration=%.2fms",
                               session_id, duration_ms)
            else:
                logger.info("Session processing completed: session=%s, duration=%.2fms",
                            session_id, duration_ms)

    def _execute_with_resilience(self, session_id, processor_script, unprocessed):
        """
        Execute processor with circuit breaker and retry logic.

        Args:
            session_id: Session ID to process
            processor_script: Path to processor script
            unprocessed: List of unprocessed messages

        Returns:
            True if execution succeeded, False otherwise
        """
        def _execute_processor():
            if self.worker_manager is None:
                logger.error("Worker manager not configured")
                return False

            # Format the task
            task = format_pending_messages(unprocessed)
            latest_msg = unprocessed[-1]

            return self.worker_manager.start_processor(
                session_id=session_id,
                msg_id=latest_msg.msg_id,
                task=task
            )

        try:
            return _processor_circuit_breaker.call(_execute_processor)
        except CircuitBreakerOpenError:
            return False
        except Exception as e:
            logger.exception("Processor execution failed for session %s: %s", session_id, e)
            return False

    def _log_execution_duration(self, job_name, start_time):
        """
        Log job execution duration.

        Args:
            job_name: Name of the job
            start_time: Start time from time.time()
        """
        duration_ms = (time.time() - start_time) * 1000
        if duration_ms > 30000:
            logger.warning("%s took %.2fms (slow execution)", job_name, duration_ms)
        else:
            logger.info("%s completed in %.2fms", job_name, duration_ms)
