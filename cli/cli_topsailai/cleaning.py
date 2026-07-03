"""Log file cleanup helpers for the TopsailAI CLI."""

import os
import time
from typing import List

from cli_topsailai.colors import Colors, colored, cprint
from cli_topsailai.formatting import format_size, format_timestamp_full, print_header
from cli_topsailai.log_files import get_file_pid


def clean_expired_files(task_dir: str, files: List[dict]) -> int:
    """Clean up .stdout log files that are idle and older than 3 days.

    Shows a confirmation prompt before deletion.

    Args:
        task_dir: Directory containing the log files.
        files: List of file metadata dictionaries.

    Returns:
        Number of files deleted.
    """
    now = time.time()
    threshold_seconds = 3 * 24 * 60 * 60  # 72 hours

    expired_files = []
    for f in files:
        if not os.path.isfile(f["path"]):
            continue

        try:
            mtime = os.path.getmtime(f["path"])
        except OSError:
            continue

        age = now - mtime
        if age <= threshold_seconds:
            continue

        pid = get_file_pid(f["path"])
        if pid is not None:
            continue

        expired_files.append({
            "filename": f["filename"],
            "path": f["path"],
            "size": os.path.getsize(f["path"]),
            "mtime": mtime,
            "age_hours": age / 3600,
        })

    if not expired_files:
        cprint(
            "\n[INFO] No expired .stdout files found. "
            "(Files must be idle and older than 3 days)",
            color=Colors.GREEN,
        )
        return 0

    print_header("Clean Expired Log Files")
    cprint(
        f"[WARN] The following {len(expired_files)} file(s) are idle "
        "and older than 3 days:\n",
        color=Colors.YELLOW,
    )

    w_no = 4
    w_name = 32
    w_size = 10
    w_time = 20
    w_age = 12

    header = (
        f"{colored('', Colors.WHITE, bold=True, bg=Colors.BG_BLUE)}"
        f" {'No':^{w_no}} |"
        f" {'Filename':^{w_name}} |"
        f" {'Size':^{w_size}} |"
        f" {'Modified':^{w_time}} |"
        f" {'Age':^{w_age}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_size + 2)}+"
        f"{'-' * (w_time + 2)}+"
        f"{'-' * (w_age + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for idx, ef in enumerate(expired_files, start=1):
        name = ef["filename"]
        if len(name) > w_name:
            name = name[:w_name - 3] + "..."

        size_str = format_size(ef["size"])
        time_str = format_timestamp_full(ef["mtime"])
        age_str = f"{ef['age_hours']:.1f}h"

        row = (
            f"{Colors.GRAY}"
            f" {idx:^{w_no}} |"
            f" {name:<{w_name}} |"
            f" {size_str:>{w_size}} |"
            f" {time_str:^{w_time}} |"
            f" {age_str:>{w_age}} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)

    confirm_prompt = (
        f"\n{colored('', Colors.YELLOW, bold=True)}"
        f"Are you sure you want to delete these {len(expired_files)} file(s)? [y/N]: "
        f"{Colors.RESET}"
    )
    try:
        confirm = input(confirm_prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        cprint("\n[INFO] Clean cancelled.", color=Colors.YELLOW)
        return 0

    if confirm not in ("y", "yes"):
        cprint("[INFO] Clean cancelled.", color=Colors.YELLOW)
        return 0

    deleted_count = 0
    failed_files = []

    for ef in expired_files:
        try:
            os.remove(ef["path"])
            deleted_count += 1
            cprint(f"[OK] Deleted: {ef['filename']}", color=Colors.GREEN)
        except OSError as e:
            failed_files.append((ef["filename"], str(e)))
            cprint(f"[ERROR] Failed to delete {ef['filename']}: {e}", color=Colors.RED)

    cprint(
        f"\n[INFO] Clean complete: {deleted_count} deleted, {len(failed_files)} failed.",
        color=Colors.GREEN,
    )
    return deleted_count


def clean_by_numbers(task_dir: str, files: List[dict], indices: List[int]) -> int:
    """Clean up specific .stdout log files by their list numbers.

    Validates each index, shows a confirmation prompt, then deletes the files.

    Args:
        task_dir: Directory containing the log files.
        files: List of file metadata dictionaries.
        indices: 0-based indices of files to delete.

    Returns:
        Number of files deleted.
    """
    valid_files = []
    invalid_indices = []

    for idx in indices:
        if 0 <= idx < len(files):
            f = files[idx]
            if os.path.isfile(f["path"]):
                valid_files.append(f)
            else:
                invalid_indices.append(idx + 1)
        else:
            invalid_indices.append(idx + 1)

    if invalid_indices:
        cprint(
            f"[WARN] Invalid or out-of-range number(s): {', '.join(str(i) for i in invalid_indices)}",
            color=Colors.YELLOW,
        )

    if not valid_files:
        cprint("[INFO] No valid files to delete.", color=Colors.YELLOW)
        return 0

    print_header("Clean Selected Log Files")
    cprint(
        f"[WARN] The following {len(valid_files)} file(s) will be deleted:\n",
        color=Colors.YELLOW,
    )

    w_no = 4
    w_name = 32
    w_size = 10
    w_time = 20

    header = (
        f"{colored('', Colors.WHITE, bold=True, bg=Colors.BG_BLUE)}"
        f" {'No':^{w_no}} |"
        f" {'Filename':^{w_name}} |"
        f" {'Size':^{w_size}} |"
        f" {'Modified':^{w_time}} "
        f"{Colors.RESET}"
    )
    sep = (
        f"{Colors.CYAN}"
        f"{'-' * (w_no + 1)}+"
        f"{'-' * (w_name + 2)}+"
        f"{'-' * (w_size + 2)}+"
        f"{'-' * (w_time + 1)}"
        f"{Colors.RESET}"
    )

    print(header)
    print(sep)

    for idx, f in enumerate(valid_files, start=1):
        name = f["filename"]
        if len(name) > w_name:
            name = name[:w_name - 3] + "..."

        size_str = format_size(f["size"])
        time_str = format_timestamp_full(f["mtime"])

        row = (
            f"{Colors.GRAY}"
            f" {idx:^{w_no}} |"
            f" {name:<{w_name}} |"
            f" {size_str:>{w_size}} |"
            f" {time_str:^{w_time}} "
            f"{Colors.RESET}"
        )
        print(row)

    print(sep)

    confirm_prompt = (
        f"\n{colored('', Colors.YELLOW, bold=True)}"
        f"Are you sure you want to delete these {len(valid_files)} file(s)? [y/N]: "
        f"{Colors.RESET}"
    )
    try:
        confirm = input(confirm_prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        cprint("\n[INFO] Clean cancelled.", color=Colors.YELLOW)
        return 0

    if confirm not in ("y", "yes"):
        cprint("[INFO] Clean cancelled.", color=Colors.YELLOW)
        return 0

    deleted_count = 0
    failed_files = []

    for f in valid_files:
        try:
            os.remove(f["path"])
            deleted_count += 1
            cprint(f"[OK] Deleted: {f['filename']}", color=Colors.GREEN)
        except OSError as e:
            failed_files.append((f["filename"], str(e)))
            cprint(f"[ERROR] Failed to delete {f['filename']}: {e}", color=Colors.RED)

    cprint(
        f"\n[INFO] Clean complete: {deleted_count} deleted, {len(failed_files)} failed.",
        color=Colors.GREEN,
    )
    return deleted_count
