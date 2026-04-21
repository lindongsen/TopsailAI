'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Main application entry point for agent_daemon
'''

import signal
import sys
import os
from sqlalchemy import create_engine, text

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.configer import get_config
from topsailai_server.agent_daemon.storage.session_manager import SessionSQLAlchemy
from topsailai_server.agent_daemon.storage.message_manager import MessageSQLAlchemy
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
        logger.info("Storage initialized")

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

    def run(self):
        """Run the application"""
        logger.info("Starting agent_daemon on %s:%d", self.config.host, self.config.port)

        # Start the scheduler
        self.scheduler.start()

        import uvicorn
        uvicorn.run(
            self.app,
            host=self.config.host,
            port=self.config.port,
            log_level=self.config.log_level.lower()
        )

    def shutdown(self):
        """Shutdown the application gracefully"""
        logger.info("Shutting down agent_daemon")

        # Stop scheduler
        if self.scheduler:
            self.scheduler.stop()

        # Stop all workers
        if self.worker_manager:
            self.worker_manager.stop_all()

        # Close database connections
        if self.engine:
            self.engine.dispose()

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

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        _daemon.initialize()
        _daemon.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        _daemon.shutdown()
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
