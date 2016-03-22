#! python
# -*- coding: utf-8 -*-
# Script to generate conditional automation against published views from a Tableau Server instance

__author__ = 'mcoles'

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

# Tableau modules
import tabUtil
from tabUtil import tabhttp

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
        'smtp.subject',
        'temp.dir',
        'temp.dir.file_retention_seconds',
        'trusted.clientip',
        'trusted.useclientip',
        'viz.data.maxrows',
        'viz.data.timeout',
        'viz.png.height',
        'viz.png.width']

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

# regular expresstion used to split recipient address strings into separate email addresses
EMAIL_RECIP_SPLIT_REGEX = u'[; ,]*'

# name of the file used for maintaining subscriptions state in schedule.state.dir
SCHEDULE_STATE_FILENAME = u'vizalerts.state'

# reserved strings for Advanced Alerts embedding
IMAGE_PLACEHOLDER = u'VIZ_IMAGE()' # special string for embedding viz images in Advanced Alert body
PDF_PLACEHOLDER = u'VIZ_PDF()'
CSV_PLACEHOLDER = u'VIZ_CSV()'
TWB_PLACEHOLDER = u'VIZ_TWB()'
DEFAULT_FOOTER = u'VIZALERTS_FOOTER()' # special string for embedding the default footer in an Advanced Alert

