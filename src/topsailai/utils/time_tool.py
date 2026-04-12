'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-19
  Purpose:
'''

from datetime import datetime

def get_current_date(with_t=False, include_ms=False):
    """
    Get the current date and time in a formatted string.

    :param with_t: If True, use 'T' as separator between date and time (ISO 8601 format).
                   Default is False, using space.
    :param include_ms: If True, include milliseconds in the time portion.
    :return: Formatted date time string.
    """
    c = " "
    if with_t:
        c = "T"
    dt = datetime.now()
    time_format = "%H:%M:%S"
    if include_ms:
        ms = f".{dt.microsecond // 1000:03d}"
        time_format += ms
    return dt.strftime(f"%Y-%m-%d{c}{time_format}")

def get_current_day():
    """Get the current date in YYYY-MM-DD format.

    Returns:
        str: Current date formatted as 'YYYY-MM-DD'.
    """
    dt = datetime.now()
    return dt.strftime("%Y-%m-%d")


def parse_time_seconds(ts: int) -> str:
    """
    Convert Unix timestamp to human-readable datetime string.

    Args:
        ts: Integer representing Unix timestamp (seconds since epoch)

    Returns:
        Formatted datetime string in the format YYYY-MM-DDTHH:MM:SS
    """
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%S')

def get_now_hex_str() -> str:
    """ get time-based uuid """
    dt = datetime.now()
    _part1 = dt.strftime("%Y%m%d%H%M%S")
    _part2 = dt.strftime(f"{dt.microsecond // 1000:03d}")

    result = hex(int(_part1))[2:] + hex(int(_part2))[2:]
    return result
