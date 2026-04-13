"""FastAPI application factory for agent_daemon API."""

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage

# Global references for dependency injection
_storage: Optional[Storage] = None
_worker_manager = None
_scheduler = None


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    database: str
    timestamp: datetime


def create_app(session_storage, message_storage, worker_manager, scheduler) -> FastAPI:
    """Create and configure the FastAPI application."""
    global _storage, _worker_manager, _scheduler

    _storage = Storage(session_storage.engine)
    _worker_manager = worker_manager
    _scheduler = scheduler

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan context manager for startup/shutdown."""
        logger.info("Starting agent_daemon API server")
        if scheduler:
            scheduler.start()
        yield
        # Shutdown
        logger.info("Shutting down agent_daemon API server")
        if scheduler:
            scheduler.stop()
        if worker_manager:
            worker_manager.stop_all()

    # Create FastAPI app
    fastapi_app = FastAPI(
        title="Agent Daemon API",
        description="API for managing sessions and messages",
        version="1.0.0",
        lifespan=lifespan
    )

    # Health check endpoint - returns unified response format
    @fastapi_app.get("/health")
    async def health_check():
        """Health check endpoint."""
        db_status = "healthy"
        try:
            _storage.session.get_all()
        except Exception as e:
            logger.exception("Database health check failed: %s", e)
            db_status = "unhealthy"

        response_data = HealthResponse(
            status="healthy" if db_status == "healthy" else "degraded",
            database=db_status,
            timestamp=datetime.now()
        )

        return {
            "code": 0,
            "data": response_data.model_dump(),
            "message": "OK"
        }

    # Include routers
    from topsailai_server.agent_daemon.api.routes import message, task, session
    message.set_dependencies(session_storage, message_storage, worker_manager)
    task.set_dependencies(session_storage, message_storage, worker_manager)
    session.set_dependencies(session_storage, message_storage, worker_manager)

    fastapi_app.include_router(message.router)
    fastapi_app.include_router(task.router)
    fastapi_app.include_router(session.router)

    return fastapi_app