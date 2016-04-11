#! python
# -*- coding: utf-8 -*-
# Script to generate conditional automation against published views from a Tableau Server instance

__author__ = 'mcoles'
__credits__ = 'Jonathan Drummey'

# generic modules
import logging
import sys
import os
import traceback
import shutil
import csv
import datetime
import re
import time
import smtplib
import fileinput
from os.path import abspath, basename, expanduser
from operator import itemgetter
import posixpath
from PyPDF2 import PdfFileReader, PdfFileMerger
from collections import OrderedDict

# Tableau modules
import tabUtil
from tabUtil import tabhttp

# SMS modules - this is the base load, included modules are loaded as necessary
import smsAction
from smsAction import smsaction

# PostgreSQL module
import psycopg2
import psycopg2.extras
import psycopg2.extensions
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)
psycopg2.extensions.register_type(psycopg2.extensions.UNICODEARRAY)

# added for MIME handling
from itertools import chain
from errno import ECONNREFUSED
from mimetypes import guess_type
from subprocess import Popen, PIPE

import email.encoders
from email.encoders import encode_base64
from cStringIO import StringIO
from email.header import Header
from email import Charset
from email.generator import Generator
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from socket import error as SocketError

import codecs
from codecs import decode
from codecs import encode

# Global Variable Definitions
valid_conf_keys = \
    ['db.database',
        'db.host',
        'db.port',
        'db.pw',
        'db.query',
        'db.user',
        'log.dir',
        'log.dir.file_retention_seconds',
        'log.level',
        'schedule.state.dir',
        'server',
        'server.version',
        'server.user',
        'smtp.address.from',
        'smtp.notify_subscriber_on_failure',
        'smtp.address.to',
        'smtp.alloweddomains',
        'smtp.serv',
        'server.ssl',
        'server.certcheck',
        'smtp.subject',
        'temp.dir',
        'temp.dir.file_retention_seconds',
        'trusted.clientip',
        'trusted.useclientip',
        'viz.data.maxrows',
        'viz.data.timeout',
        'viz.png.height',
        'viz.png.width',
        'smsaction.enable',
        'smsaction.provider',
        'smsaction.account_id',
        'smsaction.auth_token',
        'smsaction.from_number',
        'exportfile.mode',
        'exportfile.allowedpaths']

required_email_fields =\
    [' Email To *',
        ' Email Subject *',
        ' Email Body *']

# appended to the bottom of all user-facing emails
    # expecting bodyfooter.format(subscriberemail, vizurl, viewname)
bodyfooter = u'<br><br><font size="2"><i>This VizAlerts email generated on behalf of {}, from view <a href="{}">' \
             u'{}</a></i></font>'

# appended under the bodyfooter, but only for Simple Alerts
    # expecting unsubscribe_footer.format(subscriptionsurl)
unsubscribe_footer = u'<br><font size="2"><i><a href="{}">Manage my subscription settings</a></i></font>'

# regular expression used to split recipient address strings into separate email addresses
EMAIL_RECIP_SPLIT_REGEX = u'[; ,]*'
SMS_RECIP_SPLIT_REGEX = u'[;,]*'

# name of the file used for maintaining subscriptions state in schedule.state.dir
SCHEDULE_STATE_FILENAME = u'vizalerts.state'

# reserved strings for Advanced Alerts embedding
IMAGE_PLACEHOLDER = u'VIZ_IMAGE()' 
PDF_PLACEHOLDER = u'VIZ_PDF()'
CSV_PLACEHOLDER = u'VIZ_CSV()'
TWB_PLACEHOLDER = u'VIZ_TWB()'
DEFAULT_FOOTER = u'VIZALERTS_FOOTER()' # special string for embedding the default footer in an Advanced Alert
VIZLINK_PLACEHOLDER = u'VIZ_LINK()' # special string for embedding HTML links in Advanced Alert 

# reserved strings for Advanced Alerts arguments
EXPORTFILENAME_ARGUMENT = u'filename'
EXPORTFILEPATH_ARGUMENT = u'exportfilepath'
NOATTACH_ARGUMENT = u'noattach'
MERGEPDF_ARGUMENT = u'mergepdf'
VIZLINK_ARGUMENT = u'vizlink'
RAWLINK_ARGUMENT = u'rawlink'
ARGUMENT_DELIMITER = u'|'

# defined values for ' Email Action *' field
EMAIL_ACTION = u'1'
SMS_ACTION = u'2'

# whether SMS action is available
SMS_ACTION_AVAILABLE = False

# code from https://github.com/mitsuhiko/flask/blob/50dc2403526c5c5c67577767b05eb81e8fab0877/flask/helpers.py#L80
# what separators does this operating system provide that are not a slash?
# used in VizAlerts for verifying custom filenames and paths for appended attachments and exported attachments
_os_alt_seps = list(sep for sep in [os.path.sep, os.path.altsep]
                    if sep not in (None, '/', '\\'))
                    
class UnicodeCsvReader(object):
    """Code from http://stackoverflow.com/questions/1846135/general-unicode-utf-8-support-for-csv-files-in-python-2-6"""
    def __init__(self, f, encoding="utf-8", **kwargs):
        self.csv_reader = csv.reader(f, **kwargs)
        self.encoding = encoding

    def __iter__(self):
        return self

    def next(self):
        # read and split the csv row into fields
        row = self.csv_reader.next()
        # now decode
        return [unicode(cell, self.encoding) for cell in row]

    @property
    def line_num(self):
        return self.csv_reader.line_num


class UnicodeDictReader(csv.DictReader):
    """Returns a DictReader that supports Unicode"""
    """Code from http://stackoverflow.com/questions/1846135/general-unicode-utf-8-support-for-csv-files-in-python-2-6"""
    def __init__(self, f, encoding="utf-8", fieldnames=None, **kwds):
        csv.DictReader.__init__(self, f, fieldnames=fieldnames, **kwds)
        self.reader = UnicodeCsvReader(f, encoding=encoding, **kwds)


def main(configfile=u'.\\config\\vizalerts.yaml',
         logfile=u'.\\logs\\vizalerts.log'):
    # initialize logging
    global logger
    logger = logging.getLogger()
    if not len(logger.handlers):
        logger = tabUtil.LoggerQuickSetup(logfile, log_level=logging.DEBUG)

    # load configs from yaml file
    global configs
    configs = validate_conf(configfile, logger)

    # set the log level based on the config file
    logger.setLevel(configs["log.level"])

    # check whether SMS Actions are enabled
    if configs['smsaction.enable']:
        try:
            global smsclient
            smsclient = smsaction.get_sms_client(configs, logger)
            global SMS_ACTION_AVAILABLE
            SMS_ACTION_AVAILABLE = True
            logger.info(u'SMS Actions are enabled')
            
        except Exception as e:
            errormessage = u'Unable to get SMS client, error: {}'.format(e.message)
            logger.error(errormessage)
            quit_script(errormessage)
    
    # check options for exporting files
    # 0 (default) = disabled
    if configs['exportfile.mode'] == 0:
        logger.info(u'Exporting files via content references is disabled')
    # 1 = only export to admin approvided paths & subfolders of those paths
    elif configs['exportfile.mode'] == 1:
        if len(configs['exportfile.allowedpaths']) == 0:
            errormessage = u'Export file option has been configured but no exportfile.allowedpaths have been set up'
            logger.error(errormessage)
            quit_script(errormessage)
        else:
            for exportfilepath in configs['exportfile.allowedpaths']:
                if not os.path.exists(exportfilepath):
                    errormessage = u'Configured export file path {} in exportfile.allowedpaths does not exist.'.format(exportfilepath)
                    logger.error(errormessage)
                    quit_script(errormessage)
            
            logger.info(u'Exporting files via content references is allowed to admin-approved paths {}'.format(configs['exportfile.allowedpaths']))
    # 2 = any user-defined UNC path
    elif configs['exportfile.mode'] == 2:
        logger.info(u'Exporting files via content references is allowed for any user-defined path')
    else:
        errormessage = u'Unknown export file path option {} found'.format(configs['exportfile.mode'])
        logger.error(errormessage)
        quit_script(errormessage)        
    
    # cleanup old temp files
    try:
        cleanup_dir(configs["temp.dir"], configs["temp.dir.file_retention_seconds"])
    except Exception as e:
        errormessage = u'Unable to cleanup temp directory {}, error: {}'.format(configs["temp.dir"], e)
        logger.error(errormessage)
        send_email(configs["smtp.address.from"], configs["smtp.address.to"], configs["smtp.subject"], errormessage)

    # cleanup old log files
    try:
        cleanup_dir(configs["log.dir"], configs["log.dir.file_retention_seconds"])
    except Exception as e:
        errormessage = u'Unable to cleanup log directory {}, error: {}'.format(configs["temp.dir"], e)
        logger.error(errormessage)
        send_email(configs["smtp.address.from"], configs["smtp.address.to"], configs["smtp.subject"], errormessage)

    # test ability to connect to Tableau Server and obtain a trusted ticket
    trusted_ticket_test()
    # get the views to process
    try:
        views = get_views()
        logger.info(u'Processing a total of {} views'.format(len(views)))
    except Exception as e:
        errormessage = u'Unable to get views to process, error: {}'.format(e.message)
        logger.error(errormessage)
        quit_script(errormessage)

    process_views(views)


