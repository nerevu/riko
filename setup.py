#!/usr/bin/env python

from distutils.core import setup

import os

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(name='pipe2py',
      version='0.10.0',
      description=('A project to compile Yahoo! Pipes into Python. '
                   'The pipe2py package can compile a Yahoo! Pipe into pure Python source code, '
                   'or it can interpret the pipe on-the-fly. It supports embedded pipes too.'
                  ), 
      author='Greg Gaughan',
      author_email='gjgaughan@gmail.com',
      url='http://ggaughan.github.com/pipe2py/',
      license = 'GPL2',
      long_description=read('README.rst'),
      package_dir={'pipe2py': '', 'pipe2py.modules':'modules'},
      packages=['pipe2py', 'pipe2py.modules'],
     )

