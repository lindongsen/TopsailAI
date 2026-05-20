"""
API Key Do Functions

This module provides the do_xxx functions for API key management-related CLI operations.
These functions are used by the topsailai_agent_client CLI.

Functions:
    - do_client_create_api_key: Create a new API key
    - do_client_list_api_keys: List API keys
    - do_client_delete_api_key: Delete an API key
    - do_client_bind_sessions: Bind sessions to an API key
    - do_client_unbind_sessions: Unbind sessions from an API key
    - do_client_set_api_key_environ: Set an environment variable for an API key
    - do_client_list_api_key_environs: List environment variables for an API key
    - do_client_delete_api_key_environ: Delete an environment variable for an API key
"""

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.client.api_key import ApiKeyClient


def do_client_create_api_key(args):
    """Create a new API key"""
    client = ApiKeyClient(
        base_url=f"http://{args.host}:{args.port}",
        api_key=getattr(args, 'api_key', None),
        auth_header_style=getattr(args, 'auth_style', 'x-api-key')
    )

    try:
        logger.info(
            "Creating API key: name=%s, role=%s, rate_limit=%s",
            args.name, args.role, args.rate_limit
        )

        session_ids = None
        if args.session_ids:
            session_ids = [s.strip() for s in args.session_ids.split(',') if s.strip()]

        client.create_api_key(
            name=args.name,
            role=args.role,
            rate_limit=args.rate_limit,
            session_ids=session_ids,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to create API key: %s", e)
        print(f"Error: {e}")
        return False


def do_client_list_api_keys(args):
    """List API keys"""
    client = ApiKeyClient(
        base_url=f"http://{args.host}:{args.port}",
        api_key=getattr(args, 'api_key', None),
        auth_header_style=getattr(args, 'auth_style', 'x-api-key')
    )

    try:
        logger.info("Listing API keys")
        client.list_api_keys(
            session_id=getattr(args, 'session_id', None),
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to list API keys: %s", e)
        print(f"Error: {e}")
        return False


def do_client_delete_api_key(args):
    """Delete an API key"""
    client = ApiKeyClient(
        base_url=f"http://{args.host}:{args.port}",
        api_key=getattr(args, 'api_key', None),
        auth_header_style=getattr(args, 'auth_style', 'x-api-key')
    )

    try:
        logger.info("Deleting API key %s", args.api_key_id)
        client.delete_api_key(
            api_key_id=args.api_key_id,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to delete API key: %s", e)
        print(f"Error: {e}")
        return False


def do_client_bind_sessions(args):
    """Bind sessions to an API key"""
    client = ApiKeyClient(
        base_url=f"http://{args.host}:{args.port}",
        api_key=getattr(args, 'api_key', None),
        auth_header_style=getattr(args, 'auth_style', 'x-api-key')
    )

    session_ids = [s.strip() for s in args.session_ids.split(',') if s.strip()]
    if not session_ids:
        print("Error: At least one session ID is required")
        return False

    try:
        logger.info(
            "Binding sessions to API key %s: %s",
            args.api_key_id, session_ids
        )
        client.bind_sessions(
            api_key_id=args.api_key_id,
            session_ids=session_ids,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to bind sessions: %s", e)
        print(f"Error: {e}")
        return False


def do_client_unbind_sessions(args):
    """Unbind sessions from an API key"""
    client = ApiKeyClient(
        base_url=f"http://{args.host}:{args.port}",
        api_key=getattr(args, 'api_key', None),
        auth_header_style=getattr(args, 'auth_style', 'x-api-key')
    )

    session_ids = [s.strip() for s in args.session_ids.split(',') if s.strip()]
    if not session_ids:
        print("Error: At least one session ID is required")
        return False

    try:
        logger.info(
            "Unbinding sessions from API key %s: %s",
            args.api_key_id, session_ids
        )
        client.unbind_sessions(
            api_key_id=args.api_key_id,
            session_ids=session_ids,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to unbind sessions: %s", e)
        print(f"Error: {e}")
        return False


def do_client_set_api_key_environ(args):
    """Set an environment variable for an API key"""
    client = ApiKeyClient(
        base_url=f"http://{args.host}:{args.port}",
        api_key=getattr(args, 'api_key', None),
        auth_header_style=getattr(args, 'auth_style', 'x-api-key')
    )

    try:
        logger.info(
            "Setting environment variable for API key %s: %s=%s",
            args.api_key_id, args.key, args.value
        )
        client.set_api_key_environ(
            api_key_id=args.api_key_id,
            key=args.key,
            value=args.value,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to set API key environment variable: %s", e)
        print(f"Error: {e}")
        return False


def do_client_list_api_key_environs(args):
    """List environment variables for an API key"""
    client = ApiKeyClient(
        base_url=f"http://{args.host}:{args.port}",
        api_key=getattr(args, 'api_key', None),
        auth_header_style=getattr(args, 'auth_style', 'x-api-key')
    )

    try:
        logger.info("Listing environment variables for API key %s", args.api_key_id)
        client.list_api_key_environs(
            api_key_id=args.api_key_id,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to list API key environment variables: %s", e)
        print(f"Error: {e}")
        return False


def do_client_delete_api_key_environ(args):
    """Delete an environment variable for an API key"""
    client = ApiKeyClient(
        base_url=f"http://{args.host}:{args.port}",
        api_key=getattr(args, 'api_key', None),
        auth_header_style=getattr(args, 'auth_style', 'x-api-key')
    )

    try:
        logger.info(
            "Deleting environment variable %s for API key %s",
            args.key, args.api_key_id
        )
        client.delete_api_key_environ(
            api_key_id=args.api_key_id,
            key=args.key,
            verbose=args.verbose
        )
        return True
    except Exception as e:
        logger.exception("Failed to delete API key environment variable: %s", e)
        print(f"Error: {e}")
        return False


def add_api_key_parsers(subparsers):
    """Add API key management-related subparsers to the argument parser

    Args:
        subparsers: The subparsers object from argparse
    """
    # Create API key
    create_parser = subparsers.add_parser(
        'create-api-key',
        help='Create a new API key'
    )
    create_parser.add_argument(
        '--name', type=str, required=True,
        help='Human-readable name for the key (required)'
    )
    create_parser.add_argument(
        '--role', type=str, default='user', choices=['admin', 'user'],
        help='Role of the key (default: user)'
    )
    create_parser.add_argument(
        '--rate-limit', type=int, default=0,
        help='Max messages per minute, 0=unlimited (default: 0)'
    )
    create_parser.add_argument(
        '--session-ids', type=str,
        help='Comma-separated session IDs to bind (user role only)'
    )
    create_parser.set_defaults(func=do_client_create_api_key)

    # List API keys
    list_parser = subparsers.add_parser(
        'list-api-keys',
        help='List API keys'
    )
    list_parser.add_argument(
        '--session-id', type=str,
        help='Filter API keys by bound session ID'
    )
    list_parser.set_defaults(func=do_client_list_api_keys)

    # Delete API key
    delete_parser = subparsers.add_parser(
        'delete-api-key',
        help='Delete an API key'
    )
    delete_parser.add_argument(
        '--api-key-id', type=str, required=True,
        help='API key ID to delete (required)'
    )
    delete_parser.set_defaults(func=do_client_delete_api_key)

    # Bind sessions
    bind_parser = subparsers.add_parser(
        'bind-sessions',
        help='Bind sessions to an API key'
    )
    bind_parser.add_argument(
        '--api-key-id', type=str, required=True,
        help='API key ID (required)'
    )
    bind_parser.add_argument(
        '--session-ids', type=str, required=True,
        help='Comma-separated session IDs to bind (required)'
    )
    bind_parser.set_defaults(func=do_client_bind_sessions)

    # Unbind sessions
    unbind_parser = subparsers.add_parser(
        'unbind-sessions',
        help='Unbind sessions from an API key'
    )
    unbind_parser.add_argument(
        '--api-key-id', type=str, required=True,
        help='API key ID (required)'
    )
    unbind_parser.add_argument(
        '--session-ids', type=str, required=True,
        help='Comma-separated session IDs to unbind (required)'
    )
    unbind_parser.set_defaults(func=do_client_unbind_sessions)

    # Set API key environ
    set_environ_parser = subparsers.add_parser(
        'set-api-key-environ',
        help='Set an environment variable for an API key'
    )
    set_environ_parser.add_argument(
        '--api-key-id', type=str, required=True,
        help='API key ID (required)'
    )
    set_environ_parser.add_argument(
        '--key', type=str, required=True,
        help='Environment variable name (required)'
    )
    set_environ_parser.add_argument(
        '--value', type=str, required=True,
        help='Environment variable value (required)'
    )
    set_environ_parser.set_defaults(func=do_client_set_api_key_environ)

    # List API key environs
    list_environs_parser = subparsers.add_parser(
        'list-api-key-environs',
        help='List environment variables for an API key'
    )
    list_environs_parser.add_argument(
        '--api-key-id', type=str, required=True,
        help='API key ID (required)'
    )
    list_environs_parser.set_defaults(func=do_client_list_api_key_environs)

    # Delete API key environ
    delete_environ_parser = subparsers.add_parser(
        'delete-api-key-environ',
        help='Delete an environment variable for an API key'
    )
    delete_environ_parser.add_argument(
        '--api-key-id', type=str, required=True,
        help='API key ID (required)'
    )
    delete_environ_parser.add_argument(
        '--key', type=str, required=True,
        help='Environment variable name to delete (required)'
    )
    delete_environ_parser.set_defaults(func=do_client_delete_api_key_environ)