# reserved strings for Advanced Alerts file export arguments
EXPORTFILENAME_ARGUMENT = u'filename'
EXPORTFILEPATH_ARGUMENT = u'exportfilepath'
ARGUMENT_DELIMITER = u'|'

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

    # cleanup old temp files
    try:
        cleanup_dir(configs["temp.dir"], configs["temp.dir.file_retention_seconds"])
    except Exception as e:
        errormessage = u'Unable to cleanup temp directory {}, error: {}'.format(configs["temp.dir"], e.message)
        logger.error(errormessage)
        quit_script(errormessage)

    # cleanup old log files
    try:
        cleanup_dir(configs["log.dir"], configs["log.dir.file_retention_seconds"])
    except Exception as e:
        errormessage = u'Unable to cleanup log directory {}, error: {}'.format(configs["log.dir"], e.message)
        logger.error(errormessage)
        quit_script(errormessage)

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
        logger.debug(viewurlsuffix)
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
            message = u'Unable to send email to address {} for view {}, view id {}: {}'.format(subscriberemail, viewname, view["view_id"], subscriberemailerror)
            logger.error(message)
            send_email(configs["smtp.address.from"], configs["smtp.address.to"], configs["smtp.subject"], message)
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
            errormessage = u'Unable to process data from viewname {}, error: {}'.format(viewname, e)
            logger.error(errormessage)
            view_failure(view, u'VizAlerts was unable to process this view due to the following error: {}'.format(e))
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
        test_ticket = tabhttp.get_trusted_ticket(configs["server"], sitename, configs["server.user"], configs["server.ssl"], logger, None, clientip)
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

            inlineattachments = []
            for tmppath in [csvpath, imagepath]
                tmpattachment = dict()
                tmpattachment['imagepath'] = tmppath
                inlineattachments.append(tmpattachment)
            
            # embed the viz image
            inlineattachments = [csvpath, imagepath]
            logger.info(u'Sending simple alert email to user {}'.format(subscriberemail))
            body = u'<a href="{}"><img src="cid:{}"></a>'.format(vizurl, basename(imagepath)) +\
                   bodyfooter.format(subscriberemail, vizurl, viewname)
            subject = unicode(u'Alert triggered for {}'.format(viewname))
            send_email(configs["smtp.address.from"], subscriberemail, subject, body,
                       None, None, inlineattachments)
            return
        except Exception as e:
            errormessage = u'Alert was triggered, but encountered a failure rendering data/image: {}'.format(e.message)
            logger.error(errormessage)
            view_failure(view, errormessage)
            raise e
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

            logger.debug(u'Validating email addresses')
            # validate all From and Recipient addresses
            addresserrors = validate_addresses(data, has_email_from, has_email_cc, has_email_bcc)
            if addresserrors:
                errormessage = u'Invalid email addresses found, details to be emailed.'
                logger.error(errormessage)

                # Need to send a custom email for this error
                addresslist = u'<table border=1><tr><b><td>Row</td><td width="75">Field</td><td>Value</td><td>Error</td></b></tr>'
                for adderror in addresserrors:
                    addresslist = addresslist + u'<tr><td width="75">{}</td><td width="75">{}</td><td>{}</td><td>{}</td></tr>'.format(adderror['Row'],
                                                                                                                adderror['Field'],
                                                                                                                adderror['Value'],
                                                                                                                adderror['Error'],)
                addresslist = addresslist + u'</table>'
                view_failure(view, u'VizAlerts was unable to process this view due to the following error: ' + \
                                u'Errors found in recipients:<br><br>{}'.format(addresslist) + \
                                u'<br><br>See row numbers in attached CSV file.' ,
                                [csvpath])
                return

            # eliminate duplicate rows and ensure proper sorting
            data = get_unique_vizdata(data, has_consolidate_email, has_email_from, has_email_cc, has_email_bcc, has_email_header, has_email_footer, has_email_attachment)
            rowcount_unique = len(data)

            # could be multiple viz's (including PDF, CSV, TWB) for a single row in the CSV
            # return a list of all found VIZ_*() strings including any custom views w/ or w/out URL parameters as well
            # as VizAlerts parameters. The structure is: 
            # VIZ_*([optional custom view w/optional custom URL parameters]|[optional VizAlerts parameters])
            #   - The custom view could be myWorkbook/myView?field1=value1
            #   - The VizAlerts parameters are separated by | (pipe) characters since they are 
            #       technically not allowed in URL parameters. The two VizAlerts parameters are:
            #       - filename=[filename used for attachments and file export without extension]
            #       - exportpathname=[pathname used for file export]

            vizcompleterefs = dict()

            try:
                vizcompleterefs = find_viz_refs(data, viewurlsuffix, has_email_header, has_email_footer, has_email_attachment)
            except Exception as e:
                errormessage = u'Alert was triggered, but encountered a failure getting data/image references: {}'.format(e.message)
                logger.error(errormessage)
                view_failure(view, errormessage)
                raise e
            
            # iterate through the rows and send emails accordingly
            consolidate_email_ctr = 0
            body = []
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
                    email_from = configs["smtp.address.from"]   # use default from config file

                # get the other recipient addresses
                if has_email_cc:
                    email_cc = row[' Email CC ~']
                else:
                    email_cc = None

                if has_email_bcc:
                    email_bcc = row[' Email BCC ~']
                else:
                    email_bcc = None

                if row[' Email Action *'] == '1':
                    logger.debug(u'Starting email action')

                    # Append header row, if provided
                    if has_email_header and consolidate_email_ctr == 0:
                        logger.debug(u'has_email_header is {} and consolidate_email_ctr is '
                                     u'{}, so appending body header'.format(has_email_header, consolidate_email_ctr))
                        body.append(row[' Email Header ~'])

                    # If rows are being consolidated, consolidate all with same recipients & subject
                    if has_consolidate_email:
                        logger.debug(u'Consolidate field exists, testing for true')
                        if row[' Email Consolidate ~'] == '1':
                            logger.debug(u'Consolidate value is true, row index is {}, rowcount is {}'.format(i, rowcount_unique))

                            # test for end of iteration--if done, take what we have so far and send it
                            if i + 1 == rowcount_unique:
                                logger.debug(u'Last email in set reached, sending consolidated email')
                                logger.info(u'Sending email to {}, CC {}, BCC {}, subject {}'.format(row[' Email To *'],
                                                                                        email_cc, email_bcc ,
                                                                                        row[' Email Subject *']))
                                try: # remove this later??
                                    body, inlineattachments, appendattachments = append_body_and_attachments(body, inlineattachments, appendattachments, row, imagepaths, subscriberemail, vizurl, viewname, has_email_footer, has_email_attachment)
                                    
                                    # send the email
                                    send_email(email_from, row[' Email To *'], row[' Email Subject *'],
                                               u''.join(body), email_cc, email_bcc, inlineattachments, appendattachments, imagefilenames)
                                except Exception as e:
                                    logger.error(u'Failed to send the email. Exception: {}'.format(e))
                                    view_failure(view, u'VizAlerts was unable to process this view due to the following error: {}'.format(e))

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
                                    logger.debug(u'Next row matches recips and subject, appending body')
                                    body.append(row[' Email Body *'])
                                    consolidate_email_ctr += 1
                                else:
                                    logger.debug(u'Next row does not match recips and subject, sending consolidated email')
                                    logger.info(u'Sending email to {}, CC {}, BCC {}, Subject {}'.format(row[' Email To *'],
                                                                                            email_cc , email_bcc,
                                                                                            row[' Email Subject *']))

                                    body, inlineattachments, appendattachments = append_body_and_attachments(body, inlineattachments, appendattachments, row, imagepaths, subscriberemail, vizurl, viewname, has_email_footer, has_email_attachment)
                                    
                                    # send the email
                                    try:
                                        send_email(email_from, row[' Email To *'], row[' Email Subject *'],
                                                u''.join(body), email_cc, email_bcc, inlineattachments, appendattachments, imagefilenames)
                                    except Exception as e:
                                        logger.error(u'Failed to send the email. Exception: {}'.format(e))
                                        view_failure(view, u'VizAlerts was unable to process this view due to the following error: {}'.format(e))

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

                        body, inlineattachments, appendattachments = append_body_and_attachments(body, inlineattachments, appendattachments, row, imagepaths, subscriberemail, vizurl, viewname, has_email_footer, has_email_attachment)
                                    
                        try:
                            send_email(email_from, row[' Email To *'], row[' Email Subject *'], u''.join(body), email_cc,
                                    email_bcc, inlineattachments, appendattachments, imagefilenames)
                        except Exception as e:
                            logger.error(u'Failed to send the email. Exception: {}'.format(e))
                            view_failure(view, u'VizAlerts was unable to process this view due to the following error: {}'.format(e))

                        inlineattachments = []
                        body = []
                        appendattachments=[]
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
        #msg = MIMEBase('application', "octet-stream")
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
                   body, ccaddrs, None, attachments)
    except Exception as e:
        logger.error(u'Unknown error sending exception alert email: {}'.format(e.message))


