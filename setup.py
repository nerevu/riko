#!/usr/bin/env python

from distutils.core import setup

setup(name='pipe2py',
      version='0.9.4',
      description='A project to compile Yahoo! Pipes into Python',
      author='Greg Gaughan',
      author_email='gjgaughan@gmail.com',
      url='https://github.com/ggaughan/pipe2py',
      package_dir={'pipe2py': '', 'pipe2py.modules':'modules'},
      packages=['pipe2py', 'pipe2py.modules'],
     )

