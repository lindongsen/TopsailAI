'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-17
  Purpose: File path manipulation and file system utilities
'''

import os
import time
import fcntl
from pathlib import Path
from contextlib import contextmanager

from topsailai.logger import logger


##########################################################
# Core
##########################################################

def get_filename(file_path: str) -> str:
    """Extract the filename without extension from a file path.

    This function returns the stem (filename without the final extension)
    from a given file path. It handles both Unix and Windows path formats.

    Args:
        file_path: Full path to the file

    Returns:
        str: Filename without extension, or empty string for invalid input

    Examples:
        "/tmp/123.txt" -> "123"
        "C:\\data\\report.pdf" -> "report"
        "" -> ""
    """
    if not file_path:
        return ""
    return Path(file_path).stem

def match_file(
        file_path:str,
        to_exclude_dot_start:bool,
        excluded_starts:tuple,
        included_filename_keywords:list[str]=None,
        keyword_min_len=3,
    ) -> bool:
    """Check if a file path matches the specified filtering criteria.

    This function applies multiple filtering rules to determine if a file path
    should be included or excluded based on various criteria.

    Args:
        file_path: The file path to check
        to_exclude_dot_start: If True, exclude files starting with '.' or containing '/.'
        excluded_starts: Tuple of strings that should be excluded from the path
        included_filename_keywords: List of keywords that must be present in the filename
        keyword_min_len: Minimum length for keywords to be considered (default: 3)

    Returns:
        bool: True if the file matches all criteria, False otherwise

    Examples:
        >>> match_file("/tmp/.hidden/file.txt", True, (), None)
        False  # Excluded because of dot-start

        >>> match_file("/tmp/important_doc.txt", False, ("exclude",), ["important"])
        True   # Contains "important" keyword

        >>> match_file("/tmp/excluded/file.txt", False, ("excluded",), None)
        False  # Excluded because path contains "excluded"
    """
    if to_exclude_dot_start:
        if "/." in file_path:
            return False
        if file_path[0] == '.':
            return False

    if not excluded_starts:
        excluded_starts = tuple()

    for excluded_str_start in excluded_starts:
        if f"/{excluded_str_start}" in file_path:
            return False
        if file_path.startswith(excluded_str_start):
            return False

    if included_filename_keywords:
        for key in included_filename_keywords:
            key = key.strip()
            if not key:
                continue
            if len(key) < keyword_min_len:
                continue
            if key in file_path:
                return True
        return False

    return True


##########################################################
# Shell
##########################################################

def find_files_by_name(folder_path:str, file_name:str) -> list[str]:
    """Find all files with a specific name within a directory tree.

    This function recursively searches through a directory and all its
    subdirectories to find files with the specified name.

    Args:
        folder_path: Root directory path to search in
        file_name: Exact filename to search for

    Returns:
        list[str]: List of full paths to matching files

    Examples:
        >>> find_files_by_name("/tmp", "config.txt")
        ["/tmp/config.txt", "/tmp/subdir/config.txt"]

        >>> find_files_by_name("/tmp", "nonexistent.txt")
        []  # Empty list if no files found
    """
    results = []
    for root, dirs, files in os.walk(folder_path):
        if file_name in files:
            file_path = os.path.join(root, file_name)
            results.append(file_path)

    return results

def list_files(
        folder_path:str,
        to_exclude_dot_start:bool=True,
        excluded_starts:tuple=None,
        included_filename_keywords:list[str]=None,
    ) -> list[str]:
    """List files in a directory tree with filtering options.

    This function recursively lists files from a directory, applying various
    filtering criteria to include or exclude specific files based on their paths.

    Args:
        folder_path: Root directory to search
        to_exclude_dot_start: If True, exclude files starting with '.' (default: True)
        excluded_starts: Tuple of strings that should be excluded from file paths
        included_filename_keywords: List of keywords that must be present in filenames

    Returns:
        list[str]: List of full paths to matching files

    Note:
        - Both directory paths and filenames are filtered using match_file()
        - If included_filename_keywords is provided, only files containing
          at least one keyword will be included
    """
    results = []
    if not excluded_starts:
        excluded_starts = tuple()

    for root, dirs, files in os.walk(folder_path):
        if not match_file(
            root,
            to_exclude_dot_start=to_exclude_dot_start,
            excluded_starts=excluded_starts,
        ):
            continue
        for file in files:
            if not match_file(
                file,
                to_exclude_dot_start=to_exclude_dot_start,
                excluded_starts=excluded_starts,
                included_filename_keywords=included_filename_keywords,
            ):
                continue
            file_path = os.path.join(root, file)
            results.append(file_path)
    return results

def delete_file(file_path:str):
    """Safely delete a file if it exists.

    This function checks if a file exists before attempting to delete it,
    and logs the deletion operation for tracking purposes.

    Args:
        file_path: Path to the file to delete

    Returns:
        None: The function returns nothing, but logs the operation
    """
    if file_path and os.path.exists(file_path):
        logger.info("delete file: [%s]", file_path)
        os.unlink(file_path)
    return


def get_file_content_fuzzy(f:str) -> tuple[str, str]:
    """
    Args:
        f (str): file content or file path

    Returns:
        tuple[str, str]: (file_path, file_content)
    """
    file_path = ""
    file_content = ""

    if os.path.exists(f):
        file_path = f
    else:
        file_content = f

    if file_path:
        with open(file_path, encoding="utf-8") as fd:
            file_content = fd.read()

    return (file_path, file_content)


##########################################################
# Lock Shell
##########################################################
@contextmanager
def ctxm_file_lock(file_path, mode="w"):
    """Context manager for file locking using advisory locks.

    This context manager provides exclusive file locking using fcntl.flock.
    It ensures that only one process can write to the file at a time.

    Args:
        file_path: Path to the file to lock
        mode: File open mode (default: "w" for write)

    Yields:
        file: The locked file object

    Example:
        with ctxm_file_lock("/tmp/data.txt") as f:
            f.write("important data")
    """
    with open(file_path, mode) as file:
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX)
            yield file
        finally:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)
    return

@contextmanager
def ctxm_temp_file(file_content, mode="w"):
    """
    Args:
        file_content (str):
        mode (str, optional): Defaults to "w".

    Yields:
        tuple(file_path, fd)
    """
    file_path = None
    for _ in range(100):
        file_path = f"/tmp/{time.time()}"
        if not os.path.exists(file_path):
            break
        file_path = None

    try:
        with ctxm_file_lock(file_path, mode) as fd:
            fd.write(file_content)
            yield (file_path, fd)
    finally:
        delete_file(file_path)

    return
