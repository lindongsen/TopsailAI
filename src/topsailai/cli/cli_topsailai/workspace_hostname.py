"""Resolve workspace hostname cells from exact session metadata only.

Author: DawsonLin
"""

from cli_topsailai import session_meta


def _row_owns_filename(row: dict) -> bool:
    """Report whether the row's filename was written by the row's own PID.

    A session process writes ``{session}.{pid}.session.stdout`` and a task agent
    writes ``{session}.{pid}[.{task_id}].task.stdout``. Both files are created
    by the process whose PID they carry, so the filename is the evidence that
    ties a row to one exact metadata record. A row whose filename does not carry
    its own PID has no record of its own and must not borrow another process's.
    """
    sid, pid = row.get("session_id"), row.get("pid")
    filename = row.get("filename")
    if not isinstance(sid, str) or not sid or type(pid) is not int or pid <= 0:
        return False
    if not isinstance(filename, str):
        return False
    prefix = "topsailai" if sid == "(temp)" else sid
    if row.get("is_task"):
        return filename.startswith(f"{prefix}.{pid}.") and filename.endswith(".task.stdout")
    return filename in (f"{prefix}.{pid}.session.stdout",
                        f"{prefix}.{pid}.session.stderr")


def enrich_workspace_hostnames(files: list[dict], home: str) -> None:
    """Reuse discovery snapshots and read each exact session at most once."""
    cache = {}
    for row in files:
        snapshot = row.get("_workspace_meta_snapshot")
        if snapshot is not None and snapshot[0] == home:
            cache[(snapshot[1], snapshot[2])] = snapshot[3]

    for row in files:
        sid, pid = row.get("session_id"), row.get("pid")
        row["hostname"] = ""
        row["_workspace_session_meta_data"] = None
        if not _row_owns_filename(row):
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
