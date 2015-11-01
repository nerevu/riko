# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.lib.utils
    ~~~~~~~~~~~~~~~~~
    Utility functions

"""

from __future__ import absolute_import, division, print_function

import sys, logging


class LogFilter(logging.Filter):
    """Filters (lets through) all messages with level < LEVEL"""
    # http://stackoverflow.com/a/24956305/408556
    def __init__(self, level):
        self.level = level

    def filter(self, record):
        # "<" instead of "<=": since logger.setLevel is inclusive, this should
        # be exclusive
        return record.levelno < self.level

MIN_LEVEL = logging.DEBUG
stdout_hdlr = logging.StreamHandler(sys.stdout)
stderr_hdlr = logging.StreamHandler(sys.stderr)
log_filter = LogFilter(logging.WARNING)
stdout_hdlr.addFilter(log_filter)
stdout_hdlr.setLevel(MIN_LEVEL)
stderr_hdlr.setLevel(max(MIN_LEVEL, logging.WARNING))
# messages lower than WARNING go to stdout
# messages >= WARNING (and >= STDOUT_LOG_LEVEL) go to stderr

rootLogger = logging.getLogger()
rootLogger.addHandler(stdout_hdlr)
rootLogger.addHandler(stderr_hdlr)

class Logger(object):
    def __init__(self, level):
        self.level = level

    @property
    def logger(self):
        logger = logging.getLogger(__name__)
        logger.setLevel(getattr(logging, self.level))
        return logger

# # Example Usage
# logger.debug("A DEBUG message")
# logger.info("An INFO message")
# logger.warning("A WARNING message")
# logger.error("An ERROR message")
# logger.critical("A CRITICAL message")
