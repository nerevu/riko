# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    riko.lib.utils
    ~~~~~~~~~~~~~~~~~
    Utility functions

"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import sys
import logging

from builtins import *


class LogFilter(logging.Filter):
    """Filters (lets through) all messages with level < LEVEL"""
    # http://stackoverflow.com/a/24956305/408556
    def __init__(self, level):
        self.level = level

    def filter(self, record):
        return record.levelno < self.level


class Logger(object):
    """
    # logger = Logger('name', 'DEBUG').logger
    # logger.debug("A DEBUG message")
    # logger.info("An INFO message")
    # logger.warning("A WARNING message")
    # logger.error("An ERROR message")
    # logger.critical("A CRITICAL message")
    """
    def __init__(self, name, level='INFO', context=None):
        level = 'DEBUG' if context and context.verbose else level
        self.level = getattr(logging, level)
        self.name = name

    @property
    def logger(self):
        # messages < level go to stdout
        # messages >= level (and >= logging.WARNING) go to stderr
        stdout_hdlr = logging.StreamHandler(sys.stdout)
        stderr_hdlr = logging.StreamHandler(sys.stderr)
        log_filter = LogFilter(self.level)
        stdout_hdlr.addFilter(log_filter)
        stdout_hdlr.setLevel(self.level)
        stderr_hdlr.setLevel(max(self.level, logging.WARNING))

        logger = logging.getLogger(self.name)
        logger.addHandler(stdout_hdlr)
        logger.addHandler(stderr_hdlr)
        return logger
