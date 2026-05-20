"""
API Key Client Module

This module provides the ApiKeyClient class for interacting with
the API key management endpoints of the agent_daemon API.

Features:
    - Create API keys
    - List API keys
    - Delete API keys
    - Bind sessions to API keys
    - Unbind sessions from API keys
    - Set environment variables for API keys
    - List environment variables for API keys
    - Delete environment variables for API keys

Usage:
    from topsailai_server.agent_daemon.client import ApiKeyClient

    client = ApiKeyClient()
    api_key = client.create_api_key(name="My Key", role="user")
    api_keys = client.list_api_keys()
    client.delete_api_key("ak_xxx")
    client.bind_sessions("ak_xxx", ["session-1"])
    client.unbind_sessions("ak_xxx", ["session-1"])
    client.set_api_key_environ("ak_xxx", "KEY", "value")
    environs = client.list_api_key_environs("ak_xxx")
    client.delete_api_key_environ("ak_xxx", "KEY")
"""

from typing import Any, Dict, List, Optional

from topsailai_server.agent_daemon.client.base import BaseClient, SPLIT_LINE


class ApiKeyClient(BaseClient):
    """
    Client for API key management-related API operations.

    This class provides methods for managing API keys including CRUD
    operations, session binding, and environment variable management.

    Example:
        >>> client = ApiKeyClient()
        >>> api_key = client.create_api_key(name="My Key", role="user")
        >>> api_keys = client.list_api_keys()
        >>> client.delete_api_key("ak_xxx")
        >>> client.bind_sessions("ak_xxx", ["session-1"])
        >>> client.unbind_sessions("ak_xxx", ["session-1"])
    """

    def create_api_key(
        self,
        name: str,
        role: str = "user",
        rate_limit: int = 0,
        session_ids: Optional[List[str]] = None,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new API key.

        Args:
            name: Human-readable name for the key.
            role: Role of the key, 'admin' or 'user'. Defaults to 'user'.
            rate_limit: Max messages per minute, 0 means unlimited.
                        Defaults to 0.
            session_ids: Optional list of session IDs to bind (user role only).
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with the created API key info including the
            actual key value (shown only once on creation).

        Raises:
            APIError: If the API returns an error.
        """
        data = {
            "name": name,
            "role": role,
            "rate_limit": rate_limit,
        }

        if session_ids is not None:
            data["session_ids"] = session_ids

        result = self.post("/api/v1/apikey", json_data=data)

        # Print formatted output
        api_key_id = result.get("api_key_id", "N/A")
        api_key_value = result.get("api_key", "N/A")
        key_role = result.get("role", "N/A")
        key_rate_limit = result.get("rate_limit", "N/A")
        is_active = result.get("is_active", "N/A")
        create_time = self.format_time(result.get("create_time"))

        print("API Key created successfully")
        print(SPLIT_LINE)
        print(f"API Key ID: {api_key_id}")
        print(f"API Key:    {api_key_value}")
        print(f"Name:       {name}")
        print(f"Role:       {key_role}")
        print(f"Rate Limit: {key_rate_limit}")
        print(f"Active:     {is_active}")
        print(f"Created:    {create_time}")
        print(SPLIT_LINE)
        print("WARNING: The API key value is shown only once. Save it securely.")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

    def list_api_keys(
        self,
        session_id: Optional[str] = None,
        verbose: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List API keys.

        Args:
            session_id: Optional session ID to filter by.
            verbose: If True, print full JSON response.

        Returns:
            List of API key dictionaries.

        Raises:
            APIError: If the API returns an error.
        """
        params = {}
        if session_id:
            params["session_id"] = session_id

        result = self.get("/api/v1/apikey", params=params)

        api_keys = result.get("api_keys", []) if result else []
        total = result.get("total", 0) if result else 0

        # Print formatted output
        print(f"API Keys: {total}")

        if verbose:
            import json
            print(json.dumps(result, indent=2))
        elif api_keys:
            for api_key in api_keys:
                self._print_api_key(api_key)

        return api_keys

    def delete_api_key(
        self,
        api_key_id: str,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Delete an API key.

        Args:
            api_key_id: The API key ID to delete.
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with the deletion result.

        Raises:
            APIError: If the API returns an error.
        """
        result = self.delete(f"/api/v1/apikey/{api_key_id}")

        # Print formatted output
        print(f"API Key deleted successfully")
        print(f"  API Key ID: {api_key_id}")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

    def bind_sessions(
        self,
        api_key_id: str,
        session_ids: List[str],
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Bind sessions to a user API key.

        Args:
            api_key_id: The API key ID to bind sessions to.
            session_ids: List of session IDs to bind.
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with bound session IDs.

        Raises:
            APIError: If the API returns an error.
            ValueError: If session_ids is empty.
        """
        if not session_ids:
            raise ValueError("At least one session ID is required")

        data = {
            "session_ids": session_ids,
        }

        result = self.post(f"/api/v1/apikey/{api_key_id}/sessions", json_data=data)

        bound_sessions = result.get("bound_sessions", []) if result else []

        # Print formatted output
        print(f"Sessions bound successfully")
        print(f"  API Key ID:     {api_key_id}")
        print(f"  Bound Sessions: {', '.join(bound_sessions)}")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

    def unbind_sessions(
        self,
        api_key_id: str,
        session_ids: List[str],
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Unbind sessions from a user API key.

        Args:
            api_key_id: The API key ID to unbind sessions from.
            session_ids: List of session IDs to unbind.
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with unbound session IDs.

        Raises:
            APIError: If the API returns an error.
            ValueError: If session_ids is empty.
        """
        if not session_ids:
            raise ValueError("At least one session ID is required")

        data = {
            "session_ids": session_ids,
        }

        result = self.delete(
            f"/api/v1/apikey/{api_key_id}/sessions",
            params=data
        )

        unbound_sessions = result.get("unbound_sessions", []) if result else []

        # Print formatted output
        print(f"Sessions unbound successfully")
        print(f"  API Key ID:       {api_key_id}")
        print(f"  Unbound Sessions: {', '.join(unbound_sessions)}")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

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

    def _print_api_key(self, api_key: Dict[str, Any]) -> None:
        """
        Print a single API key in formatted output.

        Args:
            api_key: API key dictionary to print.
        """
        create_time = self.format_time(api_key.get('create_time'))
        update_time = self.format_time(api_key.get('update_time'))
        api_key_id = api_key.get('api_key_id', 'N/A')
        name = api_key.get('name', 'N/A')
        role = api_key.get('role', 'N/A')
        rate_limit = api_key.get('rate_limit', 'N/A')
        is_active = api_key.get('is_active', 'N/A')

        print(SPLIT_LINE)
        print(f"[{create_time}] [{api_key_id}] {name}")
        print(f"  Role:       {role}")
        print(f"  Rate Limit: {rate_limit}")
        print(f"  Active:     {is_active}")
        print(f"  Updated:    {update_time}")

        sessions = api_key.get('sessions', [])
        environs = api_key.get('environs', [])

        print(f"  Sessions:   {sessions if sessions else '[]'}")
        if environs:
            print(f"  Environs:")
            for env in environs:
                print(f"    {env.get('key', 'N/A')}={env.get('value', 'N/A')}")
        else:
            print(f"  Environs:   (none)")

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
