"""
Unit Tests for Client Package Initialization

This module contains unit tests for the client package __init__.py module.
It tests the exports, imports, and module-level attributes.

Test Classes:
    - TestClientPackageImports: Test that all expected imports are available
    - TestClientPackageExports: Test that __all__ exports are correct
    - TestClientPackageAttributes: Test module-level attributes
    - TestClientPackageIntegration: Test integration scenarios

Usage:
    Run all tests:
        pytest tests/unit/test_client/test_client_main.py -v
"""

import pytest
import sys
from unittest.mock import patch, MagicMock


class TestClientPackageImports:
    """Test that all expected imports from the client package are available."""

    def test_import_base_client(self):
        """Test that BaseClient can be imported from the package."""
        from topsailai_server.agent_daemon.client import BaseClient
        assert BaseClient is not None

    def test_import_session_client(self):
        """Test that SessionClient can be imported from the package."""
        from topsailai_server.agent_daemon.client import SessionClient
        assert SessionClient is not None

    def test_import_message_client(self):
        """Test that MessageClient can be imported from the package."""
        from topsailai_server.agent_daemon.client import MessageClient
        assert MessageClient is not None

    def test_import_task_client(self):
        """Test that TaskClient can be imported from the package."""
        from topsailai_server.agent_daemon.client import TaskClient
        assert TaskClient is not None

    def test_import_api_error(self):
        """Test that APIError can be imported from the package."""
        from topsailai_server.agent_daemon.client import APIError
        assert APIError is not None

    def test_import_split_line(self):
        """Test that SPLIT_LINE can be imported from the package."""
        from topsailai_server.agent_daemon.client import SPLIT_LINE
        assert SPLIT_LINE is not None
        assert isinstance(SPLIT_LINE, str)

    def test_import_session_do_functions(self):
        """Test that session do_xxx functions can be imported."""
        from topsailai_server.agent_daemon.client import (
            do_client_health,
            do_client_list_sessions,
            do_client_get_session,
            do_client_delete_sessions,
            do_client_process_session,
        )
        assert callable(do_client_health)
        assert callable(do_client_list_sessions)
        assert callable(do_client_get_session)
        assert callable(do_client_delete_sessions)
        assert callable(do_client_process_session)

    def test_import_message_do_functions(self):
        """Test that message do_xxx functions can be imported."""
        from topsailai_server.agent_daemon.client import (
            do_client_send_message,
            do_client_get_messages,
        )
        assert callable(do_client_send_message)
        assert callable(do_client_get_messages)

    def test_import_task_do_functions(self):
        """Test that task do_xxx functions can be imported."""
        from topsailai_server.agent_daemon.client import (
            do_client_set_task_result,
            do_client_get_tasks,
        )
        assert callable(do_client_set_task_result)
        assert callable(do_client_get_tasks)

    def test_import_add_parser_functions(self):
        """Test that add_xxx_parsers functions can be imported."""
        from topsailai_server.agent_daemon.client import (
            add_session_parsers,
            add_message_parsers,
            add_task_parsers,
        )
        assert callable(add_session_parsers)
        assert callable(add_message_parsers)
        assert callable(add_task_parsers)


class TestClientPackageExports:
    """Test that __all__ exports are correct and complete."""

    def test_all_contains_base_classes(self):
        """Test that __all__ contains base class exports."""
        from topsailai_server.agent_daemon import client
        assert "BaseClient" in client.__all__
        assert "APIError" in client.__all__
        assert "SPLIT_LINE" in client.__all__

    def test_all_contains_client_classes(self):
        """Test that __all__ contains client class exports."""
        from topsailai_server.agent_daemon import client
        assert "SessionClient" in client.__all__
        assert "MessageClient" in client.__all__
        assert "TaskClient" in client.__all__

    def test_all_contains_session_functions(self):
        """Test that __all__ contains session function exports."""
        from topsailai_server.agent_daemon import client
        assert "do_client_health" in client.__all__
        assert "do_client_list_sessions" in client.__all__
        assert "do_client_get_session" in client.__all__
        assert "do_client_delete_sessions" in client.__all__
        assert "do_client_process_session" in client.__all__
        assert "add_session_parsers" in client.__all__

    def test_all_contains_message_functions(self):
        """Test that __all__ contains message function exports."""
        from topsailai_server.agent_daemon import client
        assert "do_client_send_message" in client.__all__
        assert "do_client_get_messages" in client.__all__
        assert "add_message_parsers" in client.__all__

    def test_all_contains_task_functions(self):
        """Test that __all__ contains task function exports."""
        from topsailai_server.agent_daemon import client
        assert "do_client_set_task_result" in client.__all__
        assert "do_client_get_tasks" in client.__all__
        assert "add_task_parsers" in client.__all__

    def test_all_is_list(self):
        """Test that __all__ is a list."""
        from topsailai_server.agent_daemon import client
        assert isinstance(client.__all__, list)

    def test_all_has_expected_length(self):
        """Test that __all__ has the expected number of exports."""
        from topsailai_server.agent_daemon import client
        # Base (3) + Clients (3) + Session (6) + Message (3) + Task (3) = 18
        assert len(client.__all__) == 18


