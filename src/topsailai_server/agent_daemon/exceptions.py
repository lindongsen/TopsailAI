'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Custom exceptions for agent_daemon
'''


class AgentDaemonError(Exception):
    """Base exception for agent_daemon"""
    pass


class StorageError(AgentDaemonError):
    """Database operations errors"""
    pass


class WorkerError(AgentDaemonError):
    """Worker process errors"""
    pass


class ConfigError(AgentDaemonError):
    """Configuration errors"""
    pass


class APIError(AgentDaemonError):
    """API errors"""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