def process_views(views):
    """Iterate through the list of applicable views, and process each"""
    for view in views:
        logger.debug('~view')
        for key in view:
            logger.debug('{}'.format(key))
        logger.debug(u'Processing subscription_id {}, view_id {}, site_name {}, customized view id {}, '
                     'view_name {}'.format(
                                        view["subscription_id"],
                                        view["view_id"],
                                        view["site_name"],
                                        view["customized_view_id"],
                                        view["view_name"]))
        sitename = unicode(view["site_name"]).replace('Default', '')
        viewurlsuffix = view['view_url_suffix']
        viewname = unicode(view['view_name'])

        timeout_s = view['timeout_s']
        subscribersysname = unicode(view['subscriber_sysname'].decode('utf-8'))
        subscriberemail = view['subscriber_email']

        # get the domain of the subscriber's user
        subscriberdomain = None
        if view['subscriber_domain'] != 'local': # leave it as None if Server uses local authentication
            subscriberdomain = view['subscriber_domain']

        # check for invalid email domains
        subscriberemailerror = address_is_invalid(subscriberemail)
        if subscriberemailerror:
            errormessage = u'VizAlerts was unable to process this alert, because it was unable to send email to address {}: {}'.format(subscriberemail, subscriberemailerror)
            logger.error(errormessage)

            view_failure(view, errormessage)
            continue

        # check for unlicensed user
            
        if view['subscriber_license'] == 'Unlicensed':
            errormessage = u'VizAlerts was unable to process this alert: User {} is unlicensed.'.format(subscribersysname)
            logger.error(errormessage)
            view_failure(view, errormessage)
            continue

        # set our clientip properly if Server is validating it
        if configs["trusted.useclientip"]:
            clientip = configs["trusted.clientip"]
        else:
            clientip = None

        # get the raw csv data from the view
        try:
            filepath = tabhttp.export_view(configs, view, tabhttp.Format.CSV, logger)
        except Exception as e:
            errormessage = u'Unable to export viewname {} as {}, error: {}'.format(viewname, tabhttp.Format.CSV, e)
            logger.error(errormessage)
            view_failure(view, u'VizAlerts was unable to export data for this view. Error message: {}'.format(errormessage))
            continue

        # We now have the CSV, so process it
        try:
            process_csv(filepath, view, sitename, viewname, subscriberemail, subscribersysname, subscriberdomain,
                        viewurlsuffix, timeout_s)
        except Exception as e:
            errormessage = u'Unable to process data from viewname {}, error:<br> {}'.format(viewname, e)
            logger.error(errormessage)
            view_failure(view, u'VizAlerts was unable to process this view due to the following error:<br>{}'.format(e))
            continue


def validate_conf(configfile, logger):
    """Import config values and do some basic validations"""
    try:
        localconfigs = tabUtil.load_yaml_file(configfile)
    except:
        errormessage = u'An exception was raised loading the config file {}: {} Stacktrace: {}'.format(configfile, sys.exc_info(),
                                                                                                   sys.exc_info()[2])
        print errormessage
        logger.error(errormessage)
        sys.exit(1)

    # test for missing config values
    missingkeys = set(valid_conf_keys).difference(localconfigs.keys())
    if len(missingkeys) != 0:
        errormessage = u'Missing config values {}'.format(missingkeys)
        print errormessage
        logger.error(errormessage)
        sys.exit(1)

    # test specific conf values and prep if possible
    for dir in [localconfigs["schedule.state.dir"], localconfigs["log.dir"], localconfigs["temp.dir"]]:
        if not os.path.exists(os.path.dirname(dir)):
            try:
                os.makedirs(os.path.dirname(dir))
            except OSError:
                errormessage = u'Unable to create missing directory {}, error: {}'.format(os.path.dirname(dir),
                                                                                         OSError.message)
                logger.error(errormessage)
                quit_script(errormessage)

    # test for password files and override with contents
    localconfigs["smtp.password"] = get_password_from_file(localconfigs["smtp.password"])
    localconfigs["db.pw"] = get_password_from_file(localconfigs["db.pw"])

    # check for valid viz.png heigh/width settings
    if not type(localconfigs["viz.png.width"]) is int or not type(localconfigs["viz.png.height"]) is int:
        errormessage = u'viz.png height/width values are invalid {},{}'.format(localconfigs["viz.png.width"],
                                                                              localconfigs["viz.png.height"])
        print errormessage
        logger.error(errormessage)
        sys.exit(1)

    # check for valid viz.data.timeout setting
    for rule in localconfigs["viz.data.timeout"]:
        if len(rule) > 3:
            errormessage = u'viz.data.timeout values are invalid--only three entries per rule allowed'
            print errormessage
            logger.error(errormessage)
            sys.exit(1)

    # check for valid viz.data.timeout setting
    for rule in localconfigs["viz.data.retrieval_tries"]:
        if len(rule) > 3:
            errormessage = u'viz.data.retrieval_tries values are invalid--only three entries per rule allowed'
            print errormessage
            logger.error(errormessage)
            sys.exit(1)

    # check for valid server.version setting
    if not localconfigs["server.version"] in {8,9}:
        errormessage = u'server.version value is invalid--only version 8 or version 9 allowed'
        print errormessage
        logger.error(errormessage)
        sys.exit(1)

    return localconfigs


def trusted_ticket_test():
    """Test ability to generate a trusted ticket from Tableau Server"""
    # test for ability to generate a trusted ticket with the general username provided
    if configs["trusted.useclientip"]:
        clientip = configs["trusted.clientip"]
    else:
        clientip = None

    logger.debug(u'testing trusted ticket: {}, {}, {}'.format(configs["server"], configs["server.user"], clientip))
    sitename = ''    # this is just a test, use the default site
    test_ticket = None
    try:
        test_ticket = tabhttp.get_trusted_ticket(configs["server"], sitename, configs["server.user"], configs["server.ssl"], logger, configs["server.certcheck"], None, clientip)
        logger.debug(u'Generated test trusted ticket. Value is: {}'.format(test_ticket))
    except Exception as e:
        errormessage = e.message
        logger.error(errormessage)
        quit_script(errormessage)


def get_views():
    """Get the set of Tableau Server views to check during this execution"""
    try:
        connstring = "dbname={} user={} host={} port={} password={}".format(configs["db.database"], configs["db.user"],
                                                                            configs["db.host"], configs["db.port"],
                                                                            configs["db.pw"])
        conn = psycopg2.connect(connstring)
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(configs["db.query"])
        views = cur.fetchall()
        logger.debug(u'PostgreSQL repository returned {} rows'.format(len(views)))
    except psycopg2.Error as e:
        errormessage = u'Failed to execute query against PostgreSQL repository: {}'.format(e)
        logger.error(errormessage)
        quit_script(errormessage)
    except Exception as e:
        errormessage = u'Unknown error obtaining views to process: {}'.format(e)
        logger.error(errormessage)
        quit_script(errormessage)

    # retrieve schedule data from the last run and compare to current
    statefile = configs["schedule.state.dir"] + SCHEDULE_STATE_FILENAME

    # list of views to write to the state file again
    persistviews = []

    # final list of views to execute alerts for
    execviews = []
    try:
        if not os.path.exists(statefile):
            f = codecs.open(statefile, encoding='utf-8', mode='w+')
            f.close()
    except IOError as e:
        errormessage = u'Invalid schedule state file: {}'.format(e.message)
        logger.error(errormessage)
        quit_script(errormessage)

    try:
        for line in fileinput.input([statefile]):
            if not fileinput.isfirstline():
                linedict = {}
                linedict['site_name'] = line.split('\t')[0]
                linedict['subscription_id'] = line.split('\t')[1]
                linedict['view_id'] = line.split('\t')[2]
                linedict['customized_view_id'] = line.split('\t')[3]
                linedict['ran_last_at'] = line.split('\t')[4]
                linedict['run_next_at'] = line.split('\t')[5]
                linedict['schedule_id'] = line.split('\t')[6].rstrip()  # remove trailing line break
                for view in views:
                    # subscription_id is our unique identifier
                    if str(view['subscription_id']) == str(linedict['subscription_id']):

                        # preserve the last time the alert was scheduled to run
                        view['ran_last_at'] = str(linedict['ran_last_at'])

                        # if the run_next_at date is greater for this view since last we checked, mark it to run now
                            # the last condition ensures the alert doesn't run simply due to a schedule switch
                                # (note that CHANGING a schedule will still trigger the alert check...to be fixed later
                        if (
                            (datetime.datetime.strptime(str(view['run_next_at']), "%Y-%m-%d %H:%M:%S") \
                                != datetime.datetime.strptime(str(linedict['run_next_at']), "%Y-%m-%d %H:%M:%S") \
                                and \
                            str(view["schedule_id"]) == str(linedict["schedule_id"]))
                            or
                            (view['is_test'] and \
                                datetime.datetime.strptime(str(view['run_next_at']), "%Y-%m-%d %H:%M:%S") \
                                != datetime.datetime.strptime(str(linedict['ran_last_at']), "%Y-%m-%d %H:%M:%S")) # test alerts run immediately if never executed before
                            ):

                            # For a test, run_next_at is anchored to the most recent comment, so use it as last run time
                            if view['is_test']:
                                view['ran_last_at'] = view['run_next_at']
                            else:
                                view['ran_last_at'] = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

                            seconds_since_last_run = \
                                abs((
                                    datetime.datetime.strptime(str(linedict['ran_last_at']),
                                                               "%Y-%m-%d %H:%M:%S") -
                                    datetime.datetime.utcnow()
                                    ).total_seconds())

                            # Set the timeout value in seconds to use for this view
                            timeout_s = view["timeout_s"]
                            for rule in configs["viz.data.timeout"]:
                                # REMOVE
                                logger.debug('Checking rule with from: {}, to: {}, timeout: {}'.format(rule[0], rule[1], rule[2]))
                                if rule[0] <= seconds_since_last_run <= rule[1]:
                                    logger.debug('Rule applies!')
                                    timeout_s = rule[2]
                                    break

                            # Set the number of data retrieval attempts to use for this view
                            data_retrieval_tries = view["data_retrieval_tries"]
                            for rule in configs["viz.data.retrieval_tries"]:
                                if rule[0] <= seconds_since_last_run <= rule[1]:
                                    data_retrieval_tries = rule[2]

                            # overwrite the placeholder values with our newly derived values
                            view['timeout_s'] = timeout_s
                            view['data_retrieval_tries'] = data_retrieval_tries
                            logger.debug(u'using timeout {}s, data retrieval tries {}, due to it being {} seconds since last'
                                         ' run.'.format(timeout_s, data_retrieval_tries, seconds_since_last_run))
                            execviews.append(view)

                        # add the view to the list to write back to our state file
                        persistviews.append(view)

        # add NEW subscriptions that weren't in our state file
            # this is ugly I, know...sorry. someday I'll be better at Python.
        persist_sub_ids = []
        for view in persistviews:
            persist_sub_ids.append(view['subscription_id'])
        for view in views:
            if view['subscription_id'] not in persist_sub_ids:
                persistviews.append(view)

        # write the next run times to file
        with codecs.open(statefile, encoding='utf-8', mode='w') as fw:
            fw.write('{}\t{}\t{}\t{}\t{}\t{}\t{}\n'.format("site_name", "subscription_id", "view_id",
                                                       "customized_view_id", "ran_last_at", "run_next_at",
                                                       "schedule_id"))
            for view in persistviews:
                fw.write('{}\t{}\t{}\t{}\t{}\t{}\t{}\n'.format(view['site_name'], view["subscription_id"],
                                                                   view["view_id"], view["customized_view_id"],
                                                                   view["ran_last_at"], view["run_next_at"],
                                                                   view["schedule_id"]))
    except IOError as e:
        errormessage = u'IOError accessing {} while getting views to process: {}'.format(e.filename, e.message)
        logger.error(errormessage)
        quit_script(errormessage)
    except Exception as e:
        errormessage = u'Error accessing {} while getting views to process: {}'.format(statefile, e)
        logger.error(errormessage)
        quit_script(errormessage)

    return execviews


