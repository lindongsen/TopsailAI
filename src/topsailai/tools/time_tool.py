'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-20
  Purpose:
'''

import time

from topsailai.utils import time_tool

# Disabled by default. Enable explicitly when local time tooling is needed.
FLAG_TOOL_ENABLED = False

def get_local_date():
    """ get current date.
    return local time in 'ISO 8601'. example: '2025-10-19T21:17:07'
    """
    return time_tool.get_current_date(True)

def get_local_time():
    """ get local time in 'integer'. example: 1760908828 """
    return int(time.time())

def get_local_day():
    """
    return str, format is "year-month-day", e.g. '2025-11-24'
    """
    return time_tool.get_current_day()

TOOLS = dict(
    get_local_date=get_local_date,
    get_local_time=get_local_time,
)
