"""Resolve workspace hostname cells from exact session metadata only.

Author: DawsonLin
"""

from cli_topsailai import session_meta


def enrich_workspace_hostnames(files: list[dict], home: str) -> None:
    """Reuse discovery snapshots and read each exact session at most once."""
    owners = {}
    for row in files:
        sid, pid = row.get("session_id"), row.get("pid")
        filename_sid = "topsailai" if sid == "(temp)" else sid
        if (not row.get("is_task") and type(pid) is int and pid > 0
                and row.get("filename") in (
                    f"{filename_sid}.{pid}.session.stdout", f"{filename_sid}.{pid}.session.stderr")):
            owners.setdefault(sid, set()).add(pid)

    cache = {}
    for row in files:
        snapshot = row.get("_workspace_meta_snapshot")
        if snapshot is not None and snapshot[0] == home:
            cache[(snapshot[1], snapshot[2])] = snapshot[3]

    for row in files:
        sid, pid = row.get("session_id"), row.get("pid")
        row["hostname"] = ""
        row["_workspace_session_meta_data"] = None
        if row.get("is_task"):
            candidates = owners.get(sid, set())
            pid = (next(iter(candidates)) if len(candidates) == 1 else None)
            # Discovery retains ambiguity even when filtering removes a parent.
            if "_workspace_meta_pid" in row:
                pid = row["_workspace_meta_pid"]
        elif row.get("filename") not in (
                f"{'topsailai' if sid == '(temp)' else sid}.{pid}.session.stdout",
                f"{'topsailai' if sid == '(temp)' else sid}.{pid}.session.stderr"):
            continue
        if sid == "(temp)":
            continue
        if not isinstance(sid, str) or not sid or type(pid) is not int or pid <= 0:
            continue
        key = (sid, pid)
        if key not in cache:
            try:
                cache[key] = session_meta.read_session_meta(home, sid, pid).data
            except session_meta.SessionMetaError:
                # The hardened reader diagnoses genuine errors, not absence.
                cache[key] = None
        data = cache[key]
        row["_workspace_session_meta_data"] = data
        if data is not None and isinstance(data.get("hostname"), str):
            row["hostname"] = data["hostname"]
