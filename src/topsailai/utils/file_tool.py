'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-17
  Purpose: File path manipulation and file system utilities
'''

import os
import time
import fcntl
import shutil
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
        "" -> ""
    """
    if not file_path:
        return ""
    filename = os.path.basename(file_path)
    return os.path.splitext(filename)[0]

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
    if not f:
        return ("", "")

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

def write_text(file_path:str, file_content:str):
    """
    Write text to file

    Args:
        file_path (str): _description_
        file_content (str): _description_
    """

    # folder
    folder_path = os.path.dirname(file_path)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path, exist_ok=True)

    # file
    if os.path.exists(file_path):
        logger.warning("exists file and overwrite it: [%s]", file_path)
    with open(file_path, mode='w', encoding='utf-8') as fp:
        fp.write(file_content)
        fp.flush()
    return

def append_data(file_path: str, data: any) -> bool:
    """
    Append data to a file (supports both text and binary).

    Args:
        file_path: Path to the file
        data: Data to append (str, bytes, or any serializable type)

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        # Determine mode based on data type
        if isinstance(data, bytes):
            mode = 'ab'  # Append binary
            # Don't convert bytes to string
        elif isinstance(data, str):
            mode = 'a'   # Append text
        else:
            # For other types, try bytes first, fallback to string
            mode = 'ab'
            data = str(data).encode('utf-8')

        # Append data to file
        with open(file_path, mode, encoding='utf-8' if 'b' not in mode else None) as file:
            file.write(data)
            file.flush()

        return True

    except (IOError, OSError, PermissionError, UnicodeEncodeError) as e:
        logger.error("Error appending to file: %s", e)
        return False


def get_all_files(args:list[str]) -> tuple[bool, list[str]]:
    """
    Get all of files from args.

    Args:
        args (list[str]):

    Returns:
        tuple: (all_of_args_are_file, all_files_from_args)
    """
    if not args:
        return (False, [])

    _flag_all_files = True
    all_files = []
    for _arg in args:
        _arg = _arg.strip()

        if not _arg:
            continue

        if _arg[0] != '/':
            _flag_all_files = False
            continue

        if not os.path.exists(_arg):
            _flag_all_files = False
            continue

        all_files.append(_arg)

    if not all_files:
        return (False, [])

    return (_flag_all_files, all_files)


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
def ctxm_try_file_lock(file_path, mode="w"):
    """ yield file object for locked, None for unlocked """
    with open(file_path, mode) as file:
        flag_locked = False
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            flag_locked = True
        except Exception:
            # locked by other process
            flag_locked = False

        try:
            yield file if flag_locked else None
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
        file_path = f"/tmp/topsailai.{time.time()}"
        if not os.path.exists(file_path):
            break
        file_path = None

    try:
        with ctxm_file_lock(file_path, mode) as fd:
            fd.write(file_content)
            fd.flush()
            yield (file_path, fd)
    finally:
        delete_file(file_path)

    return

@contextmanager
def ctxm_wait_flock(file_path, timeout=60, to_delete_lock_file=True):
    """ yield file object for locked, None for unlocked """
    if not file_path:
        yield None
        return

    timeout = int(timeout)
    if timeout <= 0:
        timeout = 1

    logger.debug("waiting flock: [%s] [%s]", file_path, timeout)

    start_time = int(time.time())
    end_time = start_time + timeout
    while time.time() < end_time:
        with ctxm_try_file_lock(file_path) as fp:
            if not fp:
                time.sleep(0.1)
                continue

            logger.debug("wait flock OK: [%s] [%s]", file_path, timeout)
            try:
                yield fp
            finally:
                logger.debug("free flock: [%s]", file_path)
                if to_delete_lock_file:
                    delete_file(file_path)
            return

    # timeout
    logger.warning("wait flock timeout: [%s] [%s]", file_path, timeout)
    yield None

    return

@contextmanager
def ctxm_backup_file(file_path):
    """Context manager that rotates backups and copies the given file to .bak0.

    Rotates existing backup files (.bak0 through .bak8) upward by one index,
    dropping the oldest .bak9 if it exists. Then copies the source file to
    a fresh .bak0. Keeps at most 10 backup files per source file.

    If the source file does not exist, yields None and skips backup.

    Args:
        file_path (str): Full path to the file to back up.

    Yields:
        str or None: Full path to the new .bak0 backup file, or None if the
                     source file does not exist.

    Examples:
        >>> with ctxm_backup_file("/tmp/config.json") as bak:
        ...     if bak:
        ...         print(f"backup created: {bak}")
        backup created: /tmp/config.json.bak0
    """

    if not os.path.exists(file_path):
        yield None
        return

    # Rotate existing backups outward: bak8->bak9, ..., bak0->bak1
    for i in range(8, -1, -1):
        old_path = f"{file_path}.bak{i}"
        new_path = f"{file_path}.bak{i + 1}"
        if os.path.exists(old_path):
            os.replace(old_path, new_path)

    bak_file_path = f"{file_path}.bak0"
    shutil.copy2(file_path, bak_file_path)
    yield bak_file_path
    return