def validate_addresses(vizdata, has_email_from, has_email_cc, has_email_bcc):
    """Loops through the viz data for an Advanced Alert and returns a list of dicts
        containing any errors found in recipients"""

    errorlist = []
    rownum = 2 # account for field header in CSV

    for row in vizdata:
        result = addresses_are_invalid(row[' Email To *'], False) # empty string not acceptable as a To address
        if result:
            errorlist.append({'Row': rownum, 'Field': ' Email To *', 'Value': result['address'], 'Error': result['errormessage']})
        if has_email_from:
            result = addresses_are_invalid(row[' Email From ~'], False) # empty string not acceptable as a From address
            if result:
                errorlist.append({'Row': rownum, 'Field': ' Email From ~', 'Value': result['address'], 'Error': result['errormessage']})
        if has_email_cc:
            result = addresses_are_invalid(row[' Email CC ~'], True)
            if result:
                errorlist.append({'Row': rownum, 'Field': ' Email CC ~', 'Value': result['address'], 'Error': result['errormessage']})
        if has_email_bcc:
            result = addresses_are_invalid(row[' Email BCC ~'], True)
            if result:
                errorlist.append({'Row': rownum, 'Field': ' Email BCC ~', 'Value': result['address'], 'Error': result['errormessage']})
        rownum = rownum + 1

    return errorlist


def addresses_are_invalid(emailaddresses, emptystringok):
    """Validates all email addresses found in a given string"""
    logger.debug(u'Validating email field value: {}'.format(emailaddresses))
    address_list = re.split(EMAIL_RECIP_SPLIT_REGEX, emailaddresses.strip())
    for address in address_list:
        logger.debug(u'Validating presumed email address: {}'.format(address))
        if emptystringok and (address == '' or address is None):
            return None
        else:
            errormessage = address_is_invalid(address)
            if errormessage:
                logger.debug(u'Address is invalid: {}, Error: {}'.format(address, errormessage))
                if len(address) > 64:
                    address = address[:64] + '...' # truncate a too-long address for error formattting purposes
                return {'address':address, 'errormessage':errormessage}
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
    except ValueError:
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



