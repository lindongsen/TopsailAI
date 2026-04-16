"""
Base Client Module

This module provides the BaseClient class that serves as the foundation
for all API client classes in the agent_daemon client package.

Features:
    - HTTP request handling with proper error management
    - API response parsing and validation
    - Common utilities for time formatting and display
"""

import os
from typing import Any, Dict, Optional, Union

import requests

from topsailai_server.agent_daemon import logger


# Constant for formatting output separators
SPLIT_LINE = "\n" + "=" * 77


class APIError(Exception):
    """Custom exception for API errors."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"API Error {code}: {message}")


class BaseClient:
    """
    Base client class for interacting with the agent_daemon API.

    This class provides common functionality for making HTTP requests
    and handling API responses.

    Attributes:
        base_url: The base URL of the agent_daemon API server.

    Example:
        >>> client = BaseClient()
        >>> client.request("GET", "/api/v1/session")
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 10
    ):
        """
        Initialize the BaseClient.

        Args:
            base_url: Base URL of the API server. If not provided,
                     uses environment variables or defaults to
                     "http://127.0.0.1:7373".
            timeout: Default timeout for HTTP requests in seconds.
                    Defaults to 10 seconds.
        """
        if base_url is None:
            host = os.environ.get("TOPSAILAI_AGENT_DAEMON_HOST", "127.0.0.1")
            port = os.environ.get("TOPSAILAI_AGENT_DAEMON_PORT", "7373")
            base_url = f"http://{host}:{port}"

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @staticmethod
    def format_time(time_str: Optional[str]) -> str:
        """
        Format time string to YYYY-MM-DD HH:MM:SS format.

        This method handles ISO format timestamps and extracts
        only the date and time parts (up to seconds).

        Args:
            time_str: Time string in ISO format (e.g., "2026-04-13T23:27:53.123456")
                     or already formatted string.

        Returns:
            Formatted time string in "YYYY-MM-DD HH:MM:SS" format,
            or "N/A" if time_str is None or empty.

        Example:
            >>> BaseClient.format_time("2026-04-13T23:27:53.123456")
            '2026-04-13 23:27:53'
            >>> BaseClient.format_time(None)
            'N/A'
        """
        if not time_str:
            return "N/A"

        # Handle ISO format: 2026-04-13T23:27:53.123456
        if "T" in time_str:
            date_part, time_part = time_str.split("T", 1)
            # Remove microseconds if present
            time_part = time_part.split(".")[0]
            return f"{date_part} {time_part}"

        return time_str

    def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> Any:
        """
        Make an HTTP request to the API.

        This method handles all HTTP methods (GET, POST, DELETE, etc.)
        and automatically parses the API response format.

        Args:
            method: HTTP method (GET, POST, DELETE, PUT, etc.).
            endpoint: API endpoint path (e.g., "/api/v1/session").
            params: Query parameters for GET requests.
            json_data: JSON body for POST/PUT requests.
            timeout: Request timeout in seconds. If not provided,
                    uses the default timeout from __init__.

        Returns:
            The 'data' field from the API response.

        Raises:
            APIError: If the API returns a non-zero code.
            requests.exceptions.ConnectionError: If cannot connect to server.
            requests.exceptions.Timeout: If request times out.

        Example:
            >>> client = BaseClient()
            >>> sessions = client.request("GET", "/api/v1/session")
        """
        url = f"{self.base_url}{endpoint}"
        if timeout is None:
            timeout = self.timeout

        try:
            logger.info("Request: %s %s", method, url)

            response = requests.request(
                method=method.upper(),
                url=url,
                params=params,
                json=json_data,
                timeout=timeout
            )

            if response.status_code != 200:
                logger.error("HTTP Error: %s - %s", response.status_code, response.text)
                raise APIError(response.status_code, response.text)

            result = response.json()
            code = result.get("code", -1)
            message = result.get("message", "Unknown error")
            data = result.get("data")

            if code != 0:
                logger.error("API Error: %s - %s", code, message)
                raise APIError(code, message)

            logger.info("Request successful")
            return data

        except requests.exceptions.ConnectionError as e:
            logger.error("Connection error: %s", e)
            raise
        except requests.exceptions.Timeout as e:
            logger.error("Request timeout: %s", e)
            raise
        except APIError:
            raise
        except Exception as e:
            logger.exception("Request failed: %s", e)
            raise

    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> Any:
        """
        Make a GET request to the API.

        Args:
            endpoint: API endpoint path.
            params: Query parameters.
            timeout: Request timeout in seconds.

        Returns:
            The 'data' field from the API response.
        """
        return self.request("GET", endpoint, params=params, timeout=timeout)

    def post(
        self,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> Any:
        """
        Make a POST request to the API.

        Args:
            endpoint: API endpoint path.
            json_data: JSON body data.
            timeout: Request timeout in seconds.

        Returns:
            The 'data' field from the API response.
        """
        return self.request("POST", endpoint, json_data=json_data, timeout=timeout)

    def delete(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> Any:
        """
        Make a DELETE request to the API.

        Args:
            endpoint: API endpoint path.
            params: Query parameters.
            timeout: Request timeout in seconds.

        Returns:
            The 'data' field from the API response.
        """
        return self.request("DELETE", endpoint, params=params, timeout=timeout)

    def health_check(self) -> bool:
        """
        Check if the server is healthy.

        Returns:
            True if server is healthy, False otherwise.
        """
        try:
            self.get("/health", timeout=5)
            return True
        except Exception as e:
            logger.warning("Health check failed: %s", e)
            return False