def process_csv(csvpath, view, sitename, viewname, subscriberemail, subscribersysname, subscriberdomain, viewurlsuffix, timeout_s):
    """For a CSV containing viz data, process it as a simple or advanced alert"""
    try:
        logger.debug(u'Opening file {} for reading'.format(csvpath))

        f = open(csvpath, 'rU')
        csvreader = UnicodeDictReader(f)

    except Exception as e:
        logger.error(u'Error accessing {} while getting processing view {}: {}'.format(csvpath, viewurlsuffix, e))
        raise e

    # get the data into a list of dictionaries
    data = []
    rowcount = 0
    logger.debug(u'Iterating through rows')
    for row in csvreader:
        if rowcount > configs["viz.data.maxrows"]:
            errormessage = u'Maximum rows of {} exceeded.'.format(configs["viz.data.maxrows"],
                                                                                       viewurlsuffix)
            logger.error(errormessage)
            raise UserWarning(errormessage)
        data.append(row)
        rowcount = rowcount + 1
        logger.debug(u'Rowcount at: {}'.format(rowcount))

    logger.debug('Done loading data')
    
    # bail if no data to process
    if rowcount == 0:
        logger.info(u'0 rows found; no actions being taken')
        return

    # detect if this is a simple or advanced alert
    if u' Email Action *' in csvreader.fieldnames:
        logger.debug('Advanced alert detected')

        simplealert = False
    else:
        logger.debug('Simple alert detected')
        simplealert = True

    vizurl = get_view_url(view)

    # construct the body footer text for later use
    bodyfooter = get_footer(subscriberemail, subscribersysname, subscriberdomain, vizurl, viewname, simplealert, configs["server.version"])

    # set our clientip properly if Server is validating it
    if configs["trusted.useclientip"]:
        clientip = configs["trusted.clientip"]
    else:
        clientip = None

    # process the simple alert scenario
    if simplealert:
        try:
            logger.debug(u'Processing as a simple alert')

            # export the viz to a PNG file
            imagepath = tabhttp.export_view(configs, view, tabhttp.Format.PNG, logger)

            # attachments are stored lists of dicts to handle Advanced Alerts
            inlineattachments = [{'imagepath' : imagepath}]
            appendattachments = [{'imagepath' : csvpath}]
            
            logger.info(u'Sending simple alert email to user {}'.format(subscriberemail))
            body = u'<a href="{}"><img src="cid:{}"></a>'.format(vizurl, basename(imagepath)) +\
                   bodyfooter.format(subscriberemail, vizurl, viewname)
            subject = unicode(u'Alert triggered for {}'.format(viewname))
            send_email(configs["smtp.address.from"], subscriberemail, subject, body,
                       None, None, inlineattachments, appendattachments)
            return
        except Exception as e:
            errormessage = u'Alert was triggered, but encountered a failure rendering data/image:<br> {}'.format(e.message)
            logger.error(errormessage)
            raise UserWarning(errormessage)
    else:
        # this is an advanced alert, so we need to process all the fields appropriately
        logger.debug(u'Processing as an advanced alert')

        # ensure the subscriber is the owner of the viz -- if not, disregard it entirely
        if view['subscriber_sysname'] != view['owner_sysname']:
            logger.info(u'Ignoring advanced alert subscription_id {} for non-owner {}'.format(
                view['subscription_id'], view['subscriber_sysname']))
            return

        # test for valid fields
        if u' Email Action *' in csvreader.fieldnames:
            missingfields = set(required_email_fields).difference(csvreader.fieldnames)
            if len(missingfields) != 0:
                errormessage = u'Missing email fields {}'.format(list(missingfields))
                logger.error(errormessage)
                raise UserWarning(errormessage)

            # booleans determining whether optional fields are present
            has_consolidate_email = False
            has_email_from = False
            has_email_cc = False
            has_email_bcc = False
            has_email_header = False
            has_email_footer = False
            has_email_attachment = False
            # used for forcing a sort order in consolidated emails since the 
            # trigger view csv gets re-sorted by the download process
            has_email_sort_order = False 

            # create variables for optional email fields
            email_from = None
            email_cc = None
            email_bcc = None
            email_header = None
            email_footer = None
            
            # assign variable for any viz image generated
            imagepath = u''

            if u' Email Consolidate ~' in csvreader.fieldnames:
                has_consolidate_email = True
            if u' Email From ~' in csvreader.fieldnames:
                has_email_from = True
            if u' Email CC ~' in csvreader.fieldnames:
                has_email_cc = True
            if u' Email BCC ~' in csvreader.fieldnames:
                has_email_bcc = True
            if u' Email Header ~' in csvreader.fieldnames:
                has_email_header = True
            if u' Email Footer ~' in csvreader.fieldnames:
                has_email_footer = True
            if u' Email Attachment ~' in csvreader.fieldnames:
                has_email_attachment = True
            if u' Email Sort Order ~' in csvreader.fieldnames:
                has_email_sort_order = True

            logger.debug(u'Validating email addresses')
            # validate all From and Recipient addresses
            addresserrors = validate_addresses(data, has_email_from, has_email_cc, has_email_bcc)
            if addresserrors:
                errormessage = u'Invalid email addresses found, details to be emailed.'
                logger.error(errormessage)

                # Need to send a custom email for this error
                addresslist = u'<table border=1><tr><b><td>Row</td><td width="75">Email Action</td><td width="75">Field</td><td>Value</td><td>Error</td></b></tr>'
                for adderror in addresserrors:
                    addresslist = addresslist + u'<tr><td width="75">{}</td><td width="75">{}</td><td width="75">{}</td><td>{}</td><td>{}</td></tr>'.format(adderror['Row'],
                                                                                                                adderror['Action'],
                                                                                                                adderror['Field'],
                                                                                                                adderror['Value'],
                                                                                                                adderror['Error'],)
                addresslist = addresslist + u'</table>'
                appendattachments = [{'imagepath' : csvpath}]
                view_failure(view, u'Error(s) found in recipients:<br><br>{}'.format(addresslist) + \
                                u'<br><br>See row numbers in attached CSV file.' ,
                                appendattachments)
                return

            # eliminate duplicate rows and ensure proper sorting
            data = get_unique_vizdata(data, has_consolidate_email, has_email_from, has_email_cc, has_email_bcc, has_email_header, has_email_footer, has_email_attachment, has_email_sort_order)
            rowcount_unique = len(data)
                
            # could be multiple viz's (including PDF, CSV, TWB) for a single row in the CSV
            # return a list of all found content reference VIZ_*() strings
            # VIZ_*([optional custom view w/optional custom URL parameters]|[optional VizAlerts parameters])
            # stored as a dict of dicts, the key is the content reference

            vizcompleterefs = dict()

            try:
                vizcompleterefs = find_viz_refs(view, data, viewurlsuffix, has_email_header, has_email_footer, has_email_attachment)
            except Exception as e:
                errormessage = u'Alert was triggered, but encountered a failure getting data/image references:<br> {}'.format(e.message)
                logger.error(errormessage)
                raise UserWarning(errormessage)
                
            # iterate through the rows and send emails accordingly
            consolidate_email_ctr = 0
            body = []

            # inline attachments and appendattachments will be a list of dicts
            # where each dict is a content reference VIZ_PDF(), VIZ_IMAGE(), etc.
            inlineattachments = []
            appendattachments =[]

            # Process each row of data
            for i, row in enumerate(data):
                logger.debug(u'Starting iteration {}, consolidate_email_ctr is {}'.format(i, consolidate_email_ctr))
                for line in body:
                    logger.debug(u'Body row: {}'.format(line))

                # make sure we set the "from" address if the viz did not provide it
                if has_email_from:
                    email_from = row[' Email From ~']
                else:
                    if row[' Email Action *'] == EMAIL_ACTION:
                        email_from = configs["smtp.address.from"]   # use default from config file
                    elif row[' Email Action *'] == SMS_ACTION:
                        email_from = configs["smsaction.from_number"] # use default from config file

                # get the other recipient addresses
                if has_email_cc:
                    email_cc = row[' Email CC ~']
                else:
                    email_cc = None

                if has_email_bcc:
                    email_bcc = row[' Email BCC ~']
                else:
                    email_bcc = None

                if row[' Email Action *'] == EMAIL_ACTION:
                    logger.debug(u'Starting email action')

                    # Append header row, if provided
                    if has_email_header and consolidate_email_ctr == 0:
                        logger.debug(u'has_email_header is {} and consolidate_email_ctr is '
                                     u'{}, so appending body header'.format(has_email_header, consolidate_email_ctr))
                        body.append(row[' Email Header ~'])

                    # If rows are being consolidated, consolidate all with same recipients & subject
                    if has_consolidate_email:
                        # could put a test in here for mixing consolidated and non-consolidated emails in
                        # the same trigger view, would also need to check the sort in get_unique_vizdata

                        logger.debug(u'Consolidate value is true, row index is {}, rowcount is {}'.format(i, rowcount_unique))

                        # test for end of iteration--if done, take what we have so far and send it
                        if i + 1 == rowcount_unique:
                            logger.debug(u'Last email in set reached, sending consolidated email')
                            logger.info(u'Sending email to {}, CC {}, BCC {}, subject {}'.format(row[' Email To *'],
                                                                                    email_cc, email_bcc ,
                                                                                    row[' Email Subject *']))

                            try: # remove this later??
                                body, inlineattachments = append_body_and_inlineattachments(body, inlineattachments, row, vizcompleterefs, subscriberemail, vizurl, viewname, view, has_email_footer)
                                appendattachments = append_attachments(appendattachments, row, vizcompleterefs, has_email_attachment)
                                
                                # send the email

                                send_email(email_from, row[' Email To *'], row[' Email Subject *'],
                                           u''.join(body), email_cc, email_bcc, inlineattachments, appendattachments)
                            except Exception as e:
                                errormessage = u'Failed to send the email. Exception:<br> {}'.format(e)
                                logger.error(errormessage)
                                raise UserWarning(errormessage)
                            # reset variables for next email
                            body = []
                            inlineattachments = []
                            consolidate_email_ctr = 0
                            appendattachments = []
                        else:
                            # This isn't the end, and we're consolidating rows, so test to see if the next row needs
                                # to be a new email
                            this_row_recipients = []
                            next_row_recipients = []

                            this_row_recipients.append(row[' Email Subject *'])
                            this_row_recipients.append(row[' Email To *'])
                            this_row_recipients.append(email_from)

                            next_row_recipients.append(data[i + 1][' Email Subject *'])
                            next_row_recipients.append(data[i + 1][' Email To *'])
                            if has_email_from:
                                next_row_recipients.append(data[i + 1][' Email From ~'])
                            else:
                                next_row_recipients.append(email_from)

                            if has_email_cc:
                                this_row_recipients.append(email_cc)
                                next_row_recipients.append(data[i + 1][' Email CC ~'])

                            if has_email_bcc:
                                this_row_recipients.append(email_bcc)
                                next_row_recipients.append(data[i + 1][' Email BCC ~'])

                            # Now compare the data from the rows
                            if this_row_recipients == next_row_recipients:
                                logger.debug(u'Next row matches recips and subject, appending body & attachments')
                                body.append(row[' Email Body *'])
                                if has_email_attachment and len(row[' Email Attachment ~']) > 0:
                                    appendattachments = append_attachments(appendattachments, row, vizcompleterefs, has_email_attachment)
                                consolidate_email_ctr += 1
                            else:
                                logger.debug(u'Next row does not match recips and subject, sending consolidated email')
                                logger.info(u'Sending email to {}, CC {}, BCC {}, Subject {}'.format(row[' Email To *'],
                                                                                        email_cc , email_bcc,
                                                                                        row[' Email Subject *']))

                                body, inlineattachments = append_body_and_inlineattachments(body, inlineattachments, row, vizcompleterefs, subscriberemail, vizurl, viewname, view, has_email_footer)
                                appendattachments = append_attachments(appendattachments, row, vizcompleterefs, has_email_attachment)

                                # send the email
                                try:

                                    send_email(email_from, row[' Email To *'], row[' Email Subject *'],
                                            u''.join(body), email_cc, email_bcc, inlineattachments, appendattachments)
                                except Exception as e:
                                    errormessage = u'Failed to send the email. Exception:<br> {}'.format(e)
                                    logger.error(errormessage)
                                    raise UserWarning(errormessage)

                                body = []
                                consolidate_email_ctr = 0
                                inlineattachments = []
                                appendattachments = []
                    else:
                        # emails are not being consolidated, so send the email
                        logger.info(u'Sending email to {}, CC {}, BCC {}, Subject {}'.format(row[' Email To *'],
                                                                                email_cc , email_bcc,
                                                                                row[' Email Subject *']))
                        consolidate_email_ctr = 0 # I think this is redundant now...
                        body = []

                        # add the header if needed
                        if has_email_header:
                            body.append(row[' Email Header ~'])

                        body, inlineattachments = append_body_and_inlineattachments(body, inlineattachments, row, vizcompleterefs, subscriberemail, vizurl, viewname, view, has_email_footer)
                        appendattachments = append_attachments(appendattachments, row, vizcompleterefs, has_email_attachment)

                            
                        try:

                            send_email(email_from, row[' Email To *'], row[' Email Subject *'], u''.join(body), email_cc,
                                    email_bcc, inlineattachments, appendattachments)
                        except Exception as e:
                            errormessage = u'Failed to send the email. Exception:<br> {}'.format(e)
                            logger.error(errormessage)
                            raise UserWarning(errormessage)

                        inlineattachments = []
                        body = []
                        appendattachments=[]

                # this is an SMS Action
                elif row[' Email Action *'] == SMS_ACTION:
                    
                    # check that SMS actions are available
                    if SMS_ACTION_AVAILABLE == False:
                        errormessage = u'Trigger view {} was set up to send SMS but this VizAlerts install has not been configured for SMS Actions, please contact your Tableau Server admin.'.format(view["view_name"])
                        logger.error(errormessage)
                        raise UserWarning(errormessage)
                  
                    logger.info(u'Sending SMS to {}, CC {}, BCC {}, Subject {}'.format(row[' Email To *'],
                                                                            email_cc , email_bcc,
                                                                            row[' Email Subject *']))
                    consolidate_email_ctr = 0 # I think this is redundant now...
                    body = []

                    # add the header if needed
                    if has_email_header:
                        body.append(row[' Email Header ~'])

                    body.append(row[' Email Body *'])

                    # add the footer if needed, otherwise no footer
                    if has_email_footer:
                        body.append(row[' Email Footer ~'].replace(DEFAULT_FOOTER,
                            bodyfooter.format(subscriberemail, vizurl, viewname)))
                    
                    body = sms_append_body(body, row, vizcompleterefs, subscriberemail, vizurl, viewname, view)
                    
                    # make list of all SMS addresses - they already went through 1st validation
                    smsaddresses = re.split(SMS_RECIP_SPLIT_REGEX, row[' Email To *'].strip())

                    if has_email_cc:
                        smsaddresses.extend(re.split(SMS_RECIP_SPLIT_REGEX, email_cc.strip()))

                    if has_email_bcc:
                        smsaddresses.extend(re.split(SMS_RECIP_SPLIT_REGEX, email_bcc.strip()))

                    # send the message
                    for smsaddress in smsaddresses:
                        errormessage = smsaction.send_sms(configs, logger, smsclient, email_from, smsaddress, row[' Email Subject *'], u' '.join(body))

                        if errormessage != None:
                            view_failure(view, u'VizAlerts was unable to process this view due to the following error: {}'.format(e))

        else:
            # missing any valid action
            logger.info(u'No valid actions specified in view data for {}, skipping'.format(viewurlsuffix))
            return


