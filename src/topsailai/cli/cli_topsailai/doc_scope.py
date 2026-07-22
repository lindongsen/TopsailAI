"""Doc scope: list and read documentation files under docs/."""

import os
from typing import Any, Dict, List, Optional, Tuple

from cli_topsailai import formatting


def get_docs_dir() -> str:
    """Return the absolute path to the documentation root directory.

    The path is resolved relative to this module so it stays portable across
    deployments and does not rely on hard-coded absolute paths.
    """
    module_dir = os.path.dirname(os.path.abspath(__file__))
    cli_dir = os.path.dirname(module_dir)
    return os.path.abspath(os.path.join(cli_dir, "docs"))


def get_usage_docs_dir() -> str:
    """Return the absolute path to the usage documentation directory.

    Kept for backward compatibility. New code should use :func:`get_docs_dir`.
    """
    return os.path.join(get_docs_dir(), "usage")


def _is_valid_doc_folder(docs_dir: str, folder_path: str) -> bool:
    """Check whether ``folder_path`` is a direct single-level subfolder of docs."""
    if not os.path.isdir(folder_path):
        return False
    parent = os.path.dirname(folder_path)
    return os.path.samefile(parent, docs_dir)


def _discover_doc_folders(docs_dir: str) -> List[str]:
    """Return sorted names of single-level subfolders under ``docs_dir``."""
    if not os.path.isdir(docs_dir):
        return []
    folders = []
    for name in os.listdir(docs_dir):
        folder_path = os.path.join(docs_dir, name)
        if _is_valid_doc_folder(docs_dir, folder_path):
            folders.append(name)
    folders.sort()
    return folders


def _list_docs_in_folder(folder_path: str) -> List[Dict[str, Any]]:
    """Return metadata for all ``.md`` files (including symlinks) in a folder."""
    entries = []
    for filename in os.listdir(folder_path):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(folder_path, filename)
        if not os.path.isfile(filepath):
            continue
        stat = os.stat(filepath)
        title = _extract_title(filepath) or filename
        entries.append(
            {
                "filename": filename,
                "title": title,
                "size_bytes": stat.st_size,
                "created": stat.st_ctime,
                "folder": os.path.basename(folder_path),
                "rel_path": f"{os.path.basename(folder_path)}/{filename}",
                "path": filepath,
            }
        )
    return entries


def build_doc_list() -> List[Dict[str, Any]]:
    """Build a list of documentation files under ``docs/``.

    Files are discovered in every single-level subfolder of ``docs/`` (for
    example ``usage/`` and ``memo/``). Symbolic links to ``.md`` files are
    followed. The returned list is sorted by creation time, oldest first,
    with alphabetical tie-breaking, and each entry receives a global
    ``row_number``.

    Returns a list of dicts with keys:
        row_number, folder, filename, rel_path, path, title, size_bytes, created
    """
    docs_dir = get_docs_dir()
    folders = _discover_doc_folders(docs_dir)

    entries = []
    for folder in folders:
        folder_path = os.path.join(docs_dir, folder)
        entries.extend(_list_docs_in_folder(folder_path))

    entries.sort(key=lambda item: (item["created"], item["folder"], item["filename"]))
    for idx, entry in enumerate(entries):
        entry["row_number"] = idx + 1
    return entries


def _extract_title(filepath: str) -> Optional[str]:
    """Extract the first Markdown H1 title from a file, if present."""
    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[2:].strip()
    except (OSError, UnicodeDecodeError):
        pass
    return None


def print_doc_table(docs: List[Dict[str, Any]]) -> None:
    """Print a numbered table of documentation files grouped by folder."""
    if not docs:
        print("No documentation files found.")
        return

    headers = ["No", "Folder", "Name", "Title", "Size"]
    rows = []
    for entry in docs:
        rows.append(
            [
                str(entry["row_number"]),
                str(entry["folder"]),
                str(entry["filename"]),
                str(entry["title"]),
                formatting.format_size(int(entry["size_bytes"])),
            ]
        )
    formatting.print_simple_table(headers, rows)


