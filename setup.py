#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys

from os import path as p
from setuptools import setup, find_packages

import pkutils

PARENT_DIR = p.abspath(p.dirname(__file__))

sys.dont_write_bytecode = True
requirements = list(pkutils.parse_requirements("requirements.txt"))
dev_requirements = list(pkutils.parse_requirements("dev-requirements.txt"))
optional = "optional-requirements.txt"
opt_requirements = set(pkutils.parse_requirements(optional))
readme = pkutils.read("README.rst")
module = pkutils.parse_module(p.join(PARENT_DIR, "riko", "__init__.py"))
license = module.__license__
version = module.__version__
project = module.__title__
description = module.__description__
user = "nerevu"

# Setup requirements
setup_require = [r for r in dev_requirements if "pkutils" in r]

# Optional requirements
xml_require = [r for r in opt_requirements if not r.lower().startswith("t")]
async_require = list(opt_requirements.difference(xml_require))

setup(
    name=project,
    version=version,
    description=description,
    long_description=readme,
    author=module.__author__,
    author_email=module.__email__,
    url=pkutils.get_url(project, user),
    download_url=pkutils.get_dl_url(project, user, version),
    packages=find_packages(exclude=["tests"]),
    include_package_data=True,
    package_data={
        "data": ["data/*"],
        "helpers": ["helpers/*"],
        "tests": ["tests/*"],
        "docs": ["docs/*"],
        "examples": ["examples/*"],
    },
    install_requires=requirements,
    extras_require={
        "xml": xml_require,
        "async": async_require,
        "develop": dev_requirements,
    },
    setup_requires=setup_require,
    test_suite="nose.collector",
    tests_require=dev_requirements,
    license=license,
    zip_safe=False,
    keywords=[project] + description.split(" "),
    classifiers=[
        pkutils.get_license(license),
        pkutils.get_status(version),
        "Natural Language :: English",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Environment :: Console",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Intended Audience :: Developers",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
    ],
    platforms=["MacOS X", "Windows", "Linux"],
    scripts=[p.join("bin", "runpipe")],
)