def get_mimetype(filename):
    """Returns the MIME type of the given file.

    :param filename: A valid path to a file
    :type filename: str

    :returns: The file's MIME type
    :rtype: tuple
    """
    content_type, encoding = guess_type(filename)
    if content_type is None or encoding is not None:
        content_type = "application/octet-stream"
    return content_type.split("/", 1)


def mimify_file(filename, inline = True, overridename = None):
    """Returns an appropriate MIME object for the given file.

    :param filename: A valid path to a file
    :type filename: str

    :returns: A MIME object for the given file
    :rtype: instance of MIMEBase
    """

    filename = abspath(expanduser(filename))
    if overridename:
        basefilename = overridename
    else:
        basefilename = basename(filename)
    
    
    if inline:
        msg = MIMEBase(*get_mimetype(filename))
        msg.set_payload(open(filename, "rb").read())
        msg.add_header('Content-ID', '<{}>'.format(basefilename))
        msg.add_header('Content-Disposition', 'inline; filename="%s"' % basefilename)
    else:
        msg = MIMEBase(*get_mimetype(filename))
        msg.set_payload( open(filename,"rb").read() )
        if overridename:
            basefilename = overridename
           
        msg.add_header('Content-Disposition', 'attachment; filename="%s"' % basefilename)
        
    encode_base64(msg)
    return msg



def quit_script(message):
    """"Called when a fatal error is encountered in the script"""
    try:
        send_email(configs["smtp.address.from"], configs["smtp.address.to"], configs["smtp.subject"], message)
    except Exception as e:
        logger.error(u'Unknown error-sending exception alert email: {}'.format(e.message))
    sys.exit(1)


def view_failure(view, message, attachments=None):
    """Alert the Admin, and optionally the Subscriber, to a failure to process their alert"""

    subject = u'VizAlerts was unable to process view {}'.format(view["view_name"])
    body = message + u'<br><br>' + \
        u'<b>Details:</b><br><br>' + \
        u'<b>View URL:</b> <a href="{}">{}<a>'.format(get_view_url(view), get_view_url(view)) + u'<br>' \
        u'<b>Subscriber:</b> <a href="mailto:{}">{}</a>'.format(view['subscriber_email'], view['subscriber_sysname']) + u'<br>' \
        u'<b>View Owner:</b> <a href="mailto:{}">{}</a>'.format(view['owner_email'], view['owner_sysname']) + u'<br>' \
        u'<b>Site Id:</b> {}'.format(view['site_name']) + u'<br>' \
        u'<b>Project:</b> {}'.format(view['project_name'])

    if configs['smtp.notify_subscriber_on_failure'] == True:
        toaddrs = view['subscriber_email'] # email the Subscriber, cc the Admin
        ccaddrs = configs['smtp.address.to']
    else:
        toaddrs = configs['smtp.address.to'] # just email the Admin
        ccaddrs = None

    if attachments:
        logger.debug('Failure email should include attachment: {}'.format(attachments))

    try:
        send_email(configs['smtp.address.from'], toaddrs, subject,
                   body, ccaddrs, None, None, attachments)
    except Exception as e:
        logger.error(u'Unknown error sending exception alert email: {}'.format(e.message))