def find_viz_refs(data, viewurlsuffix, has_email_header, has_email_footer, has_email_attachment):
    """ Given the data this searches through the body, header, footer, and attachment for all references to vizzes to be downloaded, downloads only the distinct vizzes (to avoid duplicating downloads). 
    
    Returns vizcompleterefs dictionary that contains a key of each distinct viz reference. The value is another dictionary with the following keys:
        vizref = the original viz reference string
        view_url_suffix = the workbook/viewname to be downloaded, plus any URL parameters the user has added
        formatstring = the format of the destinatino file, based on the VIZ_* reference
        imagepath = the full path to the temp tile for the downloaded viz 
        filename = the filename to use for appended attachments as well as exported files
        exportfilepath = the path to use for an exported file (~~~not yet supported)
        
    """

    vizcompleterefs = dict()        
    vizrefs = []
    imagepaths = dict()
    vizdistinctrefs = dict()

    # data is the CSV that has been downloaded for a given view
    for item in data:
        # this might be able to be more efficient code
        results = re.findall(u"VIZ[_]IMAGE\(.*?\)|VIZ[_]IMAGE\(\)", item[' Email Body *'])

        if has_email_header:
            results.extend(re.findall(u"VIZ[_]IMAGE\(.*?\)|VIZ[_]IMAGE\(\)", item[' Email Header ~']))
            
        if has_email_footer:
            results.extend(re.findall(u"VIZ[_]IMAGE\(.*?\)|VIZ[_]IMAGE\(\)", item[' Email Footer ~']))
        
        if has_email_attachment:
            results.extend(re.findall(u"VIZ[_]IMAGE\(.*?\)|VIZ[_]IMAGE\(\)|VIZ[_]CSV\(.*?\)|VIZ[_]PDF\(.*?\)|VIZ[_]TWB\(.*?\)", item[' Email Attachment ~']))

    # loop through each found viz reference, i.e. everything in the VIZ_*(*).
    for result in results
        if result not in vizcompleterefs:
            # create a dictionary to hold the necessary values for this viz reference
            vizcompleterefs[result] = dict()
            
            # store the vizref itself as a value in the edict
            vizcompleterefs[result]['vizref'] = result #
            
            # if the result is one of the placeholders then we will be pulling down the calling viz
            if result in [IMAGE_PLACEHOLDER, PDF_PLACEHOLDER, CSV_PLACEHOLDER, TWB_PLACEHOLDER]:
                vizcompleterefs[result]['view_url_suffix'] = viewurlsuffix
            else:
                # vizstring contains everything inside the VIZ_*() parentheses
                vizstring = re.match(u'VIZ_.*?\((.*?)\)', vizref)
                logger.debug('~vizstring',vizstring.group(1))
                
                # vizstring may contain reference to the viz plus advanced alert parameters like
                # a filename or exportpathname.
                
                # if there is no delimiter then at this point we know the vizstring
                # is just a viz to use
                if ARGUMENT_DELIMITER not in vizstring.group(1):
                    vizcompleterefs[result]['view_url_suffix'] = vizstring

                # there are one or more arguments
                else:
                    # split vizstring into a list of arguments
                    vizstringlist = vizstring.group(1).split(ARGUMENT_DELIMITER)

                    # first argument could be empty, such as VIZ_IMAGE(|filename=someFileName)
                    # in that case we'll use the calling viz
                    if vizstringlist[0] == '':
                        vizcompleterefs[result]['view_url_suffix'] = viewurlsuffix
                    else:
                        # return only the view
                        vizcompleterefs[result]['view_url_suffix'] = vizstringlist[0]
                    
                    # if there is more than one element in the vizstring list then we
                    # know there are arguments to parse out
                    # this code could probably be simpler
                    if len(vizstringlist) > 1:
                        for element in vizstringlist[1:]:
                        
                            # looking for filenames
                            if element.startswith(EXPORTFILENAME_ARGUMENT):
                                filename = re.match(EXPORTFILENAME_ARGUMENT + u'=(.*)', element).group(1)
                                # code from https://github.com/mitsuhiko/flask/blob/50dc2403526c5c5c67577767b05eb81e8fab0877/flask/helpers.py#L633
                                # for validing filenames
                                filename = posixpath.normpath(filename)
                                for sep in _os_alt_seps:
                                    if sep in filename:
                                        errormessage = u'Alert was triggered, but found an invalid separator in filename: {}'.format(e.message)
                                        logger.error(errormessage)
                                        view_failure(view, errormessage)

                                if os.path.isabs(filename) or filename.startswith('../') or filename.startswith('..\\'):
                                    errormessage = u'Alert was triggered, but found an invalid filename: {}'.format(e.message)
                                    logger.error(errormessage)
                                    view_failure(view, errormessage)
                                
                                vizcompleterefs[result]['filename'] = filename

                            # just getting the export filepath for now, will use it in a later update
                            if element.startswith(EXPORTFILEPATH_ARGUMENT):
                                exportfilepath = re.match(EXPORTFILEPATH_ARGUMENT + u'=(.*)', element).group(1)
                                exportfilepath = posixpath.normpath(exportfilepath)
                                
                                if ospath.isabs(filename) or '../' in exportfilepath or '..\\' in exportfilepath:
                                    errormessage = u'Alert was triggered, but found an invalid export file path: {}'.format(e.message)
                                    logger.error(errormessage)
                                    view_failure(view, errormessage)
                                vizcompleterefs[result]['exportfilepath'] = exportfilepath
            
            # identifying the format for the output file
            vizrefformat = re.match(u'VIZ_(.*?)\(', vizref)
            if vizrefformat.group(1) == 'IMAGE':
                vizcompleterefs[result]['formatstring'] = 'PNG'
            else:
                vizcompleterefs[result]['formatstring'] = vizrefformat.group(1)
            
            #creating distinct list of images to download
            if vizcompleterefs[result]['view_url_suffix'] not in vizdistinctrefs:
                vizdistinctrefs[vizcompleterefs[result]['view_url_suffix']] = dict()
                vizdistinctrefs[vizcompleterefs[result]['view_url_suffix']]['imagepath'] = ''
                vizdistinctrefs[vizcompleterefs[result]['view_url_suffix']]['formatstring'] = vizcompleterefs[result]['formatstring']
        #end if result not in vizcompleterefs
    #end for result in results

    #loop over vizdistinctrefs to export files
    for vizref in vizdistinctrefs:       
        try:
            view['view_url_suffix'] = vizref
            # export the viz to a file, store path as value with vizref as key
            vizdistinctrefs[vizref]['imagepath'] = tabhttp.export_view(configs, view, eval('tabhttp.Format.' + vizrefs[vizref]['formatstring']), logger)

        except Exception as e:
            errormessage = u'Alert was triggered, but encountered a failure rendering data/image: {}'.format(e.message)
            logger.error(errormessage)
            view_failure(view, errormessage)
            raise e

    #now match vizdistinctrefs to original references to store imagepaths
    for result in vizcompleterefs:
        vizcompleterefs[result]['imagepath'] = vizdistinctrefs[vizcompleterefs[result]['view_url_suffix']]['imagepath']

    return vizcompleterefs

