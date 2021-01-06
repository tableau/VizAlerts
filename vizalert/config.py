#! python
# -*- coding: utf-8 -*-
# Config module for VizAlert's global configs

import os.path
import sys

# local modules
import tabUtil
from . import config
from . import log

configs = []

# Global Variable Definitions


# yaml configuration values that we require
required_conf_keys = \
    ['log.dir',
    'log.dir.file_retention_seconds',
    'log.level',
    'schedule.state.dir',
    'server',
    'server.certcheck',
    'server.certfile',
    'server.ssl',
    'server.user',
    'server.user.domain',
    'server.version',
    'smsaction.enable',
    'smsaction.account_id',
    'smsaction.auth_token',
    'smsaction.provider',
    'smtp.address.from',
    'smtp.address.to',
    'smtp.password',
    'smtp.port',
    'smtp.serv',
    'smtp.ssl',
    'smtp.subject',
    'smtp.user',
    'temp.dir',
    'temp.dir.file_retention_seconds',
    'threads',
    'trusted.clientip',
    'trusted.useclientip',
    'vizalerts.source.viz',
    'vizalerts.source.site']

# yaml configuration values that we accept, but are not required
optional_conf_keys = \
    ['data.coldelimiter']

# default delimiter for CSV exports
DEFAULT_COL_DELIMITER = ','


def validate_conf(configfile):
    """Import config values and do some basic validations"""
    try:
        localconfigs = tabUtil.load_yaml_file(configfile)
    except:
        errormessage = 'An exception was raised loading the config file {}: {} Stacktrace: {}'.format(configfile,
                                                                                                       sys.exc_info(),
                                                                                                       sys.exc_info()[
                                                                                                           2])
        print(errormessage)
        log.logger.error(errormessage)
        sys.exit(1)

    # test for missing required config values
    missingkeys = set(required_conf_keys) - set(localconfigs.keys())
    if len(missingkeys) != 0:
        errormessage = 'Missing config values {}'.format(missingkeys)
        print(errormessage)
        log.logger.error(errormessage)
        sys.exit(1)

    # test for unrecognized config values
    extrakeys = set(localconfigs.keys()) - (set(required_conf_keys) | set(optional_conf_keys))
    if len(extrakeys) != 0:
        errormessage = 'Extraneous config values found. Please examine for typos: {}'.format(extrakeys)
        print(errormessage)
        log.logger.error(errormessage)
        sys.exit(1)

    # test specific conf values and prep if possible
    for dir in [localconfigs['schedule.state.dir'], localconfigs['log.dir'], localconfigs['temp.dir']]:
        if not os.path.exists(os.path.dirname(dir)):
            try:
                os.makedirs(os.path.dirname(dir))
            except OSError:
                errormessage = 'Unable to create missing directory {}, error: {}'.format(os.path.dirname(dir),
                                                                                          OSError.message)
                log.logger.error(errormessage)
                sys.exit(1)

    # test for password files and override with contents
    localconfigs['smtp.password'] = get_password_from_file(localconfigs['smtp.password'])

    # check for valid server.version setting
    if not localconfigs['server.version'] in {8, 9, 10}:
        errormessage = 'server.version value is invalid--only version 8, 9, or 10 is allowed'
        print(errormessage)
        log.logger.error(errormessage)
        sys.exit(1)

    # validate ssl config
    if localconfigs['server.certfile']:
        # ensure the certfile actually exists
        if not os.access(localconfigs['server.certfile'], os.F_OK):
            errormessage = 'The file specified in the server.certfile config setting could not be found: {}'.format(
                localconfigs['server.certfile'])
            print(errormessage)
            log.logger.error(errormessage)
            sys.exit(1)
        # ensure the certfile can be read
        if not os.access(localconfigs['server.certfile'], os.R_OK):
            errormessage = 'The file specified in the server.certfile config setting could not be accessed: {}'.format(
                localconfigs['server.certfile'])
            print(errormessage)
            log.logger.error(errormessage)
            sys.exit(1)

    # validate SMS settings
    if localconfigs['smsaction.enable']:

        # check for a valid provider
        if not localconfigs['smsaction.provider']:
            errormessage = 'Configuration value smsaction.provider must be set to enable SMS messaging'
            print(errormessage)
            log.logger.error(errormessage)
            sys.exit(1)
        elif localconfigs['smsaction.provider'] != 'twilio':
            errormessage = 'Configuration value smsaction.provider must be "twilio"; no other providers currently ' \
                           'supported.'
            print(errormessage)
            log.logger.error(errormessage)
            sys.exit(1)

        # check for an account id
        if not localconfigs['smsaction.account_id']:
            errormessage = 'Configuration value smsaction.account_id must be set to enable SMS messaging'
            print(errormessage)
            log.logger.error(errormessage)
            sys.exit(1)

        # test for SMS auth token file and override with contents
        localconfigs['smsaction.auth_token'] = get_password_from_file(localconfigs['smsaction.auth_token'])
        if not localconfigs['smsaction.auth_token']:
            errormessage = 'Configuration value smsaction.auth_token must be set to enable SMS messaging'
            print(errormessage)
            log.logger.error(errormessage)
            sys.exit(1)

    # validate data.coldelimiter
    if 'data.coldelimiter' in list(localconfigs.keys()):
        if len(localconfigs['data.coldelimiter']) > 1:
            errormessage = 'Configuration value data.coldelimiter cannot be more than one character.'
            print(errormessage)
            log.logger.error(errormessage)
            sys.exit(1)
    else:
        localconfigs['data.coldelimiter'] = DEFAULT_COL_DELIMITER
    
    config.configs = localconfigs


def get_password_from_file(password):
    """If password is actually a valid path to a text file, returns contents of text file found.
        Otherwise returns the input string again"""
    # handle the None case--some passwords won't be specified but will still be run through this function
    if not password:
        return
    try:
        if os.path.exists(password):
            log.logger.debug('Opening password file {} for reading'.format(password))
            if not password.endswith('.txt'):
                log.logger.error('Password file at path {} is not a .txt file. Quitting.'.format(password))
                sys.exit(1)
            with open(password, 'rU') as fr:
                finalpassword = fr.read()
                return finalpassword
        else:
            return password
    except IOError as e:
        log.logger.error('IOError accessing password file at path {}. Quitting. Error: {}'.format(password, e.message))
        sys.exit(1)