def validate_addresses(vizdata, has_email_from, has_email_cc, has_email_bcc):
    """Loops through the viz data for an Advanced Alert and returns a list of dicts
        containing any errors found in recipients"""

    errorlist = []
    rownum = 2 # account for field header in CSV

    for row in vizdata:
        result = addresses_are_invalid(row[' Email To *'], False, row[' Email Action *']) # empty string not acceptable as a To address
        if result:
            errorlist.append({'Row': rownum, 'Action':row[' Email Action *'], 'Field': ' Email To *', 'Value': result['address'], 'Error': result['errormessage']})
        if has_email_from:
            result = addresses_are_invalid(row[' Email From ~'], False, row[' Email Action *']) # empty string not acceptable as a From address
            if result:
                errorlist.append({'Row': rownum, 'Action':row[' Email Action *'], 'Field': ' Email From ~', 'Value': result['address'], 'Error': result['errormessage']})
        if has_email_cc:
            result = addresses_are_invalid(row[' Email CC ~'], True, row[' Email Action *'])
            if result:
                errorlist.append({'Row': rownum, 'Action':row[' Email Action *'], 'Field': ' Email CC ~', 'Value': result['address'], 'Error': result['errormessage']})
        if has_email_bcc:
            result = addresses_are_invalid(row[' Email BCC ~'], True, row[' Email Action *'])
            if result:
                errorlist.append({'Row': rownum, 'Action':row[' Email Action *'], 'Field': ' Email BCC ~', 'Value': result['address'], 'Error': result['errormessage']})
        rownum = rownum + 1

    return errorlist

    
def addresses_are_invalid(addresses, emptystringok, emailaction):
    """Validates all email addresses and phone numbers found in a given string"""
    logger.debug(u'Validating address field value: {}'.format(addresses))
    
    # split multiple values in a single trigger alert cell into a list
    if emailaction == EMAIL_ACTION:
        address_list = re.split(EMAIL_RECIP_SPLIT_REGEX, addresses.strip())
    elif emailaction == SMS_ACTION:
        address_list = re.split(SMS_RECIP_SPLIT_REGEX, addresses.strip())
        
    for address in address_list:
        logger.debug(u'Validating presumed address: {}'.format(address))
        if emptystringok and (address == '' or address is None):
            return None
        else:
            # testing email address
            if emailaction == EMAIL_ACTION:
                errormessage = address_is_invalid(address)
            elif emailaction == SMS_ACTION:
                errormessage = smsnumber_is_invalid(address)
                    
            if errormessage:
                logger.debug(u'Address is invalid: {}, Error: {}'.format(address, errormessage))
                if len(address) > 64:
                    address = address[:64] + '...' # truncate a too-long address for error formattting purposes
                return {'address':address, 'errormessage':errormessage}

    return None

def smsnumber_is_invalid(address):
    """Checks for a syntactically invalid phone number, returns None for success or an error message"""
    
    # phone number must not be empty
    if address is None or len(address) == 0 or address == '':
        errormessage = u'Phone number is empty'
        logger.error(errormessage )
        return errormessage

    # must be a phone number, not email address
    if '@' in address:
        errormessage = u'Found possible email address in phone number: {}'.format(address)
        logger.error(errormessage)
        return errormessage

    # check for other non-usable characters
    foundchars = re.findall(u'[^0-9 +.\-()]', address)
    if len(foundchars) > 0:
        errormessage = u'Found invalid characters {} in SMS number {}, only valid characters are numbers, space, hyphen, period, plus sign, and parentheses'.format(u''.join(foundchars), address)
        logger.error(errormessage)
        return errormessage
    
    # strip out everything but the numbers for these next checks
    phonenumber = re.sub('[^0-9]','',address)
    
    # phone number must be at least 8 characters (the global shortest with country code & number)
    if len(phonenumber) < 8:
        errormessage = u'Phone number is too short: {}'.format(address)
        logger.error(errormessage)
        return errormessage        
    
    #could potentially add checks here for valid country codes
    return None

def address_is_invalid(address):
    """Checks for a syntactically invalid email address."""
    # (most code derived from from http://zeth.net/archive/2008/05/03/email-syntax-check)

    # Email address must not be empty
    if address is None or len(address) == 0 or address == '':
        errormessage = u'Address is empty'
        logger.error(errormessage )
        return errormessage

    # Email address must be 6 characters in total.
    # This is not an RFC defined rule but is easy
    if len(address) < 6:
        errormessage = u'Address is too short: {}'.format(address)
        logger.error(errormessage)
        return errormessage

    # Unicode in addresses not yet supported
    try:
        address.decode('ascii')
    except Exception as e:
        errormessage = u'Address must contain only ASCII characers: {}'.format(address)
        logger.error(errormessage)
        return errormessage

    # Split up email address into parts.
    try:
        localpart, domainname = address.rsplit('@', 1)
        host, toplevel = domainname.rsplit('.', 1)
        logger.debug(u'Splitting Address: localpart, domainname, host, toplevel: {},{},{},{}'.format(localpart,
                                                                                                    domainname,
                                                                                                    host,
                                                                                                    toplevel))
    except UserWarning:
        errormessage = u'Address has too few parts'
        logger.error(errormessage)
        return errormessage

    # Validate domain if specified in config
    if len(configs["smtp.alloweddomains"]) > 0:
        if domainname not in configs["smtp.alloweddomains"]:
            errormessage = u'Address has invalid domain'
            logger.error(errormessage)
            return errormessage

    for i in '-_.%+.':
        localpart = localpart.replace(i, "")
    for i in '-_.':
        host = host.replace(i, "")

    logger.debug(u'Removing other characters from address: localpart, host: {},{}'.format(localpart, host))

    # check for length
    if len(localpart) > 64:
        errormessage = u'Localpart of address exceeds max length (65 characters)'
        logger.error(errormessage)
        return errormessage

    if len(address) > 254:
        errormessage = u'Address exceeds max length (254 characters)'
        logger.error(errormessage)
        return errormessage

    if localpart.isalnum() and host.isalnum():
        return None # Email address is fine.
    else:
        errormessage = u'Address has funny characters'
        logger.error(errormessage)
        return errormessage


def cleanup_dir(path, expiry_s):
    """Deletes all files in the provided path with modified time greater than expiry_s"""
    files = os.listdir(path)
    for file in files:
        file = os.path.join(path, file)
        fileinfo = os.stat(file)
        if (datetime.datetime.now() - datetime.datetime.fromtimestamp(fileinfo.st_mtime)).total_seconds() > expiry_s:
            os.remove(file)


def get_password_from_file(password):
    """If password is actually a valid path to a text file, returns contents of text file found. Otherwise returns the input string again"""
    # handle the None case--some passwords won't be specified but will still be run through this function
    if not password:
        return
    try:
        if os.path.exists(password):
            logger.debug(u'Opening password file {} for reading'.format(password))
            if not password.endswith('.txt'):
                logger.error(u'Password file at path {} is not a .txt file. Quitting.'.format(password))
                sys.exit(1)
            with open(password, 'rU') as fr:
                finalpassword = fr.read()
                return finalpassword
        else:
            return password
    except IOError as e:
        logger.error(u'IOError accessing password file at path {}. Quitting. Error: {}'.format(password, e.message))
        sys.exit(1)


