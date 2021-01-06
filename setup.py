from distutils.core import setup
import py2exe
import os

includes = []
includefiles = os.listdir('C:\\Python38\\Lib\\site-packages\\phonenumbers\\data')
for file in includefiles:
    if file.endswith('.py'):
        includes.append('phonenumbers.data.' + file.replace('.py', ''))

#data_files = [('cacert.pem', ['D:\\Python27\\Lib\\site-packages\\twilio\\conf\\cacert.pem'])]

setup(
    options={
        'py2exe': {
            'bundle_files': 1, 'compressed': True,
            'includes': includes,
            'packages': ['twilio']
        }
    },
    #data_files=data_files,
    console=[{'script': "vizalerts.py"}],
    zipfile=None
)
