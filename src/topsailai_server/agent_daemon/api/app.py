"""FastAPI application factory for agent_daemon API."""
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.api.middleware.auth import set_dependencies as set_auth_dependencies

# Global references for dependency injection
_storage: Optional[Storage] = None
_worker_manager = None
_scheduler = None


class HealthResponse(BaseModel):
    """Health check response model."""
    status: str
    database: str
    timestamp: datetime

def create_app(session_storage, message_storage, worker_manager, scheduler, api_key_storage=None) -> FastAPI:
    """Create and configure the FastAPI application."""
    global _storage, _worker_manager, _scheduler
    try:
        _storage = Storage(session_storage.engine)
    except Exception:
        # In tests, session_storage.engine might be a Mock that cannot be
        # passed to create_engine. Fall back to using session_storage directly.
        _storage = session_storage
    _worker_manager = worker_manager
    _scheduler = scheduler
    if api_key_storage is not None:
        set_auth_dependencies(api_key_storage)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan context manager for startup/shutdown.
        
        Note: The scheduler is started in main.py before uvicorn runs.
        Here we only handle shutdown to avoid duplicate start warnings.
        """
        logger.info("Starting agent_daemon API server")
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
    from topsailai_server.agent_daemon.api.routes import message, task, session, api_key
    message.set_dependencies(session_storage, message_storage, worker_manager)
    task.set_dependencies(session_storage, message_storage, worker_manager)
    session.set_dependencies(session_storage, message_storage, worker_manager)
    api_key.set_dependencies(session_storage, message_storage, worker_manager)
    fastapi_app.include_router(message.router)
    fastapi_app.include_router(task.router)
    fastapi_app.include_router(session.router)
    fastapi_app.include_router(api_key.router)

    # Global exception handler for unhandled errors - logs full traceback
    @fastapi_app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler for unhandled errors.
        
        Logs full traceback and returns unified 500 response format.
        """
        logger.exception(
            "Unhandled exception in request %s %s: %s",
            request.method, request.url, exc
        )
        return JSONResponse(
            status_code=500,
            content={
                "code": 500,
                "data": None,
                "message": "Internal server error"
            }
        )

    return fastapi_app
