#!/usr/bin/env python

from distutils.core import setup

from os import path as p



def read(filename, parent=None):
    parent = (parent or __file__)

    try:
        with open(p.join(p.dirname(parent), filename)) as f:
            return f.read()
    except IOError:
        return ''


def parse_requirements(filename, parent=None):
    parent = (parent or __file__)
    filepath = p.join(p.dirname(parent), filename)
    content = read(filename, parent)

    for line_number, line in enumerate(content.splitlines(), 1):
        candidate = line.strip()

        if candidate.startswith('-r'):
            for item in parse_requirements(candidate[2:].strip(), filepath):
                yield item
        else:
            yield candidate


setup(
    name='pipe2py',
    version='0.11.0',
    description=(
        'A project to compile Yahoo! Pipes into Python. '
        'The pipe2py package can compile a Yahoo! Pipe into pure Python source'
        ' code, or it can interpret the pipe on-the-fly. It supports embedded '
        'pipes too.'
    ),
    author='Greg Gaughan',
    author_email='gjgaughan@gmail.com',
    url='http://ggaughan.github.com/pipe2py/',
    license = 'GPL2',
    long_description=read('README.rst'),
    package_dir={'pipe2py': '', 'pipe2py.modules': 'modules'},
    packages=['pipe2py', 'pipe2py.modules'],
    install_requires=parse_requirements('requirements.txt'),
)
