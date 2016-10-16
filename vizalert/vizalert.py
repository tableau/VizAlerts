# -*- coding: utf-8 -*-
# Provides the core classes and functions for VizAlerts

import os
import re
import csv
import copy
import threading
import datetime
from PyPDF2 import PdfFileReader, PdfFileMerger
from collections import OrderedDict
from os.path import abspath, basename, expanduser
from operator import itemgetter
import posixpath

# import local modules
import config
import log
import tabhttp
import emailaction
import smsaction

# reserved strings for Advanced Alerts embedding
IMAGE_PLACEHOLDER = u'VIZ_IMAGE()'
PDF_PLACEHOLDER = u'VIZ_PDF()'
CSV_PLACEHOLDER = u'VIZ_CSV()'
TWB_PLACEHOLDER = u'VIZ_TWB()'
DEFAULT_FOOTER = u'VIZALERTS_FOOTER()'  # special string for embedding the default footer in an Advanced Alert
VIZLINK_PLACEHOLDER = u'VIZ_LINK()'  # special string for embedding HTML links in Advanced Alert

# reserved strings for Advanced Alerts arguments
EXPORTFILENAME_ARGUMENT = u'filename'
EXPORTFILEPATH_ARGUMENT = u'exportfilepath'
MERGEPDF_ARGUMENT = u'mergepdf'
VIZLINK_ARGUMENT = u'vizlink'
RAWLINK_ARGUMENT = u'rawlink'
ARGUMENT_DELIMITER = u'|'

# reserved strings for Action Field names (used as keys)
# General use fields
GENERAL_SORTORDER_FIELDKEY = u'Sort Order'

# Email Action fields
EMAIL_ACTION_FIELDKEY = u'Email Action'
EMAIL_TO_FIELDKEY = u'Email To'
EMAIL_FROM_FIELDKEY = u'Email From'
EMAIL_CC_FIELDKEY = u'Email CC'
EMAIL_BCC_FIELDKEY = u'Email BCC'
EMAIL_SUBJECT_FIELDKEY = u'Email Subject'
EMAIL_BODY_FIELDKEY = u'Email Body'
EMAIL_ATTACHMENT_FIELDKEY = u'Email Attachment'
EMAIL_HEADER_FIELDKEY = u'Email Header'
EMAIL_FOOTER_FIELDKEY = u'Email Footer'
EMAIL_CONSOLIDATE_FIELDKEY = u'Email Consolidate'

# SMS Action fields
SMS_ACTION_FIELDKEY = u'SMS Action'
SMS_TO_FIELDKEY = u'SMS To'
SMS_FROM_FIELDKEY = u'SMS From'
SMS_MESSAGE_FIELDKEY = u'SMS Message'

# File Copy Action fields
FILE_COPY_ACTION_FIELDKEY = u'File Copy Action'
FILE_COPY_TO_FIELDKEY = u'File Copy To'
FILE_COPY_FROM_FIELDKEY = u'File Copy From'

# File Delete action fields
FILE_DELETE_ACTION_FIELDKEY = u'File Delete Action'
FILE_DELETE_TARGET_FIELDKEY = u'File Delete Target'


# reserved strings for Action Types
GENERAL_ACTION_TYPE = u'General'
EMAIL_ACTION_TYPE = u'Email'
SMS_ACTION_TYPE = u'SMS'
FILE_COPY_ACTION_TYPE = u'File Copy'
FILE_DELETE_ACTION_TYPE = u'File Delete'

# reserved strings for alert_types
SIMPLE_ALERT = u'simple'
ADVANCED_ALERT = u'advanced'

# appended to the bottom of all user-facing emails, unless overidden
# expecting bodyfooter.format(subscriber_email, subcriber_sysname, vizurl, viewname)
bodyfooter = u'<br><br><font size="2"><i>This VizAlerts email generated on behalf of ' \
             u'<a href="mailto:{}">{}</a>, from view <a href="{}">{}</a></i></font>'

# appended under the bodyfooter, but only for Simple Alerts
# expecting unsubscribe_footer.format(subscriptionsurl)
unsubscribe_footer = u'<br><font size="2"><i><a href="{}">Manage my subscription settings</a></i></font>'

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



class ActionField:
    """Represents a mapping of a field found in a trigger CSV to an action property"""

    def __init__(self, name, action_type, is_required, is_action_flag, pattern):
        self.name = name
        self.action_type = action_type
        self.is_required = is_required  # "if performing this action_type, is this field required to do it?"
        self.is_action_flag = is_action_flag
        self.pattern = pattern
        self.field_name = None  # no field name until we validate
        self.match_list = []
        self.error_list = []

    def get_user_facing_fieldname(self):
        field_name = u'{} {}'
        if self.is_required:
            return field_name.format(self.name, u'*')
        else:
            return field_name.format(self.name, u'~')

    def has_match(self):
        if len(self.match_list) > 0:
            return True
        else:
            return False

    def has_errors(self):
        if len(self.error_list) > 0:
            return True
        else:
            return False

# stub for the Content Reference class to come someday
"""
class ContentReference:
    Represents a special text string embedded in the trigger data of a vizalert
         which, after processing, results in a single file

    def __init__(self, name, reference_type, pattern):
        # VIZ_PDF(workbook/view?filter|arg1=2|arg2)
        self.name = name
        self.pattern = pattern
        self.reference_type = reference_type  # Where the content comes from: VIZ, FILE, etc
        self.view_url_suffix = ''
        self.filepath = ''
        self.argument_list = []   # list of key-value pairs
        self.error_list = []

    def has_errors(self):
        if len(self.error_list) > 0:
            return True
        else:
            return False
"""

