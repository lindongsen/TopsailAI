"""Doc scope: list and read usage documentation files."""

import os
from typing import Dict, List, Optional

from cli_topsailai import formatting


def get_usage_docs_dir() -> str:
    """Return the absolute path to the usage documentation directory.

    The path is resolved relative to this module so it stays portable across
    deployments and does not rely on hard-coded absolute paths.
    """
    module_dir = os.path.dirname(os.path.abspath(__file__))
    cli_dir = os.path.dirname(module_dir)
    return os.path.abspath(os.path.join(cli_dir, "docs", "usage"))


def build_doc_list() -> List[Dict[str, object]]:
    """Build a list of usage documentation files.

    Returns a list of dicts with keys:
        row_number, filename, title, size_bytes, created

    Files are sorted by creation time (oldest first, newest last) to match the
    workspace task list convention.
    """
    docs_dir = get_usage_docs_dir()
    if not os.path.isdir(docs_dir):
        return []

    entries = []
    for filename in os.listdir(docs_dir):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(docs_dir, filename)
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
            }
        )

    entries.sort(key=lambda item: item["created"])
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


def print_doc_table(docs: List[Dict[str, object]]) -> None:
    """Print a numbered table of usage documentation files."""
    if not docs:
        print("No usage documentation found.")
        return

    headers = ["No", "Name", "Title", "Size"]
    rows = []
    for entry in docs:
        rows.append(
            [
                str(entry["row_number"]),
                str(entry["filename"]),
                str(entry["title"]),
                formatting.format_size(int(entry["size_bytes"])),
            ]
        )
    formatting.print_simple_table(headers, rows)


def read_doc_file(filename: str) -> Optional[str]:
    """Read the contents of a usage documentation file.

    Returns the file content as a string, or None if the file cannot be read.
    """
    docs_dir = get_usage_docs_dir()
    filepath = os.path.abspath(os.path.join(docs_dir, filename))
    # Prevent path traversal outside the usage docs directory.
    if not filepath.startswith(docs_dir + os.sep):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def refresh_doc_list() -> List[Dict[str, object]]:
    """Refresh and return the current list of usage documentation files."""
    return build_doc_list()