def get_unique_vizdata(data, has_consolidate_email, has_email_from, has_email_cc, has_email_bcc, has_email_header, has_email_footer, has_email_attachment):
    """Returns a unique list of all relevant email fields in data. Also sorts data in proper order."""

    preplist = [] # list of dicts containing only keys of concern for de-duplication from data
    uniquelist = [] # unique-ified list of dicts

    logger.debug(u'Beginning get unique vizdata')

    # copy in only relevant fields
    for item in data:
        newitem = {' Email Action *': item[' Email Action *'], ' Email To *': item[' Email To *'], ' Email Subject *': item[' Email Subject *'], ' Email Body *': item[' Email Body *'], ' Email Attachment ~': item[' Email Attachment ~']}
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
        preplist.append(newitem)

    logger.debug(u'Removing duplicates')

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
        logger.debug(u'Sorting by BCC')
        if has_email_bcc:
            uniquelist = sorted(uniquelist, key=itemgetter(u' Email BCC ~'))
        logger.debug(u'Sorting by CC')
        if has_email_cc:
            uniquelist = sorted(uniquelist, key=itemgetter(u' Email CC ~'))
        logger.debug(u'Sorting by From')
        if has_email_from:
            uniquelist = sorted(uniquelist, key=itemgetter(u' Email From ~'))
        logger.debug(u'Sorting by Subject, To')
        # finally, sort by Subject and To
        uniquelist = sorted(uniquelist, key=itemgetter(u' Email Subject *', u' Email To *'))

    logger.debug(u'Done sorting, returning the list')

    # return the list
    return uniquelist


