"""Finite workspace driver operations using existing lifecycle safeguards.

Author: DawsonLin
"""

import argparse
import json
import logging
import os
from pathlib import Path
import sys

from cli_topsailai.formatting import enrich_workspace_rows
from cli_topsailai.log_files import discover_log_files
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.runtime_cli import RuntimeParser, RuntimeUsageError, UniqueValue
from cli_topsailai.session_driver import metadata_path
from cli_topsailai.session_driver_config import resolve_driver_authority
from cli_topsailai.session_driver_launcher import launch_driver, _row_identity, _target_alive
from cli_topsailai.session_driver_stopper import stop_driver

LOGGER = logging.getLogger(__name__)


class DriverTargetError(ValueError):
    """Distinguish target selection errors from configuration failures."""


def build_parser():
    """Build offline help without probing processes or installation authority."""
    parser = RuntimeParser(prog="topsailai workspace driver", allow_abbrev=False)
    parser.add_argument("action", choices=("start", "status", "stop"))
    parser.add_argument("-s", "--session", dest="session_id", required=True,
                        action=UniqueValue, default=argparse.SUPPRESS)
    parser.add_argument("-p", "--pid", type=int, action=UniqueValue,
                        default=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true")
    return parser


def _select(rows, session, pid, home, action):
    """Select exact authoritative rows, never choosing newest or task evidence."""
    candidates = []
    for row in rows:
        if row.get("session_id") != session or row.get("is_task"):
            continue
        try:
            _row_identity(row, home)
        except (ValueError, TypeError):
            continue
        candidates.append(row)
    live = [row for row in candidates if _target_alive(row["pid"])]
    if len({row["pid"] for row in live}) > 1:
        raise DriverTargetError("ambiguous_session")
    matches = live if action == "start" else candidates
    if pid is not None:
        matches = [row for row in matches if row["pid"] == pid]
    if len(matches) != 1:
        raise DriverTargetError("ambiguous_target" if matches else "target_not_current")
    return rows.index(matches[0]) + 1


def _snapshot(observation):
    """Expose semantic evidence, not display emoticons or child handles."""
    if observation is None:
        return None
    return dict(state=observation.state, reason=observation.reason,
                driver_pid=observation.driver_pid, run_id=observation.run_id,
                metadata_status=observation.metadata.status if observation.metadata else None,
                verification=observation.verification.value)


def run_workspace_driver_cli(argv, *, environment=None, home_resolver=None):
    """Execute once and report runtime-style results without interactive setup."""
    result = dict(ok=False, exit_code=2, action="", session_id=None, pid=None,
                  delivery_state=None, error_code=None, message="",
                  bytes_written=None, request_id=None, response=None,
                  delivery_unknown=False)
    json_mode = "--json" in argv
    try:
        args = build_parser().parse_args(argv)
        json_mode = args.json
        result.update(action=args.action, session_id=args.session_id,
                      pid=getattr(args, "pid", None))
        if result["pid"] is not None and result["pid"] <= 0:
            raise RuntimeUsageError("Invalid PID")
        # Validate syntax independently of installation and discovery.
        try:
            metadata_path(Path("/"), args.session_id)
        except ValueError as error:
            raise RuntimeUsageError("Invalid session") from error
        home = Path((home_resolver or get_topsailai_home)())
        env = dict(os.environ if environment is None else environment)
        authority = resolve_driver_authority(env)

        def discover():
            """Reuse workspace discovery for initial and pre-spawn validation."""
            return discover_log_files(str(home / "workspace" / "task"))

        rows = discover()
        index = _select(rows, args.session_id, result["pid"], home, args.action)
        result["pid"] = rows[index - 1]["pid"]
        if args.action == "start":
            launched = launch_driver(rows, index, topsailai_home=home,
                                     authority=authority, environment=env, discover=discover)
            code = {"launched": 0, "already_running": 0, "rejected": 4,
                    "failed": 5, "unconfirmed": 6}[launched.outcome]
            result.update(exit_code=code, ok=code == 0,
                          delivery_state=launched.outcome,
                          error_code=None if code == 0 else launched.reason,
                          message=launched.reason, response=_snapshot(launched.observation),
                          delivery_unknown=launched.outcome == "unconfirmed")
        elif args.action == "stop":
            stopped = stop_driver(rows, index, topsailai_home=home,
                                  authority=authority, discover=discover)
            code = {"stopped": 0, "already_stopped": 0, "rejected": 4,
                    "failed": 5, "unconfirmed": 6}[stopped.outcome]
            result.update(exit_code=code, ok=code == 0,
                          delivery_state=stopped.outcome,
                          error_code=None if code == 0 else stopped.reason,
                          message=stopped.reason, response=_snapshot(stopped.observation),
                          delivery_unknown=stopped.outcome == "unconfirmed")
        else:
            fresh = discover()
            index = _select(fresh, args.session_id, result["pid"], home, "status")
            enrich_workspace_rows(fresh, str(home), driver_entry=authority.entry)
            observation = fresh[index - 1].get("driver_observation")
            if observation is None:
                raise DriverTargetError("ineligible_or_changed_row")
            result.update(ok=observation.state != "?",
                          exit_code=4 if observation.state == "?" else 0,
                          delivery_state="status_read", response=_snapshot(observation),
                          error_code=observation.reason if observation.state == "?" else None,
                          message=observation.reason)
    except RuntimeUsageError:
        result.update(exit_code=2, error_code="usage_error", message="Invalid driver arguments")
    except DriverTargetError as error:
        result.update(exit_code=3, error_code=str(error), message="No unique eligible session")
    except (ValueError, OSError) as error:
        LOGGER.warning("Workspace driver operation failed: type=%s", type(error).__name__, exc_info=True)
        result.update(exit_code=4, error_code="configuration_or_inspection_failed",
                      message="Driver configuration or inspection unavailable")
    if json_mode:
        print(json.dumps(result, ensure_ascii=True))
    elif result["ok"]:
        print(f"Driver {result['action']}: {result['delivery_state']}; {result['response']}")
    else:
        print(f"Driver failed: {result['error_code']} (exit {result['exit_code']})", file=sys.stderr)
    return result["exit_code"]
