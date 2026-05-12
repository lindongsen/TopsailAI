"""
API Key Do Functions

This module provides the do_xxx functions for API key management-related CLI operations.
These functions are used by the topsailai_agent_client CLI.

Functions:
    - do_client_set_api_key_environ: Set an environment variable for an API key
    - do_client_list_api_key_environs: List environment variables for an API key
    - do_client_delete_api_key_environ: Delete an environment variable for an API key
"""

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.client.api_key import ApiKeyClient


def do_client_set_api_key_environ(args):
    """Set an environment variable for an API key"""
    client = ApiKeyClient(
        base_url=f"http://{args.host}:{args.port}",
        api_key=getattr(args, 'api_key', None)
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
        api_key=getattr(args, 'api_key', None)
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
        api_key=getattr(args, 'api_key', None)
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
