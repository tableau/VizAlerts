# -*- coding: utf-8 -*-

from distutils.core import setup
import py2exe, sys, os

sys.argv.append('py2exe')

setup(
    options = {'py2exe': {'bundle_files': 1, 'compressed': True}},
    console = [{'script': "vizalerts.py"}],
    zipfile = None,
)