def find_viz_refs(view, data, viewurlsuffix, has_email_header, has_email_footer, has_email_attachment):
    """ Given the data this searches through the body, header, footer, and attachment for all references to vizzes to be downloaded, downloads only the distinct vizzes (to avoid duplicating downloads). 
    
    Returns vizcompleterefs dictionary that contains a key of each distinct viz reference. The value is another dictionary with the following keys:
        vizref = the original viz reference string (the view_url_suffix)
        view_url_suffix = the workbook/viewname to be downloaded, plus any URL parameters the user has added
        formatstring = the format of the destination file, based on the VIZ_* reference
        imagepath = the full path to the temp tile for the downloaded viz 
        filename = the filename to use for appended attachments as well as exported files
        exportfilepath = the path to use for an exported file
        mergepdf = used for merging pdfs
        noattach = used with exportfilepath, makes the attachment not used
        
    """

    vizcompleterefs = dict()    # dict of dicts where each child dict is a content reference      
    vizrefs = []                # list of dicts where each dict is a content reference
    vizdistinctrefs = dict()    # the distinct list of content references

    distinctexportfilepaths = dict() # distinct list of export file paths for testing
    
    results = []                # list of content references found by regex
    logger.debug(u'Identifying content references')

    # data is the CSV that has been downloaded for a given view
    # loop through it to make a result set of all viz references
    for item in data:
        # this might be able to be more efficient code
        if 'VIZ_IMAGE' in item[' Email Body *'] or 'VIZ_LINK' in item[' Email Body *']:
            results.extend(re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_LINK\(.*?\)", item[' Email Body *']))

        if has_email_header:
            results.extend(re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_LINK\(.*?\)", item[' Email Header ~']))
            
        if has_email_footer:
            results.extend(re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_LINK\(.*?\)", item[' Email Footer ~']))
        
        if has_email_attachment:
            results.extend(re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_CSV\(.*?\)|VIZ_PDF\(.*?\)|VIZ_TWB\(.*?\)", item[' Email Attachment ~']))
    
    # loop through each found viz reference, i.e. everything in the VIZ_*(*).
    for vizref in results:
        if vizref not in vizcompleterefs:
            logger.debug(u'Parsing content reference {}'.format(vizref))
            # create a dictionary to hold the necessary values for this viz reference
            vizcompleterefs[vizref] = dict()
            
            # store the vizref itself as a value in the dict, will need later
            vizcompleterefs[vizref]['vizref'] = vizref
            
            # identifying the format for the output file
            vizrefformat = re.match(u'VIZ_(.*?)\(', vizref)
            if vizrefformat.group(1) == 'IMAGE':
                vizcompleterefs[vizref]['formatstring'] = 'PNG'
            else:
                vizcompleterefs[vizref]['formatstring'] = vizrefformat.group(1)
                
            # this section parses out the vizref into several parts:
            #   view_url_suffix - always present, this is the workbook/view plus any URL parameters
            #   filename - optional custom filename for appended attachments
            #   exportfilepath - optional custom path not yet supported)
            #   noattach - indicates that exported file shouldn't be attached to email
            #   mergepdf - option to merge multiple PDFs, only for VIZ_PDF()
            #   vizlink - option to have an inline VIZ_IMAGE() be a URL link
            #   rawlink - option to have a VIZ_LINK() not have any text, just the http: link
            
            # if the vizref is one of the placeholders i.e. just a VIZ_CSV() 
            # then we will be pulling down the calling viz
            if vizref in [IMAGE_PLACEHOLDER, PDF_PLACEHOLDER, CSV_PLACEHOLDER, TWB_PLACEHOLDER, VIZLINK_PLACEHOLDER]:
                vizcompleterefs[vizref]['view_url_suffix'] = viewurlsuffix
            else:
                # vizstring contains everything inside the VIZ_*() parentheses
                vizstring = re.match(u'VIZ_.*?\((.*?)\)', vizref)
                
                # vizstring may contain reference to the viz plus advanced alert parameters like
                # a filename or exportpathname.
                
                # if there is no delimiter then at this point we know the vizstring
                # is just a viz to use
                if ARGUMENT_DELIMITER not in vizstring.group(1):
                    # if the first character is ? then the content reference is something like
                    # VIZ_IMAGE(?Region=East) so we need to use the trigger viz
                    if vizstring.group(1)[0] == '?':
                        vizcompleterefs[vizref]['view_url_suffix'] = viewurlsuffix + vizstring.group(1)
                    else:
                        vizcompleterefs[vizref]['view_url_suffix'] = vizstring.group(1)
                # there are one or more arguments
                else:

                    # split vizstring into a list of arguments
                    vizstringlist = vizstring.group(1).split(ARGUMENT_DELIMITER)
                    
                    # first argument could be empty, such as VIZ_IMAGE(|filename=someFileName)
                    # in that case we'll use the calling viz
                    if vizstringlist[0] == '':
                        vizcompleterefs[vizref]['view_url_suffix'] = viewurlsuffix
                    # first argument could also be a URL parameter such as
                    # VIZ_IMAGE(?Region=East|filename=someFileName)
                    elif vizstringlist[0][0] == '?':
                        vizcompleterefs[vizref]['view_url_suffix'] = viewurlsuffix + vizstringlist[0]
                    # there are no arguments, so return only the entire view URL suffix
                    else:
                        vizcompleterefs[vizref]['view_url_suffix'] = vizstringlist[0]
                    
                    # if there is more than one element in the vizstring list then we
                    # know there are arguments to parse out
                    # this code could probably be simpler
                    if len(vizstringlist) > 1:
                        try:
                            # 0th element is the whole reference, so skip it
                            for element in vizstringlist[1:]:
                            
                                # looking for |exportfilename
                                if element.startswith(EXPORTFILENAME_ARGUMENT):
                                    filename = re.match(EXPORTFILENAME_ARGUMENT + u'=(.*)', element).group(1)
                                    # code from https://github.com/mitsuhiko/flask/blob/50dc2403526c5c5c67577767b05eb81e8fab0877/flask/helpers.py#L633
                                    # for validating filenames
                                    filename = posixpath.normpath(filename)
                                    for sep in _os_alt_seps:
                                        if sep in filename:
                                            errormessage = u'Found an invalid or non-allowed separator in filename: {} for content reference {}'.format(filename, vizref)
                                            logger.error(errormessage)
                                            raise UserWarning(errormessage)

                                    if os.path.isabs(filename) or '../' in filename or '..\\' in filename:
                                        errormessage = u'Found non-allowed path when expecting filename: {} for content reference {}'.format(filename, vizref)
                                        logger.error(errormessage)
                                        raise UserWarning(errormessage)
                                    
                                    # check for non-allowed characters
                                    # code based on https://mail.python.org/pipermail/tutor/2010-December/080883.html
                                    # using ($L) option to set locale to handle accented characters
                                    nonallowedchars = re.findall(u'(?L)[^\w \-._+]', filename)
                                    if len(nonallowedchars) > 0:
                                        errormessage = u'Found non-allowed character(s): {} in filename {} for content reference {}, only allowed characters are alphanumeric, space, hyphen, underscore, period, and plus sign'.format(u''.join(nonallowedchars), filename, vizref)
                                        logger.error(errormessage)
                                        raise UserWarning(errormessage)
                                    
                                    # if the output is anything but LINK then append the formatstring to the output filename
                                    if vizcompleterefs[vizref]['formatstring'] != 'LINK':
                                        vizcompleterefs[vizref]['filename'] = filename + '.' + vizcompleterefs[vizref]['formatstring'].lower()
                                    else:
                                        vizcompleterefs[vizref]['filename'] = filename
                                # end of if for |exportfilename
                                
                                # looking for |exportfilepath
                                if element.startswith(EXPORTFILEPATH_ARGUMENT):
                                
                                    # if the exportfile option is disabled (0) then raise an error
                                    # we'd rather error out then have someone trying to sneak out some data
                                    if configs['exportfile.mode'] == 0:
                                        errormessage = u'File export has not been enabled by your Tableau administrator, but found |exportfilepath option in content reference {}. Please contact your Tableau admin.'.format(vizref)
                                        logger.error(errormessage)
                                        raise UserWarning(errormessage)
                                    
                                    # get the file path
                                    exportfilepath = re.match(EXPORTFILEPATH_ARGUMENT + u'=(.*)', element).group(1)

                                    # make sure the exportfile path has a trailing \
                                    if exportfilepath[-1] != '/' or exportfilepath[-1] != '\\':
                                        exportfilepath = exportfilepath + '\\'

                                    exportfilepath = posixpath.normpath(exportfilepath)
                                    
                                    # check for absolute file path
                                    if not os.path.isabs(exportfilepath):
                                        errormessage = u'Found an invalid file export file path: {} for content reference {}. Only absolute UNC paths are allowed.'.format(exportfilepath, vizref)
                                        logger.error(errormessage)
                                        raise UserWarning(errormessage)

                                    # check for relative folders in file path
                                    if '../' in exportfilepath or '..\\' in exportfilepath:
                                        errormessage = u'Found a relative folder reference in export file path: {} for content reference {}. Only UNC paths are allowed.'.format(exportfilepath, vizref)
                                        logger.error(errormessage)
                                        raise UserWarning(errormessage)

                                    # check for redirect in file path
                                    if '>' in exportfilepath:
                                        errormessage = u'Found an attempted redirect in export file path: {} for content reference {}. Only UNC paths are allowed.'.format(exportfilepath, vizref)
                                        logger.error(errormessage)
                                        raise UserWarning(errormessage)
                                    
                                    
                                    # exportfile.mode = 1 only supports an admin-approvied list of allowed paths
                                    if configs['exportfile.mode'] == 1:
                                    
                                        # verifying exportfilepath is in list of allowed paths
                                        foundallowedpath = 0
                                        for allowedpath in configs['exportfile.allowedpaths']:
                                            if exportfilepath.startswith(allowedpath):
                                                foundallowedpath = 1
                                    
                                        if foundallowedpath != 1:
                                            raise UserWarning(u'Export file path {} is not in list of allowed file paths for content reference {}'.format(exportfilepath, vizref))
                                    
                                    # made it through all the tests so add the exportfilepath to the vizref dict
                                    vizcompleterefs[vizref][EXPORTFILEPATH_ARGUMENT] = exportfilepath
                                    # check for distinct file paths, will use later for testing
                                    if exportfilepath not in distinctexportfilepaths:
                                        distinctexportfilepaths[exportfilepath] = vizref
                                
                                # end of if for EXPORTFILEPATH_ARGUMENT
                                
                                #getting |noattach option
                                if element.startswith(NOATTACH_ARGUMENT):
                                    vizcompleterefs[vizref][NOATTACH_ARGUMENT] = 'y'            
                               
                                    
                                # looking for |mergepdf
                                if element.startswith(MERGEPDF_ARGUMENT) and vizcompleterefs[vizref]['formatstring'].lower() == 'pdf':
                                    vizcompleterefs[vizref][MERGEPDF_ARGUMENT] = 'y'
                                
                                # looking for |vizlink
                                if element.startswith(VIZLINK_ARGUMENT):
                                    vizcompleterefs[vizref][VIZLINK_ARGUMENT] = 'y'
                                
                                #looking for |rawlink
                                if element.startswith(RAWLINK_ARGUMENT):
                                    vizcompleterefs[vizref][RAWLINK_ARGUMENT] = 'y'

                        except Exception as e:
                            errormessage = u'Unable to process arguments to a content reference {} with error:<br><br> {}'.format(vizref, e.message)
                            logger.error(errormessage)
                            raise UserWarning(errormessage)
                            
                    # end of processing vizstringlist
                # end of checking for argument delimiters
            #end of parsing this vizref

            # creating distinct list of images to download
            # this is a dict so we have both the workbook/viewname aka view_url_suffix as well as the formatstring
            if vizref not in vizdistinctrefs and vizcompleterefs[vizref]['formatstring'] != 'LINK':
                vizdistinctrefs[vizref] = vizcompleterefs[vizref]
            
        #end if vizref not in vizcompleterefs
    #end for vizref in results

    # loop over distinctexportfilepaths to validate paths
    if len(distinctexportfilepaths) > 0:
        for exportfilepath in distinctexportfilepaths:
            if not os.path.exists(exportfilepath):
                errormessage = u'Export file path {} does not exist for content reference {}.'.format(exportfilepath, distinctexportfilepaths[exportfilepath])
                logger.error(errormessage)
                raise UserWarning(errormessage)
    
    #loop over vizdistinctrefs to download images, PDFs, etc. from Tableau
    for vizref in vizdistinctrefs:
        try:
            # set the view_url_suffix to the vizref so we can do the download
            view['view_url_suffix'] = vizdistinctrefs[vizref]['view_url_suffix']
            # export/render the viz to a file, store path to the download as value with vizref as key
            vizdistinctrefs[vizref]['imagepath'] = tabhttp.export_view(configs, view, eval('tabhttp.Format.' + vizdistinctrefs[vizref]['formatstring']), logger)
        
        except Exception as e:
            errormessage = u'Unable to render content reference {} with error:<br> {}'.format(vizref, e.message)
            logger.error(errormessage)
            raise UserWarning(errormessage)

    #reset view_url_suffix back to original calling view
    view['view_url_suffix'] = viewurlsuffix
    
    
    #now match vizdistinctrefs to original references to store the correct imagepaths
    for vizref in vizcompleterefs:
        if vizcompleterefs[vizref]['formatstring'] != 'LINK':
            vizcompleterefs[vizref]['imagepath'] = vizdistinctrefs[vizref]['imagepath']
    
    if len(vizcompleterefs) > 0:
        logger.debug(u'Returning all content references')
    return vizcompleterefs

    
def get_unique_vizdata(data, has_consolidate_email, has_email_from, has_email_cc, has_email_bcc, has_email_header, has_email_footer, has_email_attachment, has_email_sort_order):
    """Returns a unique list of all relevant email fields in data. Also sorts data in proper order."""

    preplist = [] # list of dicts containing only keys of concern for de-duplication from data
    uniquelist = [] # unique-ified list of dicts

    logger.debug(u'Start of get_unique_vizdata')
        
    # copy in only relevant fields from each record, non-VizAlerts fields will be ignored
    for item in data:
        newitem = dict()
        newitem[' Email Action *'] = item[' Email Action *']        
        for required in required_email_fields:
            newitem[required] = item[required]

        if has_consolidate_email:
            newitem[' Email Consolidate ~'] = item[' Email Consolidate ~']
        if has_email_from:
            newitem[' Email From ~'] = item[' Email From ~']
        if has_email_cc:
            newitem[' Email CC ~'] = item[' Email CC ~']
        if has_email_bcc:
            newitem[' Email BCC ~'] = item[' Email BCC ~']
        if has_email_header:
            newitem[' Email Header ~'] = item[' Email Header ~']
        if has_email_footer:
            newitem[' Email Footer ~'] = item[' Email Footer ~']
        if has_email_attachment:
            newitem[' Email Attachment ~'] = item[' Email Attachment ~']
        if has_email_sort_order:
            newitem[' Email Sort Order ~'] = item[' Email Sort Order ~']
            
        preplist.append(newitem)

    logger.debug(u'Removing duplicate alerts')

    # remove duplicates, preserving original ordering
    # proposed solution from http://stackoverflow.com/questions/9427163/remove-duplicate-dict-in-list-in-python

    seen = set()
    for dictitem in preplist:
        t = tuple(sorted(dictitem.items()))
        if t not in seen:
            seen.add(t)
            uniquelist.append(dictitem)
    
    logger.debug(u'Sorting unique rows')

    # the data must now be sorted for use in Advanced Alerts with email consolidation
    if has_consolidate_email == True:
        # Email Sort Order is used because the downloaded trigger csv can be re-ordered during
        # the download process from the original csv. Not trying to have a distinct sort
        # order because the email/SMS delivery is subject to queueing in the email/SMS provider servers
        if has_email_sort_order:
            uniquelist = sorted(uniquelist, key=itemgetter(u' Email Sort Order ~'))
        if has_email_bcc:
            uniquelist = sorted(uniquelist, key=itemgetter(u' Email BCC ~'))
        if has_email_cc:
            uniquelist = sorted(uniquelist, key=itemgetter(u' Email CC ~'))
        if has_email_from:
            uniquelist = sorted(uniquelist, key=itemgetter(u' Email From ~'))
        # sort by Subject and To
        uniquelist = sorted(uniquelist, key=itemgetter(u' Email Subject *', u' Email To *'))
        # sort by Email Action to ensure consolidated emails don't get munged by SMS emails
        uniquelist = sorted(uniquelist, key=itemgetter(u' Email Action *'))
        
    logger.debug(u'Done sorting, returning the list')

    # return the list
    return uniquelist


def replace_in_list(inlist, findstr, replacestr):
    """Replaces all occurrences of a string in a list of strings"""
    
    outlist = []
    foundstring = False
    for item in inlist:
        # logger.debug(u'Attempting to find {} ({}) in {} ({})'.format(findstr, type(findstr), item, type(item))) # REMOVE THIS LATER
        if item.find(findstr) <> -1:
            foundstring = True
        outlist.append(item.replace(findstr, replacestr))

    # return a dictionary with a boolean indicating whether we did replace anything, and the new list
    return {'foundstring':foundstring, 'outlist':outlist}


def get_view_url(view, customviewurlsuffix = None):
    """Construct the full URL of the view"""

    # this logic should be removed--empty string should be passed in from SQL
    sitename = unicode(view["site_name"]).replace('Default', '')

    if customviewurlsuffix == None:
        customviewurlsuffix = view['view_url_suffix']
    
    # (omitting hash preserves 8.x functionality)
    if sitename == '':
        vizurl = u'http://' + configs["server"] + u'/views/' + customviewurlsuffix
    else:
        vizurl = u'http://' + configs["server"] + u'/t/' + sitename + u'/views/' + customviewurlsuffix

    return vizurl


def get_footer(subscriberemail, subscribersysname, subscriberdomain, vizurl, viewname, simplealert, server_version):
    """Get the footer text for an email alert"""
    httpprefix = u'http://'
    if configs["server.ssl"]:
        httpprefix = u'https://'

    footer = u'<br><br><font size="2"><i>This VizAlerts email generated on behalf of <a href="mailto:{}">{}</a>, from view <a href="{}">' \
                 '{}</a></i></font>'.format(subscriberemail, subscribersysname, vizurl, viewname)
    if simplealert:
        managesuburlv8 = httpprefix + configs["server"] + u'/users/' + subscribersysname
        managesuburlv9 = httpprefix + configs["server"] + u'/#/user/'
        if subscriberdomain:
            managesuburlv9 = managesuburlv9 + subscriberdomain + u'/' + subscribersysname + u'/subscriptions'
        else:
            managesuburlv9 = managesuburlv9 + u'local/' + subscribersysname + u'/subscriptions'

        managesublink = u'<br><font size="2"><i><a href="{}">Manage my subscription settings</a></i></font>'

        if server_version == 8:
            footer = footer + managesublink.format(managesuburlv8)
        if server_version == 9:
            footer = footer + managesublink.format(managesuburlv9)

    return footer

def append_attachments(appendattachments, row, vizcompleterefs, has_email_attachment):
    """generic function for adding appended (non-inline) attachments"""

    # there can be multiple content references in a single email attachment field
    # and order is important if these attachments are to be merged later
    # so we generate the list with a regex
    if has_email_attachment:
        attachmentrefs = []
        attachmentrefs = re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_CSV\(.*?\)|VIZ_PDF\(.*?\)|VIZ_TWB\(.*?\)", row[' Email Attachment ~'])
        if len(attachmentrefs) > 0:
            logger.debug('Adding appended attachments to list')
        for attachmentref in attachmentrefs:
            # only make appended attachments when they are needed
            if attachmentref not in appendattachments:
                appendattachments.append(vizcompleterefs[attachmentref])

    return(appendattachments)
 
    
def append_body_and_inlineattachments(body, inlineattachments, row, vizcompleterefs, subscriberemail, vizurl, viewname, view, has_email_footer):
    """Generic function for filling email body text with the body & footers from the csv plus inserting viz references"""
    """for inline attachments and hyperlink text"""

    logger.debug('Replacing body text with exact content references for inline attachments and hyperlinks')
    body.append(row[' Email Body *'])

    # add the footer if needed
    if has_email_footer:
        body.append(row[' Email Footer ~'].replace(DEFAULT_FOOTER,
                            bodyfooter.format(subscriberemail, vizurl, viewname)))
    else:
        # no footer specified, add the default footer
        body.append(bodyfooter.format(subscriberemail, vizurl, viewname))

    # find all distinct content references in the email body list 
    # so we can replace each with an inline image or hyperlink text
    foundcontent = re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_LINK\(.*?\)", ' '.join(body))
    foundcontentset = set(foundcontent)
    vizrefs = list(foundcontentset)
    
    if len(vizrefs) > 0:
        for vizref in vizrefs:
            # replacing VIZ_IMAGE() with inline images
            if vizcompleterefs[vizref]['formatstring'] == 'PNG':
                # add hyperlinks to images if necessary
                if VIZLINK_ARGUMENT in vizcompleterefs[vizref] and vizcompleterefs[vizref][VIZLINK_ARGUMENT] == 'y':
                    replacestring = u'<a href="' + get_view_url(view, vizcompleterefs[vizref]['view_url_suffix']) + u'"><img src="cid:{}">'.format(basename(vizcompleterefs[vizref]['imagepath'])) +u'</a>'
                else:
                    replacestring = u'<img src="cid:{}">'.format(basename(vizcompleterefs[vizref]['imagepath']))
                    
                replaceresult = replace_in_list(body, vizref, replacestring)
                
                if replaceresult['foundstring'] == True:
                    body = replaceresult['outlist']
                    
                    # create a list of inline attachments
                    if vizcompleterefs[vizref] not in inlineattachments:
                        inlineattachments.append(vizcompleterefs[vizref])
                else:
                    raise UserWarning(u'Unable to locate downloaded image for {}, check whether the content reference is properly URL encoded.'.format(vizref))
            
            # we're replacing #VIZ_LINK text
            elif vizcompleterefs[vizref]['formatstring'] == 'LINK':
                # use raw link if that option is present
                
                if RAWLINK_ARGUMENT in vizcompleterefs[vizref] and vizcompleterefs[vizref][RAWLINK_ARGUMENT] == 'y':
                    replacestring = get_view_url(view, vizcompleterefs[vizref]['view_url_suffix'])
                else:
                    # test for whether the filename field is used, if so that is the link text
                    if 'filename' in vizcompleterefs[vizref] and len(vizcompleterefs[vizref]['filename']) > 0:
                        replacestring = u'<a href="' + get_view_url(view, vizcompleterefs[vizref]['view_url_suffix']) + u'">' + vizcompleterefs[vizref]['filename'] + u'</a>'
                    # use the view_url_suffix as the link text
                    else:
                        replacestring = u'<a href="' + get_view_url(view, vizcompleterefs[vizref]['view_url_suffix']) + u'">' + vizcompleterefs[vizref]['view_url_suffix'] + u'</a>'
                   
                replaceresult = replace_in_list(body, vizref, replacestring)
                
                if replaceresult['foundstring'] == True:
                    body = replaceresult['outlist']    
                
    return body, inlineattachments

def sms_append_body(body, row, vizcompleterefs, subscriberemail, vizurl, viewname, view):
    """Generic function for filling SMS body text with hyperlink references"""
    """for inline attachments and hyperlink text"""

    logger.debug('Replacing SMS text with exact content references for hyperlinks')

    # find all distinct content references in the email body list 
    # so we can replace each with an inline image or hyperlink text
    foundcontent = re.findall(u"VIZ_LINK\(.*?\)", ' '.join(body))
    foundcontentset = set(foundcontent)
    vizrefs = list(foundcontentset)
    
    if len(vizrefs) > 0:
        for vizref in vizrefs:
            # we're replacing #VIZ_LINK text
            if vizcompleterefs[vizref]['formatstring'] == 'LINK':

                # always use raw link, ignore presence or absence of RAWLINK argument
                replacestring = get_view_url(view, vizcompleterefs[vizref]['view_url_suffix'])
                replaceresult = replace_in_list(body, vizref, replacestring)
                
                if replaceresult['foundstring'] == True:
                    body = replaceresult['outlist']    
                
    return body


def merge_pdf_attachments(appendattachments):
    """ Checks the list of appended attachments for any merged pdfs. Any pdf attachments that need to be merged are merged, then the revised attachments is returned"""

    tempdir = configs["temp.dir"]

    revisedappendattachments = []

    mergedfilenames = dict()    
    # loop through append attachments list to find the potential merges
    for attachment in appendattachments:
        if 'mergepdf' in attachment:
            # there could be multiple merges in a single output, so start a list with the attachments
            if attachment['filename'] not in mergedfilenames:
                mergedfilenames[attachment['filename']] = OrderedDict()
            
            mergedfilenames[attachment['filename']][attachment['vizref']] = attachment
 
        # this isn't a merged pdf, so just append the attachment
        else:
            revisedappendattachments.append(attachment)

     
    if mergedfilenames:
        
        # loop through list of filenames to merge the PDFs
        for listtomerge in mergedfilenames:


            # if there's only one PDF to merge then let's not go any further, just use the attachment
            if len(mergedfilenames[listtomerge]) == 1:
                logger.debug(u'Request to merge multiple PDFs into ' + listtomerge + ', only one PDF found')
                for attachment in mergedfilenames[listtomerge]:
                    revisedappendattachments.append(mergedfilenames[listtomerge][attachment])
            
            # now to merge some PDFs:
            else:
                logger.debug(u'Merging PDFs for ' + listtomerge)
           
                try:
                    # we know all attachments in a given list have the same filename due to the loop above
                    # so we can just pull the first one

                    merger = PdfFileMerger()

                    i = 0
                    for attachment in mergedfilenames[listtomerge]:
                        if i == 0:
                            mergedfilename = mergedfilenames[listtomerge][attachment]['filename']
                            # getting exportfilepath and noattach flags for first PDF in a merged PDF
                            if EXPORTFILEPATH_ARGUMENT in mergedfilenames[listtomerge][attachment]:
                                exportfilepath = mergedfilenames[listtomerge][attachment][EXPORTFILEPATH_ARGUMENT]
                            else:
                                exportfilepath = None

                            if NOATTACH_ARGUMENT in mergedfilenames[listtomerge][attachment]:
                                noattach = mergedfilenames[listtomerge][attachment][NOATTACH_ARGUMENT]
                            else:
                                noattach = None
                        
                        
                        merger.append(PdfFileReader(mergedfilenames[listtomerge][attachment]['imagepath'], "rb"))
                        i = i + 1
                    
                    # make the temp filename for the merged pdf
                    datestring = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
                    mergedfilepath = tempdir + datestring + '_' + mergedfilename
                
                    merger.write(mergedfilepath)

                    mergedattachment = {'filename' : mergedfilename, 'imagepath' : mergedfilepath, 'formatstring' : 'PDF', 'vizref' : 'mergepdf file ' + 'filename'}
                    
                    # adding exportfilepath and noattach to the mergedattachment
                    if exportfilepath != None:
                        mergedattachment[EXPORTFILEPATH_ARGUMENT] = exportfilepath
                        
                    if noattach != None:
                        mergedattachment[NOATTACH_ARGUMENT] = noattach
                    
                    revisedappendattachments.append(mergedattachment)
                except Exception as e:
                    logger.error(u'Could not generate merged PDF for filename {}: {}'.format(mergedfilename, e))
                    raise e
            
    return(revisedappendattachments)
 
def deliver_exportfile(vizref):
    """Generic function to deliver an exported file to the right folder. Argument is a vizref dict"""
    
    # check that we are exporting a file
    if EXPORTFILEPATH_ARGUMENT in vizref:
        # check for whether there is a custom filename
        if EXPORTFILENAME_ARGUMENT not in vizref:
            head, tail = os.path.split(vizref['imagepath'])
            exportpath = vizref[EXPORTFILEPATH_ARGUMENT] + tail
        else:
            exportpath = vizref[EXPORTFILEPATH_ARGUMENT] + vizref[EXPORTFILENAME_ARGUMENT]
        
        #will overwrite files if multiple alerts all have the same exportfilepath & filename
        try:
            logger.info(u'Delivering file to {}'.format(exportpath))
            shutil.copyfile(vizref['imagepath'], exportpath)
            return 
            
        except Exception as e:
            logger.error(u'Failed to deliver file {}: {}'.format(exportpath, e))
            raise e
            
def send_email(fromaddr, toaddrs, subject, content, ccaddrs=None, bccaddrs=None, inlineattachments=None, appendattachments=None):
    """Generic function to send an email. The presumption is that all arguments have been validated prior to the call to this function.
    
    Input arguments are:
        fromaddr    single email address
        toaddr      string of recipient email addresses separated by the list of separators in EMAIL_RECIP_SPLIT_REGEX
        subject     string that is subject of email
        content     body of email, may contain HTML
        ccaddrs     cc recipients, see toaddr
        bccaddrs    bcc recipients, see toaddr
        inlineattachments   List of vizref dicts where each dict has one attachment. The minimum dict has an 
                            imagepath key that points to the file to be attached.
        appendattachments   Appended (non-inline attachments). See inlineattachments for details on structure.
    
    Nothing is returned by this function unless there is an exception.
    
    """
    try:
        logger.info(u'sending email: {},{},{},{},{},{},{}'.format(configs["smtp.serv"], fromaddr, toaddrs, ccaddrs, bccaddrs,
                                                              subject, inlineattachments, appendattachments))
        logger.debug(u'email body: {}'.format(content))

        # using mixed type because there can be inline and non-inline attachments
        msg = MIMEMultipart('mixed')
        msg.set_charset('utf-8')
        msg.preamble = subject.encode('utf-8')
        msg['From'] = Header(fromaddr)
        msg['Subject'] = Header(subject.encode('utf-8'), 'UTF-8').encode()

        # Process direct recipients
        toaddrs = re.split(EMAIL_RECIP_SPLIT_REGEX, toaddrs.strip())
        msg['To'] = Header(', '.join(toaddrs))
        allrecips = toaddrs

        # Process indirect recipients
        if ccaddrs:
            ccaddrs = re.split(EMAIL_RECIP_SPLIT_REGEX, ccaddrs.strip())
            msg['CC'] = Header(', '.join(ccaddrs))
            allrecips.extend(ccaddrs)

        if bccaddrs:
            bccaddrs = re.split(EMAIL_RECIP_SPLIT_REGEX, bccaddrs.strip())
            # don't add to header, they are blind carbon-copied
            allrecips.extend(bccaddrs)

        # Create a section for the body and inline attachments
        msgalternative = MIMEMultipart(u'related')
        msg.attach(msgalternative)
        msgalternative.attach(MIMEText(content.encode('utf-8'), 'html', 'utf-8'))
        
        # Add inline attachments
        if inlineattachments != None:
            for vizref in inlineattachments:
                msgalternative.attach(mimify_file(vizref['imagepath'], inline = True))

        # Add appended attachments from Email Attachments field and prevent dup custom filenames
        appendedfilenames = []
        if appendattachments != None:
            appendattachments = merge_pdf_attachments(appendattachments)
            for vizref in appendattachments:

                # deliver exported images
                if EXPORTFILEPATH_ARGUMENT in vizref:
                    try:
                        deliver_exportfile(vizref)
                    except Exception as e:
                        raise e
                  
                # verify that we are ok to append the attachment
                if NOATTACH_ARGUMENT not in vizref:
                    # if there is no |filename= option set then use the exported imagepath
                    if EXPORTFILENAME_ARGUMENT not in vizref:
                        msg.attach(mimify_file(vizref['imagepath'], inline = False))
                    else:
                        # we need to make sure the custom filename is unique, if so then
                        # use the custom filename
                        if vizref['filename'] not in appendedfilenames:
                            appendedfilenames.append(vizref['filename'])
                            msg.attach(mimify_file(vizref['imagepath'], inline = False, overridename = vizref['filename']))
                        # use the exported imagepath
                        else:
                            msg.attach(mimify_file(vizref['imagepath'], inline = False))
                            logger.info(u'Warning: attempted to attach duplicate filename ' + vizref['filename'] + ', using unique auto-generated name instead.')
        server = smtplib.SMTP(configs["smtp.serv"])
        if configs["smtp.ssl"]:
            server.ehlo()
            server.starttls()
        if configs["smtp.user"]:
            server.login(configs["smtp.user"], configs["smtp.password"])

        # from http://wordeology.com/computer/how-to-send-good-unicode-email-with-python.html
        io = StringIO()
        g = Generator(io, False) # second argument means "should I mangle From?"
        g.flatten(msg)

        server.sendmail(fromaddr.encode('utf-8'), [addr.encode('utf-8') for addr in allrecips], io.getvalue())
        server.quit()
    except smtplib.SMTPConnectError as e:
        logger.error(u'Email failed to send; there was an issue connecting to the SMTP server: {}'.format(e))
        raise e
    except smtplib.SMTPHeloError as e:
        logger.error(u'Email failed to send; the SMTP server refused our HELO message: {}'.format(e))
        raise e
    except smtplib.SMTPAuthenticationError as e:
        logger.error(u'Email failed to send; there was an issue authenticating to SMTP server: {}'.format(e))
        raise e
    except smtplib.SMTPException as e:
        logger.error(u'Email failed to send; there was an issue sending mail via SMTP server: {}'.format(e))
        raise e
    except Exception as e:
        logger.error(u'Email failed to send: {}'.format(e))
        raise e


if __name__ == "__main__":
    exitcode = 0
    try:
        #main(*sys.argv)
        main()
        exitcode = 0
    except:
        logger.exception(u'An unhandled exception occurred: %s' % traceback.format_exc(sys.exc_info()))
        exitcode = 1
    finally:
        sys.exit(exitcode)

