#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""
tests.test
~~~~~~~~~~

Provides scripttests to test riko runpipe CLI functionality.
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import sys
import pygogo as gogo

from difflib import unified_diff
from os import path as p
from io import StringIO, open
from timeit import default_timer as timer

from builtins import *
from scripttest import TestFileEnvironment

sys.path.append('../riko')

try:
    from riko.bado import _isasync
except ImportError:
    _isasync = False

PARENT_DIR = p.abspath(p.dirname(p.dirname(__file__)))


def main(script, tests, verbose=False, stop=True):
    """ Main method

    Returns 0 on success, 1 on failure
    """
    failures = 0
    logger = gogo.Gogo(__name__, verbose=verbose).logger
    short_script = p.basename(script)
    env = TestFileEnvironment('.scripttest')

    start = timer()

    for pos, test in enumerate(tests):
        num = pos + 1
        opts, arguments, expected = test
        joined_opts = ' '.join(opts) if opts else ''
        joined_args = '"%s"' % '" "'.join(arguments) if arguments else ''
        command = "%s %s %s" % (script, joined_opts, joined_args)
        short_command = "%s %s %s" % (short_script, joined_opts, joined_args)
        result = env.run(command, cwd=PARENT_DIR, expect_stderr=True)
        output = result.stdout

        if isinstance(expected, bool):
            text = StringIO(output).read()
            outlines = [str(bool(text))]
            checklines = StringIO(str(expected)).readlines()
        elif p.isfile(expected):
            outlines = StringIO(output).readlines()

            with open(expected, encoding='utf-8') as f:
                checklines = f.readlines()
        else:
            outlines = StringIO(output).readlines()
            checklines = StringIO(expected).readlines()

        args = [checklines, outlines]
        kwargs = {'fromfile': 'expected', 'tofile': 'got'}
        diffs = ''.join(unified_diff(*args, **kwargs))

        if diffs:
            failures += 1
            msg = "ERROR! Output from test #%i:\n  %s\n" % (num, short_command)
            msg += "doesn't match:\n  %s\n" % expected
            msg += diffs if diffs else ''
        else:
            logger.debug(output)
            msg = 'Scripttest #%i: %s ... ok' % (num, short_command)

        logger.info(msg)

        if stop and failures:
            break

    time = timer() - start
    logger.info('%s' % '-' * 70)
    end = 'FAILED (failures=%i)' % failures if failures else 'OK'
    logger.info('Ran %i scripttests in %0.3fs\n\n%s' % (num, time, end))
    sys.exit(failures)

if __name__ == '__main__':
    demo = p.join(PARENT_DIR, 'bin', 'runpipe')
    benchmark = p.join(PARENT_DIR, 'bin', 'benchmark')
    text = 'Deadline to clear up health law eligibility near 682\n'
    runpipe_tests = [
        ([], ['demo'], text),
        ([], ['simple1'], "'farechart'\n")]

    if _isasync:
        runpipe_tests += [
            (['-a'], ['demo'], text),
            (['-a'], ['simple1'], "'farechart'\n")]

    main(demo, runpipe_tests)
    main(benchmark, [([], [], '')])
