# -*- coding: utf-8 -*-

import sys
import riko as module
import pkutils

try:
    from setuptools import setup, find_packages
except ImportError:
    from distutils.core import setup, find_packages

sys.dont_write_bytecode = True
requirements = sorted(pkutils.parse_requirements('requirements.txt'))
readme = pkutils.read('README.rst')
changes = pkutils.read('CHANGES.rst').replace('.. :changelog:', '')
license = module.__license__
version = module.__version__
project = module.__title__
description = module.__description__
user = 'reubano'


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
