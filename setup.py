# -*- coding: utf-8 -*-

import sys
import re

from os import path as p

try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup, find_packages


def read(filename, parent=None):
    parent = (parent or __file__)

    try:
        with open(p.join(p.dirname(parent), filename)) as f:
            return f.read()
    except IOError:
        return ''


def parse_requirements(filename, parent=None, dep=False):
    parent = (parent or __file__)
    filepath = p.join(p.dirname(parent), filename)
    content = read(filename, parent)

    for line_number, line in enumerate(content.splitlines(), 1):
        candidate = line.strip()

        if candidate.startswith('-r'):
            for item in parse_requirements(candidate[2:].strip(), filepath, dep):
                yield item
        elif not dep and '#egg=' in candidate:
            yield re.sub('.*#egg=(.*)-(.*)', r'\1==\2', candidate)
        else:
            yield candidate.replace('-e ', '')

# Avoid byte-compiling the shipped template
sys.dont_write_bytecode = True


setup(
    name='pipe2py',
    version='0.23.0',
    description=(
        'A project to compile Yahoo! Pipes into Python. '
        'The pipe2py package can compile a Yahoo! Pipe into pure Python source'
        ' code, or it can interpret the pipe on-the-fly. It supports embedded '
        'pipes too.'
    ),
    long_description=read('README.rst'),
    url='http://ggaughan.github.com/pipe2py/',
    license = 'GPL2',
    author='Greg Gaughan',
    author_email='gjgaughan@gmail.com',
    packages=find_packages(exclude=['tests']),
    package_data={'templates': 'templates/*.txt'},
    include_package_data=True,
    classifiers=[],
    keywords='',
    scripts=[p.join('bin', 'compile')],
    install_requires=parse_requirements('requirements.txt'),
    dependency_links=list(parse_requirements('requirements.txt', dep=True)),
)
