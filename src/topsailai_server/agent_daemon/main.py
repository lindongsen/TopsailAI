'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Main application entry point for agent_daemon
'''

import signal
import sys
import os
import socket
import io
import traceback
import secrets
from sqlalchemy import create_engine, text

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.configer import get_config
from topsailai_server.agent_daemon.storage.session_manager import SessionSQLAlchemy
from topsailai_server.agent_daemon.storage.message_manager import MessageSQLAlchemy
from topsailai_server.agent_daemon.storage.api_key_manager import ApiKeySQLAlchemy
from topsailai_server.agent_daemon.storage.migration import run_migrations
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.croner import create_scheduler
from topsailai_server.agent_daemon.api import create_app


class AgentDaemon:
    """Main application class for agent_daemon"""

    def __init__(self):
        self.config = None
        self.engine = None
        self.session_storage = None
        self.message_storage = None
        self.api_key_storage = None
        self.worker_manager = None
        self.scheduler = None
        self.app = None

    def initialize(self):
        """Initialize all components"""
        logger.info("Initializing agent_daemon")

        # Load configuration
        self.config = get_config()
        logger.info("Configuration loaded")

        # Create database engine
        # For SQLite, add special settings for better concurrency
        if self.config.db_url.startswith('sqlite'):
            # Enable WAL mode and timeout for SQLite
            self.engine = create_engine(
                self.config.db_url,
                connect_args={
                    'timeout': 30,  # 30 second timeout for locked database
                    'check_same_thread': False  # Allow multi-threaded access
                },
                pool_size=5,
                pool_timeout=30,
                pool_pre_ping=True,
                echo=False
            )
            # Enable WAL mode for better concurrency
            with self.engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA busy_timeout=30000"))  # 30 second busy timeout
                conn.commit()
        else:
            self.engine = create_engine(
                self.config.db_url,
                pool_size=10,
                max_overflow=20,
                pool_timeout=30,
                pool_recycle=3600,
                pool_pre_ping=True
            )
        logger.info("Database engine created: %s", self.config.db_url)

        # Run database migrations to ensure schema is up to date
        run_migrations(self.engine)

        # Initialize storage
        self.session_storage = SessionSQLAlchemy(self.engine)
        self.message_storage = MessageSQLAlchemy(self.engine)
        self.api_key_storage = ApiKeySQLAlchemy(self.engine)
        logger.info("Storage initialized")

        # Initialize default admin API key if none exists
        self._init_default_admin_key()

        # Initialize worker manager
        self.worker_manager = WorkerManager(self.config)
        logger.info("Worker manager initialized")

        # Create cron scheduler
        self.scheduler = create_scheduler(
            self.session_storage,
            self.message_storage,
            self.worker_manager,
            self.config
        )
        logger.info("Cron scheduler created")

        # Create FastAPI app
        self.app = create_app(
            self.session_storage,
            self.message_storage,
            self.worker_manager,
            self.scheduler
        )
        logger.info("FastAPI application created")

    def _init_default_admin_key(self):
        """
        Initialize a default admin API key on first startup.

        If no admin API key exists in the database, create one.
        Uses TOPSAILAI_AGENT_DAEMON_DEFAULT_ADMIN_KEY env var if set,
        otherwise generates a random secure key.
        Logs the admin key so the administrator can see it.
        """
        try:
            # Check if any admin API key already exists
            admin_count = self.api_key_storage.count_admin_api_keys()
            if admin_count > 0:
                logger.info("Admin API key already exists, skipping default initialization")
                return

            # Get default admin key from environment or generate random one
            default_key = os.getenv("TOPSAILAI_AGENT_DAEMON_DEFAULT_ADMIN_KEY")
            if default_key:
                api_key_value = default_key
                logger.info("Using configured default admin API key from environment")
            else:
                # Generate a random 32-byte hex string (64 characters)
                api_key_value = secrets.token_hex(32)
                logger.info("Generated random default admin API key")

            # Create the admin API key with unlimited rate limit
            self.api_key_storage.create_api_key(
                api_key=api_key_value,
                name="Default Admin",
                role="admin",
                rate_limit=0,
                is_active=True
            )

            logger.info("Default admin API key created successfully")
            logger.info("Admin API Key: %s", api_key_value)
            logger.info("Please save this key securely - it will not be shown again")

        except Exception as e:
            logger.exception("Failed to initialize default admin API key: %s", e)

    def _check_port_available(self, host: str, port: int) -> bool:
        """Check if the port is available for binding"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            sock.close()
            return True
        except OSError as e:
            sock.close()
            logger.error("Port %d is already in use: %s", port, e)
            return False

    def _start_server(self):
        """Start the uvicorn server with proper error capture"""
        import uvicorn

        # Capture uvicorn's stderr to ensure errors are logged
        # Uvicorn prints errors to stderr, which might not be captured by our logger
        old_stderr = sys.stderr
        old_stdout = sys.stdout
        captured_stderr = io.StringIO()
        captured_stdout = io.StringIO()

        try:
            # Redirect stderr/stdout to capture uvicorn output
            sys.stderr = captured_stderr
            sys.stdout = captured_stdout

            uvicorn.run(
                self.app,
                host=self.config.host,
                port=self.config.port,
                log_level=self.config.log_level.lower()
            )
        finally:
            # Restore stderr/stdout
            sys.stderr = old_stderr
            sys.stdout = old_stdout

            # Log any captured output
            stderr_output = captured_stderr.getvalue()
            stdout_output = captured_stdout.getvalue()

            if stderr_output:
                logger.error("Uvicorn stderr output:\n%s", stderr_output)
            if stdout_output:
                logger.info("Uvicorn stdout output:\n%s", stdout_output)

    def run(self):
        """Run the application"""
        logger.info("Starting agent_daemon on %s:%d", self.config.host, self.config.port)

        # Check if port is available before starting
        if not self._check_port_available(self.config.host, self.config.port):
            logger.error("Cannot start server - port %d is already in use", self.config.port)
            raise OSError(f"Port {self.config.port} is already in use")

        # Start the scheduler
        self.scheduler.start()
        logger.info("Cron scheduler started")

        try:
            self._start_server()
        except KeyboardInterrupt:
            logger.info("Server interrupted by user")
        except SystemExit as e:
            # Handle sys.exit() calls from uvicorn
            if e.code != 0:
                logger.error("Server exited with code: %d", e.code)
            else:
                logger.info("Server exited normally")
        except OSError as e:
            # Handle port binding errors specifically
            logger.exception("Server startup failed (OSError): %s", e)
            raise
        except Exception as e:
            # Catch any other unexpected errors
            logger.exception("Unexpected error during server startup: %s", e)
            raise

    def shutdown(self):
        """Shutdown the application gracefully"""
        logger.info("Shutting down agent_daemon")

        # Stop scheduler
        if self.scheduler:
            try:
                self.scheduler.stop()
                logger.info("Scheduler stopped")
            except Exception as e:
                logger.exception("Error stopping scheduler: %s", e)

        # Stop all workers
        if self.worker_manager:
            try:
                self.worker_manager.stop_all()
                logger.info("Worker manager stopped")
            except Exception as e:
                logger.exception("Error stopping worker manager: %s", e)

        # Close database connections
        if self.engine:
            try:
                self.engine.dispose()
                logger.info("Database connections closed")
            except Exception as e:
                logger.exception("Error closing database connections: %s", e)

        logger.info("Shutdown complete")


# Global application instance
_daemon: AgentDaemon = None


def get_daemon() -> AgentDaemon:
    """Get the global daemon instance"""
    global _daemon
    return _daemon


def main():
    """Main entry point"""
    global _daemon

    # Initialize daemon
    _daemon = AgentDaemon()

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("Received signal %d, shutting down", signum)
        if _daemon:
            _daemon.shutdown()
        sys.exit(0)

    def sigchld_handler(signum, frame):
        """Reap terminated child processes to prevent zombie processes."""
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
            except ChildProcessError:
                break

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGCHLD, sigchld_handler)

    try:
        _daemon.initialize()
        _daemon.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        _daemon.shutdown()
    except OSError as e:
        logger.exception("Fatal error (OSError): %s", e)
        _daemon.shutdown()
        sys.exit(1)
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        if _daemon:
            _daemon.shutdown()
        sys.exit(1)


if __name__ == "__main__":
    main()