def _normalize_doc_name(name: str) -> str:
    """Strip leading/trailing whitespace and optional ``.md`` suffix."""
    name = name.strip()
    if name.endswith(".md"):
        name = name[:-3]
    return name


def _resolve_exact_path(name: str) -> Optional[str]:
    """Resolve a ``folder/document.md`` style name to an absolute path.

    Returns the absolute path if it exists and stays inside ``docs/``,
    otherwise ``None``.
    """
    docs_dir = get_docs_dir()
    # Normalize separators so the traversal check is reliable.
    normalized = os.path.normpath(name)
    if normalized.startswith("..") or os.path.isabs(normalized):
        return None
    filepath = os.path.abspath(os.path.join(docs_dir, normalized))
    if not filepath.startswith(docs_dir + os.sep):
        return None
    if not os.path.isfile(filepath):
        return None
    return filepath


def _read_file(filepath: str) -> Optional[str]:
    """Read a file's contents, returning ``None`` on error."""
    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def resolve_doc(name: str) -> Dict[str, Any]:
    """Resolve a documentation name to content or a conflict/not-found status.

    Supported input formats:
        - ``folder/document.md`` — exact path within ``docs/``.
        - ``document`` or ``document.md`` — bare document name; if the name
          exists in multiple folders, a conflict is reported.

    Returns a dict with keys:
        - ``status``: ``"ok"``, ``"conflict"``, or ``"not_found"``.
        - ``content``: file content when ``status == "ok"``, else ``None``.
        - ``path``: resolved absolute path when ``status == "ok"``, else ``None``.
        - ``rel_path``: ``folder/filename`` when ``status == "ok"``, else ``None``.
        - ``options``: list of ``folder/filename.md`` strings when
          ``status == "conflict"``, else ``None``.
    """
    name = name.strip()
    if not name:
        return {"status": "not_found", "content": None, "path": None, "rel_path": None, "options": None}

    # Exact folder/document.md form.
    if "/" in name or "\\" in name:
        filepath = _resolve_exact_path(name)
        if filepath is None:
            return {"status": "not_found", "content": None, "path": None, "rel_path": None, "options": None}
        content = _read_file(filepath)
        if content is None:
            return {"status": "not_found", "content": None, "path": None, "rel_path": None, "options": None}
        rel_path = os.path.relpath(filepath, get_docs_dir())
        return {
            "status": "ok",
            "content": content,
            "path": filepath,
            "rel_path": rel_path,
            "options": None,
        }

    # Bare name: search all doc folders.
    base_name = _normalize_doc_name(name)
    docs = build_doc_list()
    matches = [doc for doc in docs if _normalize_doc_name(doc["filename"]) == base_name]

    if not matches:
        return {"status": "not_found", "content": None, "path": None, "rel_path": None, "options": None}
    if len(matches) == 1:
        doc = matches[0]
        content = _read_file(doc["path"])
        if content is None:
            return {"status": "not_found", "content": None, "path": None, "rel_path": None, "options": None}
        return {
            "status": "ok",
            "content": content,
            "path": doc["path"],
            "rel_path": doc["rel_path"],
            "options": None,
        }

    options = [doc["rel_path"] for doc in matches]
    return {
        "status": "conflict",
        "content": None,
        "path": None,
        "rel_path": None,
        "options": options,
    }


def read_doc_file(name: str) -> Optional[str]:
    """Read the contents of a documentation file.

    ``name`` may be ``folder/document.md`` or a bare document name. When the
    bare name is ambiguous, ``None`` is returned. Callers that need to report
    conflicts should use :func:`resolve_doc` instead.

    Returns the file content as a string, or ``None`` if the file cannot be
    read or is ambiguous.
    """
    result = resolve_doc(name)
    if result["status"] == "ok":
        return result["content"]
    return None


def refresh_doc_list() -> List[Dict[str, Any]]:
    """Refresh and return the current list of documentation files."""
    return build_doc_list()
