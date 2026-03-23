'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-20
  Purpose:
'''

import os
import logging
from logging.handlers import RotatingFileHandler


# default_formatter = '%(asctime)s %(levelname)s -%(thread)d- %(message)s (%(pathname)s:%(lineno)d)'
# default_stream_handler = logging.StreamHandler()
# default_stream_handler.setFormatter(default_formatter)


class AgentFormatter(logging.Formatter):
    """ format agent_name """
    def __init__(self, fmt=None, datefmt=None):
        logging.Formatter.__init__(self, fmt, datefmt)

    def format(self, record):
        """ format log content """
        # DONOT: import outside
        from topsailai.utils.thread_local_tool import (
            get_agent_name,
            get_thread_name,
        )

        # thread local in python

        # agent_name
        agent_name = get_agent_name()
        if not agent_name:
            # env in script
            agent_name = os.environ.get("AGENT_NAME", "") or os.environ.get("AI_AGENT", "")
        if not agent_name:
            agent_name = ""

        # thread_name
        thread_name = get_thread_name() or ""

        # generate message_id
        message_id = ""
        if agent_name \
            or thread_name \
        :
            message_id = f"({agent_name}:{thread_name})"
        record.message_id = message_id

        # format
        return logging.Formatter.format(self, record)


def setup_logger(name:str=None, log_file:str=None, level=logging.DEBUG):
    """ generate logger """
    formatter = AgentFormatter('%(asctime)s %(levelname)s -%(thread)d- %(message)s (%(pathname)s:%(lineno)d) %(message_id)s')
    _logger = logging.getLogger(name)

    if not log_file:
        if name:
            log_file = name + ".log"

    if log_file:
        file_handler = RotatingFileHandler(log_file, maxBytes=100000000, backupCount=1)
        file_handler.setFormatter(formatter)
        _logger.addHandler(file_handler)

    else:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        _logger.addHandler(stream_handler)

    _logger.setLevel(level)
    return _logger
