"""
Session Manager Package for AI Engineering Context

This package provides session management functionality for the AI engineering framework.
It includes base classes for session data and storage, as well as SQLAlchemy-based
implementations for persistent session management.

Modules:
- __base: Abstract base classes for session data and storage
- sql: SQLAlchemy implementation of session storage

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-29
"""

from .__base import SessionData, SessionStorageBase
from .sql import SessionSQLAlchemy

__all__ = [
    'SessionData',
    'SessionStorageBase', 
    'SessionSQLAlchemy'
]