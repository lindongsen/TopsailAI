'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Worker process management for agent_daemon
'''

import os
import subprocess
import fcntl
import time
from typing import Dict, Optional
from pathlib import Path

from topsailai.workspace import folder_constants
from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.exceptions import WorkerError


class SessionLock:
    """File-based lock for session processing to prevent race conditions"""

    def __init__(self, session_id: str, lock_dir: str = None):
        if lock_dir is None:
            lock_dir = folder_constants.FOLDER_LOCK
        self.lock_dir = Path(lock_dir)
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.lock_dir / f"{session_id}.lock"
        self.fd = None

    def acquire(self, timeout: int = 30) -> bool:
        """Acquire the lock with timeout"""
        try:
            self.fd = open(self.lock_file, 'w')
            start_time = time.time()
            while True:
                try:
                    fcntl.lockf(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    logger.debug("Acquired lock for session: %s", self.lock_file)
                    return True
                except IOError:
                    if time.time() - start_time >= timeout:
                        logger.warning("Failed to acquire lock for session within timeout: %s", self.lock_file)
                        self.fd.close()
                        self.fd = None
                        return False
                    time.sleep(0.1)
        except Exception as e:
            logger.exception("Error acquiring lock: %s", e)
            if self.fd:
                self.fd.close()
                self.fd = None
            return False

    def release(self):
        """Release the lock"""
        if self.fd:
            try:
                fcntl.lockf(self.fd, fcntl.LOCK_UN)
                self.fd.close()
                logger.debug("Released lock for session: %s", self.lock_file)
            except Exception as e:
                logger.exception("Error releasing lock: %s", e)
            finally:
                self.fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class WorkerManager:
    """Manages worker processes for message processing"""

    def __init__(self, config):
        self.config = config
        self.running_processes: Dict[str, subprocess.Popen] = {}

    def check_session_state(self, session_id: str) -> str:
        """Check if session is idle or processing"""
        # First check local process tracking
        if session_id in self.running_processes:
            process = self.running_processes[session_id]
            if process.poll() is None:
                return "processing"
            else:
                # Process finished, clean up
                del self.running_processes[session_id]

        # Check if session state checker script is configured
        if not self.config.session_state_checker_script:
            logger.debug("No session state checker configured, assuming idle for session: %s", session_id)
            return "idle"

        # Use the session state checker script
        try:
            env = os.environ.copy()
            env['TOPSAILAI_SESSION_ID'] = session_id

            result = subprocess.run(
                [self.config.session_state_checker_script],
                env=env,
                capture_output=True,
                text=True,
                timeout=30
            )

            state = result.stdout.strip().lower()
            if state in ('idle', 'processing'):
                logger.debug("Session %s state: %s", session_id, state)
                return state
            else:
                logger.warning("Unexpected state from checker: %s", state)
                return "idle"
        except subprocess.TimeoutExpired:
            logger.warning("Session state checker timed out for session: %s", session_id)
            return "idle"
        except Exception as e:
            logger.exception("Error checking session state: %s", e)
            return "idle"

    def is_session_idle(self, session_id: str) -> bool:
        """Check if session is idle (not processing)"""
        return self.check_session_state(session_id) == "idle"

    def start_processor(self, session_id: str, msg_id: str, task: str) -> bool:
        """Start processor if not already running for session"""
        # Check session state first
        state = self.check_session_state(session_id)
        if state == "processing":
            logger.info("Session %s is already processing, skipping", session_id)
            return False

        # Use lock to prevent race conditions
        lock = SessionLock(session_id)
        if not lock.acquire(timeout=10):
            logger.warning("Could not acquire lock for session: %s", session_id)
            return False

        try:
            # Double-check state after acquiring lock
            state = self.check_session_state(session_id)
            if state == "processing":
                logger.info("Session %s is already processing after lock, skipping", session_id)
                return False

            env = os.environ.copy()
            env['TOPSAILAI_MSG_ID'] = msg_id
            env['TOPSAILAI_TASK'] = task
            env['TOPSAILAI_SESSION_ID'] = session_id
            # Add host and port for processor callback
            env['TOPSAILAI_AGENT_DAEMON_HOST'] = self.config.host
            env['TOPSAILAI_AGENT_DAEMON_PORT'] = str(self.config.port)

            logger.info("Starting processor for session: %s, msg_id: %s", session_id, msg_id)

            process = subprocess.Popen(
                [self.config.processor_script],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            self.running_processes[session_id] = process
            logger.info("Processor started for session: %s, pid: %d", session_id, process.pid)
            return True
        except Exception as e:
            logger.exception("Error starting processor: %s", e)
            return False
        finally:
            lock.release()

    def _reap_finished_processes(self):
        """Remove finished processes from running_processes to free resources."""
        for session_id, process in list(self.running_processes.items()):
            if process.poll() is not None:
                del self.running_processes[session_id]

    def start_summarizer(self, session_id: str, task: str) -> Optional[subprocess.Popen]:
        """Start summarizer for a session.
        
        Args:
            session_id: The session ID to summarize
            task: The message content to summarize
            
        Returns:
            subprocess.Popen object on success, None on failure
        """
        try:
            self._reap_finished_processes()
            # Get summarizer script path from config
            summarizer_script = self.config.summarizer_script
            if not summarizer_script:
                logger.error("Summarizer script not configured")
                return None
            
            # Check if script exists and is executable
            if not os.path.exists(summarizer_script):
                logger.error("Summarizer script not found: %s", summarizer_script)
                return None
            
            if not os.access(summarizer_script, os.X_OK):
                logger.error("Summarizer script is not executable: %s", summarizer_script)
                return None
            
            # Set environment variables
            env = os.environ.copy()
            env['TOPSAILAI_SESSION_ID'] = session_id
            env['TOPSAILAI_TASK'] = task
            # Add host and port for summarizer callback
            env['TOPSAILAI_AGENT_DAEMON_HOST'] = self.config.host
            env['TOPSAILAI_AGENT_DAEMON_PORT'] = str(self.config.port)
            
            logger.info("Starting summarizer for session: %s", session_id)
            
            process = subprocess.Popen(
                [summarizer_script],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logger.info("Summarizer started for session: %s, pid: %d", session_id, process.pid)
            return process
        except Exception as e:
            logger.exception("Error starting summarizer: %s", e)
            return None

    def wait_for_completion(self, timeout: int = 30):
        """Wait for all running processes to complete"""
        for session_id, process in list(self.running_processes.items()):
            try:
                process.wait(timeout=timeout)
                logger.info("Process completed for session: %s", session_id)
            except subprocess.TimeoutExpired:
                logger.warning("Process timed out for session: %s", session_id)
                process.kill()
            finally:
                if session_id in self.running_processes:
                    del self.running_processes[session_id]

    def stop_all(self):
        """Stop all running processes"""
        for session_id, process in list(self.running_processes.items()):
            try:
                process.terminate()
                process.wait(timeout=5)
                logger.info("Process terminated for session: %s", session_id)
            except Exception as e:
                logger.exception("Error stopping process: %s", e)
                try:
                    process.kill()
                except Exception:
                    pass
        self.running_processes.clear()
