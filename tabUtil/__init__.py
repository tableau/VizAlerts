# -*- coding: utf-8 -*-

import os, sys, yaml, datetime
from yaml import Loader, SafeLoader
import logging
import logging.handlers
import codecs
#
# global (to this module) variables
#
time_format     = u"%Y-%m-%d"
log_time_format = u"%Y-%m-%d %H:%M:%S"

now      = datetime.datetime.now().strftime(log_time_format)
today    = datetime.datetime.now().strftime(time_format)
hostname = os.getenv("COMPUTERNAME")
cwd      = os.getcwd()

# log formatter
formatter       = u"%(asctime)s - [%(levelname)s] - %(funcName)s - %(message)s"
min_formatter   = u"%(asctime)s - [%(levelname)s] - %(message)s"
extra_formatter = u"%(asctime)s - [%(thread)d] - %(levelname)s - %(module)s.%(funcName)s - %(message)s"

# file log rotation constants
max_size    =  20*1024*1024  # in Bytes (5 MB)
keep_count  = 5 # how many do we keep

# load_yaml_file:
#   opens the yaml file and loads the content
def load_yaml_file(yaml_file):
    logger = logging.getLogger()
    try:
        f = codecs.open(yaml_file, encoding='utf-8')
        yaml_opts = yaml.load(f)
        f.close()
        return yaml_opts
    except:
        raise

        
# Override the default pyyaml string handling function to always return unicode objects
    # See http://stackoverflow.com/questions/2890146/how-to-force-pyyaml-to-load-strings-as-unicode-objects
def construct_yaml_str(self, node):
    return self.construct_scalar(node)
Loader.add_constructor(u'tag:yaml.org,2002:str', construct_yaml_str)
SafeLoader.add_constructor(u'tag:yaml.org,2002:str', construct_yaml_str)


# Logger
#   basic logger configuration.
def Logger(logfile_name, log_level=logging.INFO, time_format=log_time_format, extra_info = False, **kw):
    logger = logging.getLogger()
    #
    # default settings
    #
    log_logging_level       = log_level
    console_logging_level   = log_level
    log_formatter           = formatter
    console_formatter       = min_formatter

    # if the debug option is used, be very verbose
    if extra_info: log_formatter = extra_formatter
    if log_level == logging.DEBUG:
        console_formatter = log_formatter
    #
    # check the if any args have been passed in via kw
    #
    # -- logging levels --
    if kw.has_key("console_level"):
        console_logging_level = kw["console_level"]
    # -- formatters --
    if kw.has_key("log_formatter"):
        log_formatter = kw["log_formatter"]
    if kw.has_key("console_formatter"):
        console_formatter = kw["console_formatter"]
    if kw.has_key("format"):
        log_formatter = kw["format"]
        console_formatter = log_formatter
    # set up the logging instance

    #
    # make sure the logdir exists
    #
    logdir = os.path.dirname(logfile_name)
    if not os.path.isdir(logdir):
        os.makedirs(logdir)

    #
    # setup the formatters
    #
    log_formatter     = logging.Formatter(log_formatter, datefmt=time_format)
    console_formatter = logging.Formatter(console_formatter, datefmt=time_format)

    # log time formatter


    #
    # set the levels
    #
    logger.setLevel(log_logging_level)
    # add handlers
    # Handler: Log File Handler
    log_handler = logging.handlers.RotatingFileHandler(
        logfile_name,
        maxBytes=max_size,
        backupCount=keep_count,
        encoding='utf-8'
        )
    log_handler.setFormatter(log_formatter)

    # Handler: Console Output Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_logging_level)
    console_handler.setFormatter(console_formatter)

    # add handlers to the logger
    logger.addHandler(log_handler)
    logger.addHandler(console_handler)
    return logger

# QuickSetup for Logger
#   Passes in the progname and creates the logger which will
#   log to the 'logs' directory.
def LoggerQuickSetup(log_file, log_level=logging.INFO, filename_time_format='%Y-%m-%d', extra_info = False, **kw):
    log_file = log_file + "_" + today + ".log"
    logger  = Logger(log_file, log_level=log_level, extra_info=extra_info, **kw)
    logger.info("Logging initialized, writing to %s" % log_file)
    return logger

# Simple wrapper method to handle prompting the user. Return 'True' or 'False' depending on whether the input matches
#   the 'acceptable' value provided in the second argument.
def promptUser(msg, accptResp):
    resp = raw_input(msg)
    if resp == accptResp:
        return True
    else:
        return False
