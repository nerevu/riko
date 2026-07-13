#!/usr/bin/env python

from argparse import ArgumentParser, RawTextHelpFormatter
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from os import path as p

from riko.bado import react

io_error = FileNotFoundError


def load_file(name, src):
    location = "examples/%s.py" % src
    spec = spec_from_file_location(name, location)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file2name(path):
    return p.splitext(p.basename(path))[0]


def run():
    """CLI runner"""
    parser = ArgumentParser(
        description="description: Runs a riko pipe",
        prog="runpipe",
        usage="%(prog)s [pipeid]",
        formatter_class=RawTextHelpFormatter,
    )

    parser.add_argument(
        dest="pipeid",
        nargs="?",
        default=None,
        help="The pipe to run (default: reads from stdin).",
    )

    parser.add_argument(
        "-a",
        "--async",
        dest="isasync",
        action="store_true",
        default=False,
        help="Load async pipe.\n\n",
    )

    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        default=False,
        help="Run in test mode (uses default inputs).\n\n",
    )

    args = parser.parse_args()

    try:
        name = file2name("%s.py" % args.pipeid)
        module = load_file(name, args.pipeid)
    except io_error:
        try:
            module = import_module("examples.%s" % args.pipeid)
        except ImportError:
            exit("Pipe examples.%s not found!" % args.pipeid)

    if args.isasync:
        pipeline = module.async_pipe
        react(pipeline, [args.test])
    else:
        pipeline = module.pipe
        pipeline(test=args.test)


if __name__ == "__main__":
    run()
