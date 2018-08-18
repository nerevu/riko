# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
tests
~~~~~

Provides application unit tests
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *  # noqa pylint: disable=unused-import


def setup_package():
    """database context creation"""
    global initialized
    initialized = True
    print('Test Package Setup\n')


def teardown_package():
    """database context removal"""
    global initialized
    initialized = False
    print('Test Package Teardown\n')