def replace_in_list(inlist, findstr, replacestr):
    """Replaces all occurences of a string in a list of strings"""
    outlist = []
    foundstring = False
    for item in inlist:
        logger.debug(u'Attempting to find {} ({}) in {} ({})'.format(findstr, type(findstr), item, type(item))) # REMOVE THIS LATER
        if item.find(findstr) <> -1:
            foundstring = True
        outlist.append(item.replace(findstr, replacestr))

    # return a dictionary with a boolean indicating whether we did replace anything, and the new list
    return {'foundstring':foundstring, 'outlist':outlist}


def get_view_url(view):
    """Construct the full URL of the view"""

    # this logic should be removed--empty string should be passed in from SQL
    sitename = unicode(view["site_name"]).replace('Default', '')

    # (omitting hash preserves 8.x functionality)
    if sitename == '':
        vizurl = u'http://' + configs["server"] + u'/views/' + view['view_url_suffix']
    else:
        vizurl = u'http://' + configs["server"] + u'/t/' + sitename + u'/views/' + view['view_url_suffix']

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

def append_body_and_attachments(body, inlineattachments, appendattachments, row, vizcompleterefs, subscriberemail, vizurl, viewname, has_email_footer, has_email_attachment):
    """generic function for filling email body text with the body & footers from the csv plus inserting viz references"""
    """for inline attachments"""

    body.append(row[' Email Body *'])

    # add the footer if needed
    if has_email_footer:
        body.append(row[' Email Footer ~'].replace(DEFAULT_FOOTER,
                            bodyfooter.format(subscriberemail, vizurl, viewname)))
    else:
        # no footer specified, add the default footer
        body.append(bodyfooter.format(subscriberemail, vizurl, viewname))

    for vizresult in vizcompleterefs.iteritems():
        
        replaceresult = replace_in_list(body, vizresult,
                                        u'<img src="cid:{}">'.format(basename(vizcompleterefs[vizresult]['imagepath']))
                                )
        if replaceresult['foundstring'] == True:
            body = replaceresult['outlist']
            if vizcompleterefs[vizresult] not in inlineattachments:
                inlineattachments.append(vizcompleterefs[vizresult])
 
        # testing each workbookview as to whether it may belong in an appended attachment
        if has_email_attachment:
            if row[' Email Attachment ~'].find(vizresult) >= 0 and vizresult not in appendattachments:
                appendattachments.append(vizresult)

    return body, inlineattachments, appendattachments
    
def send_email(fromaddr, toaddrs, subject, content, ccaddrs=None, bccaddrs=None, inlineattachments=None, appendattachments=None, imagefilenames=None):
    """Generic function to send an email"""

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
        if inlineattachments is not None:
            for vizresult in inlineattachments:
                msgalternative.attach(mimify_file(vizresult['imagepath'], inline = True)

        
        # Add appended attachments from Email Attachments field and prevent dup custom filenames
        # appendedfilenames = []
        if appendattachments is not None:
            for vizresult in appendattachments:
                if vizresult['filename'] is None:
                    msg.attach(mimify_file(vizresult['imagepath'], inline = False))
                else:
                    if vizresult['filename'] not in appendedfilenames:
                        appendedfilenames.append[vizresult['filename']]
                        msg.attach(mimify_file(vizresult['imagepath'], inline = False, overridename = vizresult['filename']))
                    else:
                        msg.attach(mimify_file(vizresult['imagepath'], inline = False))

                       
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