class TestClientPackageAttributes:
    """Test module-level attributes."""

    def test_version_exists(self):
        """Test that __version__ attribute exists."""
        from topsailai_server.agent_daemon import client
        assert hasattr(client, "__version__")
        assert isinstance(client.__version__, str)

    def test_version_format(self):
        """Test that __version__ follows semantic versioning."""
        from topsailai_server.agent_daemon import client
        parts = client.__version__.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_package_has_docstring(self):
        """Test that the package has a docstring."""
        from topsailai_server.agent_daemon import client
        assert client.__doc__ is not None
        assert len(client.__doc__) > 0


class TestClientPackageIntegration:
    """Test integration scenarios for the client package."""

    def test_create_session_client_instance(self):
        """Test creating a SessionClient instance."""
        from topsailai_server.agent_daemon.client import SessionClient
        client_instance = SessionClient("http://localhost:7373")
        assert client_instance is not None
        assert client_instance.base_url == "http://localhost:7373"

    def test_create_message_client_instance(self):
        """Test creating a MessageClient instance."""
        from topsailai_server.agent_daemon.client import MessageClient
        client_instance = MessageClient("http://localhost:7373")
        assert client_instance is not None
        assert client_instance.base_url == "http://localhost:7373"

    def test_create_task_client_instance(self):
        """Test creating a TaskClient instance."""
        from topsailai_server.agent_daemon.client import TaskClient
        client_instance = TaskClient("http://localhost:7373")
        assert client_instance is not None
        assert client_instance.base_url == "http://localhost:7373"

    def test_client_inheritance_hierarchy(self):
        """Test that all clients inherit from BaseClient."""
        from topsailai_server.agent_daemon.client import (
            BaseClient,
            SessionClient,
            MessageClient,
            TaskClient,
        )
        session = SessionClient("http://localhost:7373")
        message = MessageClient("http://localhost:7373")
        task = TaskClient("http://localhost:7373")

        assert isinstance(session, BaseClient)
        assert isinstance(message, BaseClient)
        assert isinstance(task, BaseClient)

    def test_api_error_is_exception(self):
        """Test that APIError is an exception class."""
        from topsailai_server.agent_daemon.client import APIError
        assert issubclass(APIError, Exception)

    def test_api_error_instantiation(self):
        """Test creating an APIError instance."""
        from topsailai_server.agent_daemon.client import APIError
        error = APIError(500, "Test error")
        assert "Test error" in str(error)

    def test_split_line_is_string(self):
        """Test that SPLIT_LINE is a non-empty string."""
        from topsailai_server.agent_daemon.client import SPLIT_LINE
        assert isinstance(SPLIT_LINE, str)
        assert len(SPLIT_LINE) > 0

    def test_all_exports_are_accessible(self):
        """Test that all items in __all__ are accessible."""
        from topsailai_server.agent_daemon import client
        for item in client.__all__:
            assert hasattr(client, item), f"Item {item} not accessible in client module"

    def test_package_import_performance(self):
        """Test that importing the package is reasonably fast."""
        import time
        start = time.time()
        from topsailai_server.agent_daemon import client
        elapsed = time.time() - start
        # Import should complete in less than 1 second
        assert elapsed < 1.0, f"Package import took {elapsed:.2f}s, expected < 1.0s"


class TestClientPackageEdgeCases:
    """Test edge cases for the client package."""

    def test_client_base_url_normalization(self):
        """Test that client normalizes base URL (removes trailing slash)."""
        from topsailai_server.agent_daemon.client import SessionClient
        # Test with trailing slash - should be normalized
        client1 = SessionClient("http://localhost:7373/")
        assert client1.base_url == "http://localhost:7373"

    def test_multiple_client_instances(self):
        """Test creating multiple client instances."""
        from topsailai_server.agent_daemon.client import (
            SessionClient,
            MessageClient,
            TaskClient,
        )
        clients = [
            SessionClient("http://localhost:7373"),
            MessageClient("http://localhost:7373"),
            TaskClient("http://localhost:7373"),
        ]
        assert len(clients) == 3
        assert all(c is not None for c in clients)

    def test_client_package_docstring_content(self):
        """Test that package docstring contains expected content."""
        from topsailai_server.agent_daemon import client
        doc = client.__doc__
        assert "Agent Daemon Client" in doc
        assert "client modules" in doc.lower()

    def test_version_is_stable(self):
        """Test that version follows expected format."""
        from topsailai_server.agent_daemon import client
        version = client.__version__
        # Version should be X.Y.Z format
        assert len(version.split(".")) == 3
        major, minor, patch = version.split(".")
        assert major.isdigit()
        assert minor.isdigit()
        assert patch.isdigit()

    def test_all_exports_are_unique(self):
        """Test that all items in __all__ are unique."""
        from topsailai_server.agent_daemon import client
        all_items = client.__all__
        assert len(all_items) == len(set(all_items)), "Duplicate items in __all__"

    def test_client_with_different_url_formats(self):
        """Test creating clients with different URL formats."""
        from topsailai_server.agent_daemon.client import SessionClient
        # Test with IP address
        client1 = SessionClient("http://127.0.0.1:7373")
        assert client1.base_url == "http://127.0.0.1:7373"
        # Test with different port
        client2 = SessionClient("http://localhost:8080")
        assert client2.base_url == "http://localhost:8080"
