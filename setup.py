#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import (
    absolute_import, division, print_function, with_statement)

import sys
import riko as module
import pkutils

from builtins import *

try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup, find_packages

sys.dont_write_bytecode = True
py2_requirements = sorted(pkutils.parse_requirements('py2-requirements.txt'))
py3_requirements = sorted(pkutils.parse_requirements('requirements.txt'))
dev_requirements = sorted(pkutils.parse_requirements('dev-requirements.txt'))
optional = 'optional-requirements.txt'
async_requirements = sorted(pkutils.parse_requirements(optional))
readme = pkutils.read('README.rst')
changes = pkutils.read('CHANGES.rst').replace('.. :changelog:', '')
license = module.__license__
version = module.__version__
project = module.__title__
description = module.__description__
user = 'nerevu'

# Conditional sdist dependencies:
if 'bdist_wheel' not in sys.argv and sys.version_info.major == 2:
    requirements = py2_requirements
else:
    requirements = py3_requirements

# Conditional bdist_wheel dependencies:
py2_require = sorted(set(py2_requirements).difference(py3_requirements))

# Optional requirements
async_require = set(async_requirements).difference(requirements)
dev_require = set(dev_requirements).difference(requirements)

setup(
    name=project,
    version=version,
    description=description,
    long_description='%s\n\n%s' % (readme, changes),
    author=module.__author__,
    author_email=module.__email__,
    url=pkutils.get_url(project, user),
    download_url=pkutils.get_dl_url(project, user, version),
    packages=find_packages(exclude=['docs', 'tests']),
    include_package_data=True,
    package_data={
        'data': ['data/*'],
        'helpers': ['helpers/*'],
        'tests': ['tests/*'],
        'docs': ['docs/*'],
        'examples': ['examples/*']
    },
    install_requires=requirements,
    extras_require={
        'python_version<3.0': py2_require,
        'async': async_require,
        'develop': dev_require,
    },
    setup_requires=['pkutils>=0.12.4,<0.13.0'],
    test_suite='nose.collector',
    tests_require=dev_requirements,
    license=license,
    zip_safe=False,
    keywords=[project] + description.split(' '),
    classifiers=[
        pkutils.LICENSES[license],
        pkutils.get_status(version),
        'Natural Language :: English',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Environment :: Console',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Intended Audience :: Developers',
        'Operating System :: POSIX :: Linux',
        'Operating System :: MacOS :: MacOS X',
        'Operating System :: Microsoft :: Windows',
    ],
    platforms=['MacOS X', 'Windows', 'Linux'],
)