class VizAlert:
    """Standard class representing a VizAlert"""

    def __init__(self, view_url_suffix, site_name, subscriber_sysname, subscriber_domain):
        self.view_url_suffix = view_url_suffix
        self.site_name = site_name
        self.subscriber_domain = subscriber_domain
        self.subscriber_sysname = subscriber_sysname

        # general config
        self.data_retrieval_tries = 2
        self.force_refresh = True
        self.notify_subscriber_on_failure = True
        self.viz_data_maxrows = 1000
        self.viz_png_height = 1500
        self.viz_png_width = 1500
        self.timeout_s = 60

        # email action config
        self.action_enabled_email = 0
        self.allowed_from_addresses = u''
        self.allowed_recipient_addresses = u''

        # sms action config
        self.action_enabled_sms = 0
        self.allowed_recipient_numbers = u''
        self.allowed_from_number = u''
        self.phone_country_code = ''

        # file action config
        self.action_enabled_file = 0
        self.allowed_filepath = u''

        # alert metadata
        self.alert_type = SIMPLE_ALERT
        self.is_test = False
        self.customized_view_id = -1
        self.owner_email = u''
        self.owner_friendly_name = u''
        self.owner_sysname = u''
        self.project_id = -1
        self.project_name = u''
        self.ran_last_at = u''
        self.run_next_at = u''
        self.schedule_frequency = u''
        self.schedule_id = -1
        self.schedule_name = u''
        self.priority = -1
        self.schedule_type = -1
        self.site_id = -1
        self.subscriber_email = u''
        self.subscriber_license = u''
        self.subscriber_user_id = -1
        self.subscription_id = -1
        self.view_id = -1
        self.view_name = u''
        self.view_owner_id = -1
        self.workbook_id = u''
        self.workbook_repository_url = u''

        # alert state information
        self.trigger_data_file = u''
        self.trigger_data = []
        self.trigger_data_rowcount = 0
        self.action_field_dict = {}
        self.error_list = []  # list of errors encountered processing the vizalert

        # add all possible alert fields to the new VizAlert instance (should this live somewhere else?)

        # General
        self.action_field_dict[GENERAL_SORTORDER_FIELDKEY] = \
            ActionField(GENERAL_SORTORDER_FIELDKEY, GENERAL_ACTION_TYPE, False, False, u'.*Sort.Order')

        # Email Action fields
        self.action_field_dict[EMAIL_ACTION_FIELDKEY] = \
            ActionField(EMAIL_ACTION_FIELDKEY, EMAIL_ACTION_TYPE, True, True, u' ?Email.Action')
        self.action_field_dict[EMAIL_SUBJECT_FIELDKEY] = \
            ActionField(EMAIL_SUBJECT_FIELDKEY, EMAIL_ACTION_TYPE, True, False, u' ?Email.Subject')
        self.action_field_dict[EMAIL_TO_FIELDKEY] = \
            ActionField(EMAIL_TO_FIELDKEY, EMAIL_ACTION_TYPE, True, False, u' ?Email.To')
        self.action_field_dict[EMAIL_FROM_FIELDKEY] = \
            ActionField(EMAIL_FROM_FIELDKEY, EMAIL_ACTION_TYPE, False, False, u' ?Email.From')
        self.action_field_dict[EMAIL_CC_FIELDKEY] = \
            ActionField(EMAIL_CC_FIELDKEY, EMAIL_ACTION_TYPE, False, False, u' ?Email.CC')
        self.action_field_dict[EMAIL_BCC_FIELDKEY] = \
            ActionField(EMAIL_BCC_FIELDKEY, EMAIL_ACTION_TYPE, False, False, u' ?Email.BCC')
        self.action_field_dict[EMAIL_BODY_FIELDKEY] = \
            ActionField(EMAIL_BODY_FIELDKEY, EMAIL_ACTION_TYPE, True, False, u' ?Email.Body')
        self.action_field_dict[EMAIL_HEADER_FIELDKEY] = \
            ActionField(EMAIL_HEADER_FIELDKEY, EMAIL_ACTION_TYPE, False, False, u' ?Email.Header')
        self.action_field_dict[EMAIL_FOOTER_FIELDKEY] = \
            ActionField(EMAIL_FOOTER_FIELDKEY, EMAIL_ACTION_TYPE, False, False, u' ?Email.Footer')
        self.action_field_dict[EMAIL_ATTACHMENT_FIELDKEY] = \
            ActionField(EMAIL_ATTACHMENT_FIELDKEY, EMAIL_ACTION_TYPE, False, False, u' ?Email.Attachment')
        self.action_field_dict[EMAIL_CONSOLIDATE_FIELDKEY] = \
            ActionField(EMAIL_CONSOLIDATE_FIELDKEY, EMAIL_ACTION_TYPE, False, False, u' ?Email.Consolidate')

        # SMS Action fields
        self.action_field_dict[SMS_ACTION_FIELDKEY] = \
            ActionField(SMS_ACTION_FIELDKEY, SMS_ACTION_TYPE, True, True, u' ?SMS.Action.\*')
        self.action_field_dict[SMS_TO_FIELDKEY] = \
            ActionField(SMS_TO_FIELDKEY, SMS_ACTION_TYPE, True, False, u' ?SMS.To.\*')
        self.action_field_dict[SMS_FROM_FIELDKEY] = \
            ActionField(SMS_FROM_FIELDKEY, SMS_ACTION_TYPE, False, False, u' ?SMS.From.~')  # do we have a from?
        self.action_field_dict[SMS_MESSAGE_FIELDKEY] = \
            ActionField(SMS_MESSAGE_FIELDKEY, SMS_ACTION_TYPE, True, False, u' ?SMS.Message.\*')

        # File Copy Action fields
        self.action_field_dict[FILE_COPY_ACTION_FIELDKEY] = \
            ActionField(FILE_COPY_ACTION_FIELDKEY, FILE_COPY_ACTION_TYPE, True, True, u' ?File.Copy.Action.\*')
        self.action_field_dict[FILE_COPY_TO_FIELDKEY] = \
            ActionField(FILE_COPY_TO_FIELDKEY, FILE_COPY_ACTION_TYPE, True, False, u' ?File.Copy.To.\*')
        self.action_field_dict[FILE_COPY_FROM_FIELDKEY] = \
            ActionField(FILE_COPY_FROM_FIELDKEY, FILE_COPY_ACTION_TYPE, True, False, u' ?File.Copy.From.\*')

        # File Delete action fields
        self.action_field_dict[FILE_DELETE_ACTION_FIELDKEY] = \
            ActionField(FILE_DELETE_ACTION_FIELDKEY, FILE_DELETE_ACTION_TYPE, True, True, u' ?File.Delete.Action.\*')
        self.action_field_dict[FILE_DELETE_TARGET_FIELDKEY] = \
            ActionField(FILE_DELETE_TARGET_FIELDKEY, FILE_DELETE_ACTION_TYPE, True, False, u' ?File.Delete.Target.\*')

    def get_action_flag_field(self, action_type):
        """Return the appropriate action field representing an aciton flag based on the type
        Note that no validation is done here """
        for action_field_name, action_field in self.action_field_dict.iteritems():
            if self.action_field_dict[action_field_name].action_type == action_type \
                    and self.action_field_dict[action_field_name].is_action_flag:
                return action_field_name

    def get_view_url(self, customviewurlsuffix=None):
        """Construct the full URL of the trigger view for this VizAlert
             customviewurlsuffix is for generating URLs for other vizzes for content references"""

        # this logic should be removed--empty string should be passed in from SQL
        sitename = unicode(self.site_name).replace('Default', '')

        if not customviewurlsuffix:
            customviewurlsuffix = self.view_url_suffix

        # (omitting hash preserves 8.x functionality)
        if sitename == '':
            vizurl = u'http://' + config.configs['server'] + u'/views/' + customviewurlsuffix
        else:
            vizurl = u'http://' + config.configs['server'] + u'/t/' + sitename + u'/views/' + customviewurlsuffix

        return vizurl

    def get_footer(self):
        """Get the footer text for an email alert"""
        httpprefix = u'http://'
        if config.configs['server.ssl']:
            httpprefix = u'https://'

        footer = u'<br><br><font size="2"><i>This VizAlerts email generated on behalf of <a href="mailto:{}">{}</a>, ' \
                 u'from view <a href="{}">' \
                 u'{}</a></i></font>'.format(self.subscriber_email, self.subscriber_sysname, self.get_view_url(),
                                             self.view_name)
        if self.alert_type == SIMPLE_ALERT:
            managesuburlv8 = httpprefix + config.configs['server'] + u'/users/' + self.subscriber_sysname
            managesuburlv9 = httpprefix + config.configs['server'] + u'/#/user/'
            if self.subscriber_domain:
                managesuburlv9 = managesuburlv9 + self.subscriber_domain + u'/' + self.subscriber_sysname +\
                                 u'/subscriptions'
            else:
                managesuburlv9 = managesuburlv9 + u'local/' + self.subscriber_sysname + u'/subscriptions'

            managesublink = u'<br><font size="2"><i><a href="{}">Manage my subscription settings</a></i></font>'

            if config.configs['server.version'] == 8:
                footer += managesublink.format(managesuburlv8)
            if config.configs['server.version'] in [9, 10]:
                footer += managesublink.format(managesuburlv9)

        return footer

    def download_trigger_data(self):
        """ Exports the CSV data for a VizAlert and reads it into a list of dicts
        Returns a filepath to the CSV """

        # export the CSV to a local file
        try:
            self.trigger_data_file = tabhttp.export_view(self, tabhttp.Format.CSV)

            # read all rows into the trigger_data class member for later use
            reader = self.read_trigger_data()

            rowcount = 0
            for row in reader:
                if rowcount > self.viz_data_maxrows:
                    errormessage = u'Maximum rows of {} exceeded.'.format(self.viz_data_maxrows)
                    self.error_list.append(errormessage)
                    log.logger.error(errormessage)

                # read data in anyway
                self.trigger_data.append(row)
                rowcount += 1

            # set the rowcount value in the alert itself
            self.trigger_data_rowcount = rowcount
        except Exception as e:
            log.logger.error(e)
            self.error_list.append(e.message)
            return

    def read_trigger_data(self):
        """ Returns a CSV reader to read the trigger data file downloaded for the alert
            Requests for the data itself should use the trigger_data list member to avoid multiple reads """
        try:
            f = open(self.trigger_data_file, 'rU')
            return UnicodeDictReader(f)

        except Exception as e:
            log.logger.error(u'Error accessing {} while getting processing alert {}: {}'.format(
                self.trigger_data_file,
                self.view_url_suffix,
                e))
            raise e

    def parse_action_fields(self):
        """Parse the trigger data and map field names to VizAlert action fields
            Returns a list of dicts containing any errors found"""

        log.logger.debug(u'Parsing action fields')

        field_error_list = []
        rownum = 1  # fields are always in the first row of a csv

        try:
            # go through all possible fields and find matches
            action_field_updates = []
            for key in self.action_field_dict:
                for field in self.read_trigger_data().fieldnames:
                    if re.match(self.action_field_dict[key].pattern, field, re.IGNORECASE):
                        log.logger.debug(u'found field match! : {}'.format(field))
                        self.action_field_dict[key].match_list.append(field)  # add the match we found

            log.logger.debug(u'searching for action fields')

            # did we find at least one action flag?
            if any(i.is_action_flag and i.has_match()
                   for key, i in self.action_field_dict.iteritems()):

                self.alert_type = ADVANCED_ALERT  # we know this is an advanced alert now
                log.logger.debug(u'Advanced alert detected')

                # ensure the subscriber is the owner of the viz
                #  we need to do this check straight away so we don't send any more info to the subscriber
                if self.subscriber_sysname != self.owner_sysname:
                    errormessage = u'You must be the owner of the workbook in order to use Advanced Alerts<br><br>.' \
                                   u'Subscriber {} to advanced alert subscription_id {} is not the owner, {}'.format(
                                    self.subscriber_sysname,
                                    self.subscription_id,
                                    self.owner_sysname)
                    log.logger.error(errormessage)
                    self.error_list.append(errormessage)
                    return None  # provide no more info, and do no more work

                # check for issues in each of the fields
                for action_field in self.action_field_dict:

                    action_flag = self.get_action_flag_field(
                        self.action_field_dict[action_field].action_type)

                    if self.action_field_dict[action_field].has_match():

                        # we're not allowed to perform these actions

                        # email actions
                        if self.action_field_dict[action_field].action_type == EMAIL_ACTION_TYPE \
                                and not self.action_enabled_email:
                            self.action_field_dict[action_field].error_list.append(
                                u'Email actions are not allowed for this alert, per administrative settings')

                        # sms actions
                        if self.action_field_dict[action_field].action_type == SMS_ACTION_TYPE:
                            if not config.configs['smsaction.enable']:
                                self.action_field_dict[action_field].error_list.append(
                                    u'SMS actions are not enabled, per administrative settings')
                                self.action_field_dict[action_field].error_list.append(
                                    u'SMS actions are not allowed for this alert, per administrative settings')
                            elif not smsaction.smsclient:
                                self.action_field_dict[action_field].error_list.append(
                                    u'SMS actions cannot be processed right now--no valid client. '
                                    u'Please contact your administrator.')

                        # file copy actions
                        if self.action_field_dict[action_field].action_type == FILE_COPY_ACTION_TYPE \
                                and not self.action_enabled_file:
                            self.action_field_dict[action_field].error_list.append(
                                u'File actions are not allowed for this alert, per administrative settings')

                        # multiple matches are not allowed--we need to be sure which field to use for what
                        if len(self.action_field_dict[action_field].match_list) > 1:
                            self.action_field_dict[action_field].error_list.append(
                                u'Multiple matches found for field {}. Found:  {}'.format(
                                    action_field,
                                    u''.join(self.action_field_dict[action_field].match_list)
                            ))

                        # missing the action flag field (OK for 'General' fields)
                        if not action_flag and self.action_field_dict[action_field].action_type != GENERAL_ACTION_TYPE:
                            # we should never hit this, but OCD requires I check for it
                            self.action_field_dict[action_field].error_list.append(
                                u'VizAlerts has a bug; please contact the developers')

                        if action_flag:
                            if not self.action_field_dict[action_flag].has_match():
                                self.action_field_dict[action_field].error_list.append(
                                    u'Could not find action flag field {}, which is necessary for {} actions.'.format(
                                        self.action_field_dict[action_flag].get_user_facing_fieldname(),
                                        self.action_field_dict[action_field].action_type))

                            # may not use "Email Consolidate" field for anything but email actions
                            #   Might revisit in the future, but for now it's too confusing to support in anything else
                            if self.action_field_dict[action_field].name == EMAIL_CONSOLIDATE_FIELDKEY and \
                                    any(i.is_action_flag and i.has_match() and i.action_type != EMAIL_ACTION_TYPE
                                        for key, i in self.action_field_dict.iteritems()):
                                self.action_field_dict[action_field].error_list.append(
                                    u'{} may not be used with any action except {}'.format(
                                        self.action_field_dict[action_field].name,
                                        self.action_field_dict[action_flag].action_type))

                    else:  # the field has no matches
                        # missing fields that are required
                        if action_flag:
                            # remember, 'general' fields have don't have an action_flag
                            if self.action_field_dict[action_flag].has_match() \
                                    and self.action_field_dict[action_field].is_required:
                                # the action flag field was matched, which means
                                #   the author intends to use that action type in this alert
                                self.action_field_dict[action_field].error_list.append(
                                    u'This is a required field for {} actions'.format(
                                        self.action_field_dict[action_field].action_type))

            log.logger.debug(u'Retrieving all errors found in field parse operation')
            # capture and return errors we found
            for action_field in self.action_field_dict:
                for field_error in self.action_field_dict[action_field].error_list:

                    log.logger.debug(u'Found error in field {}: {}'.format(
                        action_field, field_error))

                    # add the error to the list
                    field_error_list.append(
                            {u'Row': rownum,
                             u'Field': self.action_field_dict[action_field].get_user_facing_fieldname(),
                             u'Value': u''.join(self.action_field_dict[action_field].match_list),
                             u'Error': field_error})

            # assign final field names for all action fields that have no issues
            for action_field in self.action_field_dict:
                if self.action_field_dict[action_field].has_match() \
                        and not self.action_field_dict[action_field].has_errors():
                    self.action_field_dict[action_field].field_name = self.action_field_dict[action_field].match_list[0]

            # add the errors we found to the list for the VizAlert as a whole
            self.error_list.extend(field_error_list)
            return field_error_list
        except Exception as e:
            errormessage = u'Error parsing trigger data fields: {}'.format(e.message)
            log.logger.debug(errormessage)
            self.error_list.append(errormessage)
            raise e

    def validate_trigger_data(self):
        """Parse the trigger data and check for error conditions
            Returns a list of dicts containing any errors found"""

        trigger_data_errors = []

        # validate the simple alert scenario
        if self.alert_type == SIMPLE_ALERT:
            log.logger.debug(u'Validating as a simple alert')

            # check for invalid email domains--just in case the user fudges their email in Tableau Server
            subscriberemailerror = emailaction.address_is_invalid(self.subscriber_email, self.allowed_recipient_addresses)
            if subscriberemailerror:
                errormessage = u'VizAlerts was unable to process this alert, because it was ' \
                               u'unable to send email to address {}: {}'.format(
                                    self.subscriber_email, subscriberemailerror)
                log.logger.error(errormessage)
                trigger_data_errors.append(subscriberemailerror)

        elif self.alert_type == ADVANCED_ALERT:
            # this is an advanced alert, so we need to process all the fields appropriately
            log.logger.debug(u'Validating as an advanced alert')

            # Email action validations
            if self.action_field_dict[EMAIL_ACTION_FIELDKEY].has_match() \
                    and not self.action_field_dict[EMAIL_ACTION_FIELDKEY].has_errors():
            
                # validate all From and Recipient addresses
                log.logger.debug(u'Validating email addresses')
                addresserrors = emailaction.validate_addresses(
                                                            self.trigger_data,
                                                            self.allowed_from_addresses, 
                                                            self.allowed_recipient_addresses,
                                                            self.action_field_dict[EMAIL_TO_FIELDKEY].field_name,
                                                            self.action_field_dict[EMAIL_FROM_FIELDKEY].field_name,
                                                            self.action_field_dict[EMAIL_CC_FIELDKEY].field_name,
                                                            self.action_field_dict[EMAIL_BCC_FIELDKEY].field_name)
                if addresserrors:
                    errormessage = u'Invalid email addresses found: {}'.format(addresserrors)
                    log.logger.error(errormessage)
                    trigger_data_errors.extend(addresserrors)

            # SMS action validations
            if self.action_field_dict[SMS_ACTION_FIELDKEY].has_match():
            
                # validate all From and Recipient numbers
                log.logger.debug(u'Validating SMS numbers')
                numbererrors = smsaction.validate_smsnumbers(
                                                            self.trigger_data,
                                                            self.action_field_dict[SMS_TO_FIELDKEY].field_name,
                                                            self.action_field_dict[SMS_FROM_FIELDKEY].field_name,
                                                            self.allowed_recipient_numbers,
                                                            self.allowed_from_number,
                                                            self.phone_country_code)
                if numbererrors:
                    errormessage = u'Invalid SMS numbers found: {}'.format(numbererrors)
                    log.logger.error(errormessage)
                    trigger_data_errors.extend(errormessage)


            ##################################################################
            # ADD CODE HERE TO DO UP-FRONT CONTENT REFERENCE VALIDATION
            #    can't get to it just yet--this will need the content reference class
            ##################################################################


        else:
            # it's not a simple alert, it's not advanced, then what is it? a bug, that's what.
            trigger_data_errors.append(u'VizAlerts has a bug; please contact the developers')

        # add the errors we found to all errors in the VizAlert
        self.error_list.extend(trigger_data_errors)

        # return the errors we found validating the trigger data
        return trigger_data_errors

    def execute_alert(self):
        """Simple function to effectively run the entire VizAlert process:
            Get the CSV data from the alert trigger
            Parse and validate the fields
            Identify and download all content references
            Perform all actions as instructed by the alert  """

        # do a bit of pre-validation first
        # check for unlicensed user
        if self.subscriber_license == 'Unlicensed':

            if self.subscriber_sysname == self.owner_sysname:
                # if they are the owner, this may be an advanced alert, so we should notify the admin
                errormessage = u'VizAlerts was unable to process this alert: User {} is unlicensed.'.format(
                    self.subscriber_sysname)
                log.logger.error(errormessage)
                self.error_list.append(errormessage)
                self.alert_failure()
                return
            else:
                # they're not the owner, so this is a simple alert. just ignore them and log that we did.
                errormessage = u'Ignoring subscription_id {}: User {} is unlicensed.'.format(
                    self.subscription_id)
                log.logger.error(errormessage)
                self.error_list.append(errormessage)
                return

        # if this is a test alert, and they're not the owner, tell them what's up
        if self.is_test and self.subscriber_sysname != self.owner_sysname:
            errormessage = u'You must be the owner of the viz in order to test the alert.'
            log.logger.error(errormessage)
            self.error_list.append(errormessage)
            self.alert_failure()
            return

        # get the CSV data from the alert trigger
        log.logger.debug(u'Starting to download trigger data')

        self.download_trigger_data()

        if self.trigger_data_rowcount == 0:
            log.logger.debug(u'Nothing to do! No rows in trigger data from file {}'.format(self.trigger_data_file))
        else:
            log.logger.debug(u'Got trigger data, now parsing fields')

            # parse and validate the fields
            if self.trigger_data and len(self.error_list) == 0:
                field_errors = self.parse_action_fields()

                # were there any problems? if so, bail
                if len(field_errors) > 0 or len(self.error_list) > 0:
                    self.alert_failure()
                    return

                log.logger.debug(u'Validating trigger data')

                trigger_data_errors = []
                trigger_data_errors = self.validate_trigger_data()

                if len(trigger_data_errors) > 0 or len(self.error_list) > 0:
                    self.alert_failure()
                    return

                log.logger.debug(u'Performing alert actions')

                # identify and download all content references
                # perform all actions as instructed by the alert
                #  These two are in the same call right now, but should probably be separated
                self.perform_actions()
            else:
                self.alert_failure()
                return

    def perform_actions(self):
        """Execute all the instructions as directed by the trigger data"""

        log.logger.debug(u'Performing alert actions now')

        # check for any errors we've detected so far
        if len(self.error_list) > 0:
            log.logger.debug(u'Errors found in alert, aborting execution')
            self.alert_failure()
        else:
            # please proceed, governor

            # Validate content references
            #   (this needs to wait for a content reference class before implementing)

            #   there could be multiple viz's (including PDF, CSV, TWB) for a single row in the CSV
            # return a list of all found content reference VIZ_*() strings
            # VIZ_*([optional custom view w/optional custom URL parameters]|[optional VizAlerts parameters])
            # stored as a dict of dicts, the key is the content reference

            vizcompleterefs = dict()

            # run the simple alert
            if self.alert_type == SIMPLE_ALERT:
                try:
                    log.logger.debug(u'Processing as a simple alert')

                    # export the viz to a PNG file
                    imagepath = tabhttp.export_view(self, tabhttp.Format.PNG)

                    # attachments are stored lists of dicts to handle Advanced Alerts
                    inlineattachments = [{'imagepath': imagepath}]
                    appendattachments = [{'imagepath': self.trigger_data_file}]

                    # embed the viz image
                    # inlineattachments = [csvpath, imagepath]
                    log.logger.info(u'Sending simple alert email to user {}'.format(self.subscriber_email))
                    body = u'<a href="{}"><img src="cid:{}"></a>'.format(self.get_view_url(), basename(imagepath)) + \
                           bodyfooter.format(self.subscriber_email, self.subscriber_sysname,
                                             self.get_view_url(), self.view_name)
                    subject = unicode(u'Alert triggered for {}'.format(self.view_name))
                    emailaction.send_email(config.configs['smtp.address.from'], self.subscriber_email, subject, body,
                                           None, None, inlineattachments, appendattachments)
                    return
                except Exception as e:
                    errormessage = u'Alert was triggered, but encountered a failure rendering data/image:<br> {}'.format(
                        e.message)
                    log.logger.error(errormessage)
                    self.error_list.append(errormessage)
                    raise UserWarning(errormessage)

            # run the advanced alert
            elif self.alert_type == ADVANCED_ALERT:
                log.logger.debug(u'Processing as an advanced alert')

                try:
                    vizcompleterefs = self.find_viz_refs(self.trigger_data)
                except Exception as e:
                    errormessage = u'Alert was triggered, but encountered a failure getting data/image references' \
                                   u':<br /> {}'.format(e.message)
                    log.logger.error(errormessage)
                    raise UserWarning(errormessage)

                # eliminate duplicate rows and ensure proper sorting
                data = self.get_unique_vizdata()
                rowcount_unique = len(data)

                # process emails
                if self.action_field_dict[EMAIL_ACTION_FIELDKEY].field_name:
                    log.logger.debug(u'Processing emails')

                    # get the field names we'll need
                    email_action_fieldname = self.action_field_dict[EMAIL_ACTION_FIELDKEY].field_name
                    email_to_fieldname = self.action_field_dict[EMAIL_TO_FIELDKEY].field_name
                    email_from_fieldname = self.action_field_dict[EMAIL_FROM_FIELDKEY].field_name
                    email_cc_fieldname = self.action_field_dict[EMAIL_CC_FIELDKEY].field_name
                    email_bcc_fieldname = self.action_field_dict[EMAIL_BCC_FIELDKEY].field_name
                    email_subject_fieldname = self.action_field_dict[EMAIL_SUBJECT_FIELDKEY].field_name
                    email_body_fieldname = self.action_field_dict[EMAIL_BODY_FIELDKEY].field_name
                    email_header_fieldname = self.action_field_dict[EMAIL_HEADER_FIELDKEY].field_name
                    email_consolidate_fieldname = self.action_field_dict[EMAIL_CONSOLIDATE_FIELDKEY].field_name

                    # iterate through the rows and send emails accordingly
                    consolidate_email_ctr = 0
                    body = []
                    inlineattachments = []
                    appendattachments = []

                    # Process each row of data
                    for i, row in enumerate(data):
                        log.logger.debug(u'Starting iteration {}, consolidate_email_ctr is {}'.format(i, consolidate_email_ctr))

                        # author wants to send an email
                        #  use string value for maximum safety. all other values are ignored, currently
                        if row[email_action_fieldname] == '1':
                            # make sure we set the "from" address if the viz did not provide it
                            if email_from_fieldname:
                                email_from = row[email_from_fieldname]
                            else:
                                email_from = config.configs['smtp.address.from']  # use default from config file

                            # get the other recipient addresses
                            if email_cc_fieldname:
                                email_cc = row[email_cc_fieldname]
                            else:
                                email_cc = None

                            if email_bcc_fieldname:
                                email_bcc = row[email_bcc_fieldname]
                            else:
                                email_bcc = None

                            # Append header row, if provided
                            if email_header_fieldname and consolidate_email_ctr == 0:
                                log.logger.debug(u'Appending body header')
                                body.append(row[email_header_fieldname])

                            # If rows are being consolidated, consolidate all with same recipients & subject
                            if email_consolidate_fieldname:
                                # could put a test in here for mixing consolidated and non-consolidated emails in
                                #   the same trigger view, would also need to check the sort in get_unique_vizdata

                                log.logger.debug(
                                    u'Consolidate value is true, row index is {}, rowcount is {}'.format(i, rowcount_unique))

                                # test for end of iteration--if done, take what we have so far and send it
                                if i + 1 == rowcount_unique:
                                    log.logger.debug(u'Last email in set reached, sending consolidated email')
                                    log.logger.info(u'Sending email to {}, CC {}, BCC {}, subject {}'.format(
                                        row[email_to_fieldname], email_cc, email_bcc, row[email_subject_fieldname]))

                                    try:  # remove this later??
                                        body, inlineattachments = self.append_body_and_inlineattachments(
                                            body, inlineattachments, row, vizcompleterefs)
                                        appendattachments = self.append_attachments(appendattachments, row, vizcompleterefs)

                                        # send the email
                                        emailaction.send_email(email_from, row[email_to_fieldname],
                                                               row[email_subject_fieldname],
                                                   u''.join(body), email_cc, email_bcc, inlineattachments, appendattachments)
                                    except Exception as e:
                                        errormessage = u'Failed to send the email. Exception:<br> {}'.format(e)
                                        log.logger.error(errormessage)
                                        self.error_list.append(errormessage)
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

                                    this_row_recipients.append(row[email_subject_fieldname])
                                    this_row_recipients.append(row[email_to_fieldname])
                                    this_row_recipients.append(email_from)

                                    # check if we're sending an email at all in the next row
                                    next_row_email_action = data[i + 1][email_action_fieldname]
                                    next_row_recipients.append(data[i + 1][email_subject_fieldname])
                                    next_row_recipients.append(data[i + 1][email_to_fieldname])

                                    if email_from_fieldname:
                                        next_row_recipients.append(data[i + 1][email_from_fieldname])
                                    else:
                                        next_row_recipients.append(email_from)

                                    if email_cc_fieldname:
                                        this_row_recipients.append(email_cc)
                                        next_row_recipients.append(data[i + 1][email_cc_fieldname])

                                    if email_bcc_fieldname:
                                        this_row_recipients.append(email_bcc)
                                        next_row_recipients.append(data[i + 1][email_bcc_fieldname])

                                    # Now compare the data from the rows
                                    if this_row_recipients == next_row_recipients and next_row_email_action:
                                        log.logger.debug(u'Next row matches recips and subject, appending body & attachments')
                                        body.append(row[email_body_fieldname])
                                        if self.action_field_dict[EMAIL_ATTACHMENT_FIELDKEY].field_name and \
                                                len(row[self.action_field_dict[EMAIL_ATTACHMENT_FIELDKEY].field_name]) > 0:
                                            appendattachments = self.append_attachments(appendattachments, row, vizcompleterefs)
                                        consolidate_email_ctr += 1
                                    else:
                                        log.logger.debug(u'Next row does not match recips and subject, sending consolidated email')
                                        log.logger.info(u'Sending email to {}, CC {}, BCC {}, Subject {}'.format(
                                            row[email_to_fieldname],
                                            email_cc,
                                            email_bcc,
                                            row[email_subject_fieldname]))

                                        body, inlineattachments = self.append_body_and_inlineattachments(body, inlineattachments,
                                                                                                    row, vizcompleterefs)
                                        appendattachments = self.append_attachments(appendattachments, row, vizcompleterefs)

                                        # send the email
                                        try:
                                            emailaction.send_email(email_from, row[email_to_fieldname],
                                                                   row[email_subject_fieldname],
                                                       u''.join(body), email_cc, email_bcc, inlineattachments,
                                                       appendattachments)
                                        except Exception as e:
                                            errormessage = u'Failed to send the email. Exception:<br> {}'.format(e)
                                            log.logger.error(errormessage)
                                            self.error_list.append(errormessage)
                                            raise UserWarning(errormessage)

                                        body = []
                                        consolidate_email_ctr = 0
                                        inlineattachments = []
                                        appendattachments = []
                            else:
                                # emails are not being consolidated, so send the email
                                log.logger.info(u'Sending email to {}, CC {}, BCC {}, Subject {}'.format(
                                    row[email_to_fieldname],
                                    email_cc,
                                    email_bcc,
                                    row[email_subject_fieldname]))

                                consolidate_email_ctr = 0  # I think this is redundant now...
                                body = []

                                # add the header if needed
                                if email_header_fieldname:
                                    body.append(row[email_header_fieldname])

                                body, inlineattachments = self.append_body_and_inlineattachments(body, inlineattachments, row,
                                                                                            vizcompleterefs)
                                appendattachments = self.append_attachments(appendattachments, row, vizcompleterefs)

                                try:
                                    emailaction.send_email(email_from, row[email_to_fieldname],
                                                           row[email_subject_fieldname],
                                                           u''.join(body),
                                                           email_cc,
                                                           email_bcc,
                                                           inlineattachments,
                                                           appendattachments)
                                except Exception as e:
                                    errormessage = u'Failed to send the email. Exception:<br> {}'.format(e)
                                    log.logger.error(errormessage)
                                    self.error_list.append(errormessage)
                                    raise UserWarning(errormessage)

                                inlineattachments = []
                                body = []
                                appendattachments = []
                        # we're not performing any actions this round.
                        #   Make sure we reset our variables again
                        else:
                            # reset variables for next email
                            body = []
                            inlineattachments = []
                            consolidate_email_ctr = 0
                            appendattachments = []

                # process sms messages
                if self.action_field_dict[SMS_ACTION_FIELDKEY].field_name:

                    # get the field names we'll need
                    sms_action_fieldname = self.action_field_dict[SMS_ACTION_FIELDKEY].field_name
                    sms_to_fieldname = self.action_field_dict[SMS_TO_FIELDKEY].field_name
                    sms_from_fieldname = self.action_field_dict[SMS_FROM_FIELDKEY].field_name
                    sms_message_fieldname = self.action_field_dict[SMS_MESSAGE_FIELDKEY].field_name

                    sms_message = []  # list to support future header, footer, and consolidate features

                    # Process each row of data
                    for i, row in enumerate(data):

                        # author wants to send an SMS
                        #  use string value for maximum safety. all other values are ignored, currently
                        if row[sms_action_fieldname] == '1':
                            sms_to = row[sms_to_fieldname]
                            sms_message.append(row[sms_message_fieldname])

                            # not sure if author used this field
                            if sms_from_fieldname:
                                sms_from = row[sms_from_fieldname]
                            else:
                                sms_from = config.configs['smsaction.from_number']

                            sms_message = smsaction.sms_append_body(sms_message, vizcompleterefs, self)

                            log.logger.debug(u'Converting phone number list {} to E.164'.format(sms_to))

                            # make list of all SMS addresses - they already went through 1st validation
                            smsaddresses = smsaction.get_e164numbers(sms_to, self.phone_country_code)

                            log.logger.info(u'Sending SMS to {}, from {}, message: {}'.format(
                                smsaddresses,
                                sms_from,
                                sms_message))

                            # send the message
                            for smsaddress in smsaddresses:
                                errormessage = smsaction.send_sms(sms_from, smsaddress, ''.join(sms_message))
                                if errormessage:
                                    self.error_list.append(u'Could not send SMS, error: {}'.format(errormessage))

                                    # since we've had one failure, bail on the entire VizAlert
                                    self.alert_failure()
                                    return
            else:
                errormessage = u'Could not determine alert type, due to a bug in VizAlerts. ' \
                               u'Please contact the developers'
                log.logger.error(errormessage)
                self.error_list.append(errormessage)
                raise UserWarning(errormessage)

    def find_viz_refs(self, data):
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

        # MCOLES: These local variables are being set to avoid refactoring everything in this function
        #   Yes, this is redundant and awful but we'll address it later
        viewurlsuffix = self.view_url_suffix
        email_body_fieldname = self.action_field_dict[EMAIL_BODY_FIELDKEY].field_name
        email_header_fieldname = self.action_field_dict[EMAIL_HEADER_FIELDKEY].field_name
        email_footer_fieldname = self.action_field_dict[EMAIL_FOOTER_FIELDKEY].field_name
        email_attachment_fieldname = self.action_field_dict[EMAIL_ATTACHMENT_FIELDKEY].field_name
        sms_message_fieldname = self.action_field_dict[SMS_MESSAGE_FIELDKEY].field_name

        vizcompleterefs = dict()
        results = []
        vizdistinctrefs = dict()

        results = []
        log.logger.debug(u'Identifying content references')

        # data is the CSV that has been downloaded for a given view
        # loop through it to make a result set of all viz references
        for item in data:
            # this might be able to be more efficient code
            if email_body_fieldname:
                if 'VIZ_IMAGE' in item[email_body_fieldname] or 'VIZ_LINK' in item[email_body_fieldname]:
                    results.extend(re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_LINK\(.*?\)", item[email_body_fieldname]))

            if email_header_fieldname:
                results.extend(re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_LINK\(.*?\)", item[email_header_fieldname]))

            if email_footer_fieldname:
                results.extend(re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_LINK\(.*?\)", item[email_footer_fieldname]))

            if email_attachment_fieldname:
                results.extend(re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_CSV\(.*?\)|VIZ_PDF\(.*?\)|VIZ_TWB\(.*?\)",
                                          item[email_attachment_fieldname]))

            if sms_message_fieldname:
                results.extend(re.findall(u"VIZ_LINK\(.*?\)", item[sms_message_fieldname]))

        # loop through each found viz reference, i.e. everything in the VIZ_*(*).
        for vizref in results:

            log.logger.debug(u'found content ref {}'.format(vizref))

            if vizref not in vizcompleterefs:
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

                                # looking for filenames
                                if element.startswith(EXPORTFILENAME_ARGUMENT):
                                    filename = re.match(EXPORTFILENAME_ARGUMENT + u'=(.*)', element).group(1)
                                    # code from https://github.com/mitsuhiko/flask/blob/50dc2403526c5c5c67577767b05eb81e8fab0877/flask/helpers.py#L633
                                    # for validating filenames
                                    filename = posixpath.normpath(filename)
                                    for sep in _os_alt_seps:
                                        if sep in filename:
                                            errormessage = u'Found an invalid or non-allowed separator in filename: ' \
                                                          u'{} for content reference {}'.format(filename, vizref)
                                            self.error_list.append(errormessage)
                                            raise ValueError(errormessage)

                                    if os.path.isabs(filename) or '../' in filename or '..\\' in filename:
                                        errormessage = u'Found non-allowed path when expecting filename: ' \
                                            u'{} for content reference {}'.format(filename, vizref)
                                        self.error_list.append(errormessage)
                                        raise ValueError(errormessage)

                                    # check for non-allowed characters
                                    # check for non-allowed characters
                                    # code based on https://mail.python.org/pipermail/tutor/2010-December/080883.html
                                    # using ($L) option to set locale to handle accented characters
                                    nonallowedchars = re.findall(u'(?L)[^\w \-._+]', filename)
                                    if len(nonallowedchars) > 0:
                                        errormessage = u'Found non-allowed character(s): {} in filename {} for content reference '
                                        u'{}, only allowed characters are alphanumeric, space, hyphen, underscore, '
                                        u'period, and plus sign'.format(u''.join(nonallowedchars), filename, vizref)
                                        self.error_list.append(errormessage)
                                        raise ValueError(errormessage)

                                    # if the output is anything but LINK then append the formatstring
                                    #  to the output filename
                                    if vizcompleterefs[vizref]['formatstring'] != 'LINK':
                                        vizcompleterefs[vizref]['filename'] = filename + '.' + vizcompleterefs[vizref][
                                            'formatstring'].lower()
                                    else:
                                        vizcompleterefs[vizref]['filename'] = filename

                                # just getting the export filepath for now, will use it in a later update
                                if element.startswith(EXPORTFILEPATH_ARGUMENT):
                                    exportfilepath = re.match(EXPORTFILEPATH_ARGUMENT + u'=(.*)', element).group(1)
                                    exportfilepath = posixpath.normpath(exportfilepath)

                                    if os.path.isabs(filename) or '../' in exportfilepath or '..\\' in exportfilepath:
                                        errormessage = u'Found an invalid or non-allowed export file path: ' \
                                                       u'{} for content reference {}'.format(exportfilepath, vizref)
                                        self.error_list.append(errormessage)
                                        raise ValueError(errormessage)
                                    vizcompleterefs[vizref]['exportfilepath'] = exportfilepath

                                # looking for mergepdf
                                if element.startswith(MERGEPDF_ARGUMENT) and vizcompleterefs[vizref][
                                    'formatstring'].lower() == 'pdf':
                                    vizcompleterefs[vizref][MERGEPDF_ARGUMENT] = 'y'

                                if element.startswith(VIZLINK_ARGUMENT):
                                    vizcompleterefs[vizref][VIZLINK_ARGUMENT] = 'y'

                                if element.startswith(RAWLINK_ARGUMENT):
                                    vizcompleterefs[vizref][RAWLINK_ARGUMENT] = 'y'

                        except Exception as e:
                            errormessage = u'Alert was triggered, but unable to process arguments to a ' \
                                           u'content reference with error:<br><br> {}'.format(e.message)
                            self.error_list.append(errormessage)
                            log.logger.error(errormessage)
                            raise UserWarning(errormessage)

                            # end of processing vizstringlist
                            # end of checking for argument delimiters
            # end of parsing this vizref

            # creating distinct list of images to download
            # this is a dict so we have both the workbook/viewname aka view_url_suffix as well as the formatstring
            if vizref not in vizdistinctrefs and vizcompleterefs[vizref]['formatstring'] != 'LINK':
                vizdistinctrefs[vizref] = vizcompleterefs[vizref]

                # end if vizref not in vizcompleterefs

        # end for vizref in results

        # loop over vizdistinctrefs to download images, PDFs, etc. from Tableau
        for vizref in vizdistinctrefs:
            try:
                # we need a full VizAlert instance to export the info, but with a different view_url_suffix
                # to avoid overwriting the view_url_suffix in ourself, create a deep copy and pass that instead
                #  this should probably be implemented differently, but for now it'll have to do
                alert_copy = copy.deepcopy(self)
                alert_copy.view_url_suffix = vizdistinctrefs[vizref]['view_url_suffix']
                # export/render the viz to a file, store path to the download as value with vizref as key
                vizdistinctrefs[vizref]['imagepath'] = tabhttp.export_view(alert_copy, eval(
                    'tabhttp.Format.' + vizdistinctrefs[vizref]['formatstring']))

            except Exception as e:
                errormessage = u'Unable to render content reference {} with error:<br> {}'.format(vizref, e.message)
                log.logger.error(errormessage)
                self.error_list.append(errormessage)
                raise UserWarning(errormessage)

        # now match vizdistinctrefs to original references to store the correct imagepaths
        for vizref in vizcompleterefs:
            if vizcompleterefs[vizref]['formatstring'] != 'LINK':
                vizcompleterefs[vizref]['imagepath'] = vizdistinctrefs[vizref]['imagepath']

        if len(vizcompleterefs) > 0:
            log.logger.debug(u'Returning all content references')

        return vizcompleterefs

    def get_unique_vizdata(self):
        """Returns a unique list of all relevant email fields in data. Also sorts data in proper order."""

        preplist = []  # list of dicts containing only keys of concern for de-duplication from data
        uniquelist = []  # unique-ified list of dicts

        log.logger.debug(u'Start of get_unique_vizdata')

        # copy in only relevant fields from each record. Non-VizAlerts fields will be ignored
        for item in self.trigger_data:
            newitem = dict()

            for action_field in self.action_field_dict:
                #  Should not assume fields passed validation
                if self.action_field_dict[action_field].has_match() \
                        and not self.action_field_dict[action_field].has_errors():
                    newitem[self.action_field_dict[action_field].field_name] = \
                        item[self.action_field_dict[action_field].field_name]
            # add the new trimmed row to our list
            preplist.append(newitem)

        log.logger.debug(u'Removing duplicates')

        # remove duplicates, preserving original ordering
        # proposed solution from http://stackoverflow.com/questions/9427163/remove-duplicate-dict-in-list-in-python

        seen = set()
        for dictitem in preplist:
            t = tuple(sorted(dictitem.items()))
            if t not in seen:
                seen.add(t)
                uniquelist.append(dictitem)

        log.logger.debug(u'Sorting unique rows')

        # the data must now be sorted for use in Advanced Alerts with email consolidation

        # sort order is used first because the downloaded trigger csv can be re-ordered during
        #  the download process from the original csv
        if self.action_field_dict[GENERAL_SORTORDER_FIELDKEY].field_name:
            uniquelist = sorted(uniquelist, key=itemgetter(self.action_field_dict[GENERAL_SORTORDER_FIELDKEY].field_name))

        # special case for Email Actions, where the Email Consolidate flag is used
        #  it's assumed here (and validated elsewhere) that if Email Consolidate is used, no other Actions are permitted
        #  MC: Shouldn't Sort Order prevail over these? Otherwise we potentially override the user's intent on how
        #   emails are consolidated...
        if self.action_field_dict[EMAIL_ACTION_FIELDKEY].field_name \
                and self.action_field_dict[EMAIL_CONSOLIDATE_FIELDKEY].field_name:
            log.logger.debug(u'Sorting by BCC')
            if self.action_field_dict[EMAIL_BCC_FIELDKEY].field_name:
                uniquelist = sorted(uniquelist, key=itemgetter(self.action_field_dict[EMAIL_BCC_FIELDKEY].field_name))
            log.logger.debug(u'Sorting by CC')
            if self.action_field_dict[EMAIL_CC_FIELDKEY].field_name:
                uniquelist = sorted(uniquelist, key=itemgetter(self.action_field_dict[EMAIL_CC_FIELDKEY].field_name))
            log.logger.debug(u'Sorting by From')
            if self.action_field_dict[EMAIL_FROM_FIELDKEY].field_name:
                uniquelist = sorted(uniquelist, key=itemgetter(self.action_field_dict[EMAIL_FROM_FIELDKEY].field_name))
            log.logger.debug(u'Sorting by Subject, To')
            # finally, sort by Subject and To
            uniquelist = sorted(uniquelist, key=itemgetter(self.action_field_dict[EMAIL_SUBJECT_FIELDKEY].field_name,
                                                           self.action_field_dict[EMAIL_TO_FIELDKEY].field_name))

        log.logger.debug(u'Done sorting, returning the list')

        # return the list
        return uniquelist

    def append_attachments(self, appendattachments, row, vizcompleterefs):
        """generic function for adding appended (non-inline) attachments"""

        # there can be multiple content references in a single email attachment field
        # and order is important if these attachments are to be merged later
        # so we generate the list with a regex
        if self.action_field_dict[EMAIL_ATTACHMENT_FIELDKEY].field_name:
            attachmentrefs = []
            attachmentrefs = re.findall(u"VIZ_IMAGE\(.*?\)|VIZ_CSV\(.*?\)|VIZ_PDF\(.*?\)|VIZ_TWB\(.*?\)",
                                        row[self.action_field_dict[EMAIL_ATTACHMENT_FIELDKEY].field_name])
            if len(attachmentrefs) > 0:
                log.logger.debug(u'Adding appended attachments to list')
            for attachmentref in attachmentrefs:
                # only make appended attachments when they are needed
                if attachmentref not in appendattachments:
                    appendattachments.append(vizcompleterefs[attachmentref])

        return appendattachments

    def append_body_and_inlineattachments(self, body, inlineattachments, row, vizcompleterefs):
        """Generic function for filling email body text with the body & footers from the csv
            plus inserting viz references"""
        """for inline attachments and hyperlink text"""

        log.logger.debug(u'Replacing body text with exact content references for inline attachments and hyperlinks')
        body.append(row[self.action_field_dict[EMAIL_BODY_FIELDKEY].field_name])

        # add the footer if needed
        if self.action_field_dict[EMAIL_FOOTER_FIELDKEY].field_name:
            body.append(row[self.action_field_dict[EMAIL_FOOTER_FIELDKEY].field_name].replace(DEFAULT_FOOTER,
                                                       bodyfooter.format(self.subscriber_email,
                                                                         self.subscriber_sysname,
                                                                         self.get_view_url(),
                                                                         self.view_name)))
        else:
            # no footer specified, add the default footer
            body.append(bodyfooter.format(self.subscriber_email, self.subscriber_sysname,
                                          self.get_view_url(), self.view_name))

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
                        replacestring = u'<a href="' + self.get_view_url(vizcompleterefs[vizref]['view_url_suffix'])\
                                        + u'"><img src="cid:{}">'.format(
                            basename(vizcompleterefs[vizref]['imagepath'])) + u'</a>'
                    else:
                        replacestring = u'<img src="cid:{}">'.format(basename(vizcompleterefs[vizref]['imagepath']))

                    replaceresult = replace_in_list(body, vizref, replacestring)

                    if replaceresult['foundstring']:
                        body = replaceresult['outlist']

                        # create a list of inline attachments
                        if vizcompleterefs[vizref] not in inlineattachments:
                            inlineattachments.append(vizcompleterefs[vizref])
                    else:
                        raise UserWarning(
                            u'Unable to locate downloaded image for {}, check whether the content '
                            u'reference is properly URL encoded.'.format(
                                vizref))

                # we're replacing #VIZ_LINK text
                elif vizcompleterefs[vizref]['formatstring'] == 'LINK':
                    # use raw link if that option is present
                    if RAWLINK_ARGUMENT in vizcompleterefs[vizref] and vizcompleterefs[vizref][RAWLINK_ARGUMENT] == 'y':
                        replacestring = self.get_view_url(vizcompleterefs[vizref]['view_url_suffix'])
                    else:
                        # test for whether the filename field is used, if so that is the link text
                        if 'filename' in vizcompleterefs[vizref] and len(vizcompleterefs[vizref]['filename']) > 0:
                            replacestring = u'<a href="' + self.get_view_url(vizcompleterefs[vizref]['view_url_suffix']) + u'">' + \
                                            vizcompleterefs[vizref]['filename'] + u'</a>'
                        # use the view_url_suffix as the link text
                        else:
                            replacestring = u'<a href="' + self.get_view_url(vizcompleterefs[vizref]['view_url_suffix']) + u'">' + \
                                            vizcompleterefs[vizref]['view_url_suffix'] + u'</a>'

            replaceresult = replace_in_list(body, vizref, replacestring)

            if replaceresult['foundstring']:
                body = replaceresult['outlist']\

        return body, inlineattachments

    def alert_failure(self):
        """Alert the Admin, and optionally the Subscriber, to a failure to process their alert"""

        subject = u'VizAlerts was unable to process alert {}'.format(self.view_name)

        data_errors = []  # errors found in the trigger data fields, or in the trigger data itself
        other_errors = []  # miscellaneous other errors we may have caught
        error_text = u'The following errors were encountered trying to ' \
                     u'process your alert:<br /><br />'  # final error text to email
        attachment = None

        # dump all errors to the log for troubleshooting
        log.logger.debug('All errors found:')
        for error in self.error_list:
            log.logger.debug('{}'.format(error))

        # Separate the errors stored in a dictionary from the generic errors
        #   structure a nice HTML table to help our beloved users sort out their problems
        #   if the error doesn't fit into the table, add it to the other_errors list
        for error in self.error_list:
            if type(error) is dict:
                if 'Row' in error:
                    data_errors.append(
                        u'<tr><td width="75">{}</td><td width="75">{}</td><td>{}</td><td>{}</td></tr>'.format(
                            error['Row'],
                            error['Field'],
                            error['Value'],
                            error['Error']))
            else:
                other_errors.append(error)

        # Format the error text for the email
        if len(data_errors) > 0:
            data_errors.insert(0, u'Errors found in alert data. See row numbers in attached CSV file:<br /><br />'
                                  u'<table border=1><tr><b><td>Row</td>'
                                  u'<td width="75">Field</td><td>Value</td><td>Error</td></b></tr>')
            data_errors.append(u'</table>')

            # append trigger data if we found problems with it
            attachment = [{'imagepath': self.trigger_data_file}]

            # add this to our final error text
            error_text += u''.join(data_errors)

        if len(other_errors) > 0:
            error_text += u'<br /><br />General errors:<br /><br />' + \
                    u'<br /><br />'.join(other_errors)

        # tack on some failure deets (in the ugliest way possible, apparently)
        body = error_text + u'<br><br>' + \
               u'<b>Alert Information:</b><br><br>' + \
               u'<b>View URL:</b> <a href="{}">{}<a>'.format(
                   self.get_view_url(),
                   self.get_view_url()) + u'<br><b>Subscriber:</b> <a href="mailto:{}">{}</a>'.format(
                    self.subscriber_email, self.subscriber_sysname) + u'<br><b>View Owner:</b> <a href="mailto:{}">{}</a>'.format(
                        self.owner_email, self.owner_sysname) + u'<br><b>Site Id:</b> {}'.format(
                            self.site_name) + u'<br><b>Project:</b> {}'.format(
                            self.project_name)

        if self.notify_subscriber_on_failure:
            toaddrs = self.subscriber_email  # email the Subscriber, cc the Admin
            ccaddrs = config.configs['smtp.address.to']
        else:
            toaddrs = config.configs['smtp.address.to']  # just email the Admin
            ccaddrs = None

        if attachment:
            log.logger.debug(u'Failure email should include attachment: {}'.format(attachment))

        try:
            emailaction.send_email(config.configs['smtp.address.from'], toaddrs, subject,
                                   body, ccaddrs, None, None, attachment)
        except Exception as e:
            log.logger.error(u'Unknown error sending exception alert email: {}'.format(e.message))


def merge_pdf_attachments(appendattachments):
        """ Checks the list of appended attachments for any merged pdfs. Any pdf attachments that need to be merged are merged, then the revised attachments is returned"""

        tempdir = config.configs['temp.dir']

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
                    log.logger.debug(u'Request to merge multiple PDFs into ' + listtomerge + ', only one PDF found')
                    for attachment in mergedfilenames[listtomerge]:
                        revisedappendattachments.append(mergedfilenames[listtomerge][attachment])

                # now to merge some PDFs:
                else:
                    log.logger.debug(u'Merging PDFs for ' + listtomerge)

                    try:
                        # we know all attachments in a given list have the same filename due to the loop above
                        # so we can just pull the first one

                        merger = PdfFileMerger()

                        i = 0
                        for attachment in mergedfilenames[listtomerge]:
                            if i == 0:
                                mergedfilename = mergedfilenames[listtomerge][attachment]['filename']

                            merger.append(PdfFileReader(mergedfilenames[listtomerge][attachment]['imagepath'], "rb"))
                            i = i + 1

                        # make the temp filename for the merged pdf
                        datestring = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
                        mergedfilepath = tempdir + datestring + '_' + threading.current_thread().name + '_' + mergedfilename

                        merger.write(mergedfilepath)

                        mergedattachment = {'filename': mergedfilename, 'imagepath': mergedfilepath, 'formatstring': 'PDF',
                                            'vizref': 'mergepdf file ' + 'filename'}
                        revisedappendattachments.append(mergedattachment)
                    except Exception as e:
                        log.logger.error(u'Could not generate merged PDF for filename {}: {}'.format(mergedfilename, e))
                        raise e

        return (revisedappendattachments)


def replace_in_list(inlist, findstr, replacestr):
    """Replaces all occurrences of a string in a list of strings"""

    outlist = []
    foundstring = False

    for item in inlist:
        if item.find(findstr) != -1:
            foundstring = True
        outlist.append(item.replace(findstr, replacestr))

    # return a dictionary with a boolean indicating whether we did replace anything, and the new list
    return {'foundstring': foundstring, 'outlist': outlist}

