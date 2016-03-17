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
    name='bomba',
    version='0.27.0',
    description=('A stream processor modeled after Yahoo! Pipes.'),
    long_description=read('README.rst'),
    url='http://kazeeki.github.com/bomba/',
    license = 'MIT',
    author='Reuben Cummings',
    author_email='reubano@gmail.com',
    packages=find_packages(exclude=['tests']),
    package_data={'data': 'data/*'},
    include_package_data=True,
    classifiers=[],
    keywords='',
    scripts=[p.join('bin', 'compile'), p.join('bin', 'run')],
    install_requires=parse_requirements('requirements.txt'),
    dependency_links=list(parse_requirements('requirements.txt', dep=True)),
)
