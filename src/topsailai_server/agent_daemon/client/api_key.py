"""
API Key Client Module

This module provides the ApiKeyClient class for interacting with
the API key management endpoints of the agent_daemon API.

Features:
    - Set environment variables for API keys
    - List environment variables for API keys
    - Delete environment variables for API keys

Usage:
    from topsailai_server.agent_daemon.client import ApiKeyClient

    client = ApiKeyClient()
    client.set_api_key_environ("ak_xxx", "KEY", "value")
    environs = client.list_api_key_environs("ak_xxx")
    client.delete_api_key_environ("ak_xxx", "KEY")
"""

from typing import Any, Dict, List, Optional

from topsailai_server.agent_daemon.client.base import BaseClient, SPLIT_LINE


class ApiKeyClient(BaseClient):
    """
    Client for API key management-related API operations.

    This class provides methods for managing API key environment variables.

    Example:
        >>> client = ApiKeyClient()
        >>> client.set_api_key_environ("ak_xxx", "KEY", "value")
        >>> environs = client.list_api_key_environs("ak_xxx")
        >>> client.delete_api_key_environ("ak_xxx", "KEY")
    """

    def set_api_key_environ(
        self,
        api_key_id: str,
        key: str,
        value: str,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Set an environment variable for an API key.

        Args:
            api_key_id: The API key ID to set the environment variable for.
            key: The environment variable name.
            value: The environment variable value.
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with the created/updated environment variable info.

        Raises:
            APIError: If the API returns an error.
        """
        data = {
            "key": key,
            "value": value,
        }

        result = self.post(f"/api/v1/apikey/{api_key_id}/environs", json_data=data)

        # Print formatted output
        print(f"Environment variable set successfully")
        print(f"  API Key ID: {api_key_id}")
        print(f"  Key: {key}")
        print(f"  Value: {value}")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

    def list_api_key_environs(
        self,
        api_key_id: str,
        verbose: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List all environment variables for an API key.

        Args:
            api_key_id: The API key ID to list environment variables for.
            verbose: If True, print full JSON response.

        Returns:
            List of environment variable dictionaries.

        Raises:
            APIError: If the API returns an error.
        """
        result = self.get(f"/api/v1/apikey/{api_key_id}/environs")

        environs = result.get("environs", []) if result else []
        total = result.get("total", 0) if result else 0

        # Print formatted output
        print(f"API Key Environs: {total}")

        if verbose:
            import json
            print(json.dumps(result, indent=2))
        elif environs:
            for env in environs:
                self._print_environ(env)

        return environs

    def delete_api_key_environ(
        self,
        api_key_id: str,
        key: str,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Delete an environment variable for an API key.

        Args:
            api_key_id: The API key ID to delete the environment variable from.
            key: The environment variable name to delete.
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with the deletion result.

        Raises:
            APIError: If the API returns an error.
        """
        result = self.delete(f"/api/v1/apikey/{api_key_id}/environs/{key}")

        # Print formatted output
        print(f"Environment variable deleted successfully")
        print(f"  API Key ID: {api_key_id}")
        print(f"  Key: {key}")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

    def _print_environ(self, environ: Dict[str, Any]) -> None:
        """
        Print a single environment variable in formatted output.

        Args:
            environ: Environment variable dictionary to print.
        """
        create_time = self.format_time(environ.get('create_time'))
        api_key_id = environ.get('api_key_id')
        key = environ.get('key')
        value = environ.get('value')

        print(SPLIT_LINE)
        print(f"[{create_time}] [{api_key_id}] {key}={value}")
