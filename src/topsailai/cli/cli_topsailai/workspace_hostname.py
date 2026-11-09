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


def filter_workspace_rows_by_hostname(files: list[dict], local_hostname: str) -> list[dict]:
    """Keep only rows produced on the local host.

    A row is local when its resolved ``hostname`` equals ``local_hostname`` or is
    empty. An empty value means the origin host is unknown, which happens for a
    row whose metadata record is absent or carries no usable hostname; such a row
    is kept so a local session is never hidden merely because its metadata is
    missing. The comparison is exact and case-sensitive, because a hostname is an
    operating-system identifier rather than a display label.

    Args:
        files: Rows already enriched by ``enrich_workspace_hostnames``.
        local_hostname: The hostname of the machine running the CLI.

    Returns:
        The retained rows in their original order.
    """
    if not isinstance(local_hostname, str):
        return list(files)
    retained = []
    for row in files:
        hostname = row.get("hostname")
        # A non-string value is an unresolved origin, not a foreign host, so it
        # is kept for the same reason an empty value is kept.
        if not isinstance(hostname, str) or hostname in ("", local_hostname):
            retained.append(row)
    return retained
