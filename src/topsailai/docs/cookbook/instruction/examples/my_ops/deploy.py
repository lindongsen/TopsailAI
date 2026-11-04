"""Deployment helpers exposed as /deploy.* slash instructions."""

# Dict form: the key is the action name, so this module registers
# /deploy.status and /deploy.rollback.

import os


def status(service: str = "") -> str:
    """Report the deployment status of one service."""
    if not service:
        return "Usage: /deploy.status <service>"
    env = os.getenv("MY_OPS_ENV", "dev")
    return f"{service}: running (env={env})"


def rollback(service: str = "", revision: str = "") -> str:
    """Roll one service back to a revision."""
    if not service or not revision:
        return "Usage: /deploy.rollback <service> <revision>"
    return f"{service}: rolled back to {revision}"


INSTRUCTIONS = {
    "status": status,
    "rollback": rollback,
}
