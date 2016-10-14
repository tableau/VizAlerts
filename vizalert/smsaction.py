#! python
# -*- coding: utf-8 -*-
# This is a utility module for integrating SMS providers into VizAlerts.

import re
import phonenumbers
import twilio

# import local modules
import config
import log
import vizalert

# store the SMS client we get back from Twilio for use across all modules
smsclient = None

# regular expression used to split recipient number strings into separate phone numbers
SMS_RECIP_SPLIT_REGEX = u'[;,]*'


def get_sms_client():
    """Generic function get an SMS client object. This only works with Twilio at this time."""

    # check to see if there's a provider set
    if config.configs['smsaction.provider'] == None or len(config.configs['smsaction.provider']) == 0:
        errormessage = u'SMS Actions are enabled but smsaction.provider value is not set, exiting'
        log.logger.error(errormessage)
        raise ValueError(errormessage)        

    # load code for Twilio
    elif config.configs['smsaction.provider'].lower() == 'twilio': 
        # these need to be in the global name space to send SMS messages
        global twilio
        import twilio
        
        global twiliorest
        import twilio.rest as twiliorest
        
        global smsclient
        smsclient = twiliorest.TwilioRestClient(
            config.configs['smsaction.account_id'],
            config.configs['smsaction.auth_token'])
        
        return smsclient

    # unknown SMS provider error
    else:
        errormessage = u'SMS Actions are enabled but found unknown smsaction.provider {}, exiting'.format(
            config.configs['smsaction.provider'])
        log.logger.error(errormessage)
        raise ValueError(errormessage)      


def send_sms(sms_from, sms_to, msgbody=None):
    """function to send an sms using Twilio's REST API, see https://www.twilio.com/docs/python/install for details.
    Presumes that numbers have gone through a first level of checks for validity
    Returns nothing on success, error string back on failure"""

    log.logger.info(u'Sending SMS: {},{},{}'.format(sms_from, sms_to, msgbody))

    # shouldn't happen but setting content to '' if it's None
    if not msgbody:
        msgbody = ''

    # now to send the message
    try:
        message = smsclient.messages.create(body=msgbody, to=sms_to, from_=sms_from)

        # this may never happen since the Twilio REST API throws exceptions, it's a failsafe check
        if message.status == 'failed':
            raise ValueError(u'Failed to deliver SMS message to {} with body {},'
                             u' no additional information is available'.format(sms_to, msgbody))

    # check for Twilio REST API exceptions
    except twilio.TwilioRestException as e:
        errormessage = u'Could not send SMS message to {} with body {}.\nHTTP status {} returned for request: ' \
                       u'{} {}\nWith error {}: {} '.format(sms_to, msgbody, e.status, e.method, e.uri, e.code, e.msg)
        log.logger.error(errormessage)
        return errormessage

    # check for ValueError from try 
    except ValueError as e:
        log.logger.error(e)
        return e

    except Exception as e:
        errormessage = u'Could not send SMS message to {} with body {}, error {}'.format(sms_to, msgbody, e)
        log.logger.error(errormessage)
        return e
    
    return None


def sms_append_body(body, vizcompleterefs, alert):
    """Generic function for filling SMS body text with hyperlink references
        for inline attachments and hyperlink text"""

    log.logger.debug(u'Replacing SMS text with exact content references for hyperlinks')

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
                replacestring = alert.get_view_url(vizcompleterefs[vizref]['view_url_suffix'])
                replaceresult = vizalert.replace_in_list(body, vizref, replacestring)

                if replaceresult['foundstring'] == True:
                    body = replaceresult['outlist']

    return body


def validate_smsnumbers(vizdata, sms_to_fieldname, sms_from_fieldname, allowed_recipient_numbers, allowed_from_number,
                        iso2countrycode):
    """Loops through the viz data for an Advanced Alert and returns a list of dicts
        containing any errors found in recipients"""

    errorlist = []
    rownum = 2  # account for field header in CSV

    try:
        for row in vizdata:
            result = smsnumbers_are_invalid(row[sms_to_fieldname],
                                            False,  # empty string not acceptable as a From number
                                            iso2countrycode,
                                            allowed_recipient_numbers)
            if result:
                errorlist.append(
                    {'Row': rownum, 'Field': sms_to_fieldname, 'Value': result['number'], 'Error': result['errormessage']})

            if sms_from_fieldname:
                result = smsnumbers_are_invalid(row[sms_from_fieldname],
                                                False,  # empty string not acceptable as a From number
                                                iso2countrycode,
                                                allowed_from_number)
                if result:
                    errorlist.append({'Row': rownum, 'Field': sms_from_fieldname, 'Value': result['number'],
                                      'Error': result['errormessage']})
            rownum += 1
    except Exception as e:
        errormessage = u'Encountered error validating SMS numbers. Error: {}'.format(e.message)
        log.logger.error(errormessage)
        errorlist.append(errormessage)
        return errorlist
    return errorlist


def smsnumbers_are_invalid(sms_numbers, emptystringok, iso2countrycode, regex_eval=None):
    """Validates all SMS numbers found in a given string, optionally that conform to the regex_eval"""
    
    log.logger.debug(u'Validating SMS field value: {}'.format(sms_numbers))

    sms_number_list = re.split(SMS_RECIP_SPLIT_REGEX, sms_numbers.strip())

    for sms_number in sms_number_list:
        log.logger.debug(u'Validating presumed sms number: {}'.format(sms_number))

        try:
            # skip if we're okay with empty, and it is
            if sms_number == '':
                if not emptystringok:
                    errormessage = u'SMS number is empty'
                else:
                    continue
            else:
                errormessage = smsnumber_is_invalid(sms_number, iso2countrycode, regex_eval)

            if errormessage:
                log.logger.debug(u'SMS number is invalid: {}, Error: {}'.format(sms_number, errormessage))
                if len(sms_number) > 64:
                    sms_number = sms_number[:64] + '...'  # truncate a too-long address for error formattting purposes
                return {'number': sms_number, 'errormessage': errormessage}
        except Exception as e:
            errormessage = u'Encountered error validating an SMS number. Error: {}'.format(e.message)
            log.logger.error(errormessage)
            return {'number': sms_number, 'errormessage': errormessage}
    return None


def smsnumber_is_invalid(smsnumber, iso2countrycode, regex_eval=None):
    """Checks for a syntactically invalid phone number, returns None for success or an error message"""

    try:
        e164_number = smsnumber_to_e164(smsnumber, iso2countrycode)

        # looks valid, but it must be permitted by regex pattern if so specified
        if regex_eval:
            log.logger.debug("testing smsnumber {} against regex {}".format(e164_number, regex_eval))
            if not re.match(regex_eval, e164_number):
                errormessage = u'SMS number must match regex pattern set by the administrator: {}'.format(regex_eval)
                log.logger.error(errormessage)
                return errormessage
    except Exception as e:
        return e.message

    # looks like it was fine!
    return None


def get_e164numbers(sms_numbers, iso2countrycode):
    """Converts a delimited string or list of SMS numbers to E.164 format
        Returns a UNIQUE list of E.164 numbers
        NOTE: This method ASSUMES that they have all been validated already """
    sms_number_list = []
    e164_numbers = []

    if isinstance(sms_numbers, str) or isinstance(sms_numbers, unicode):
        sms_number_list.extend(re.split(SMS_RECIP_SPLIT_REGEX, sms_numbers.strip()))
    elif isinstance(sms_numbers, list):
        sms_number_list.extend(sms_numbers)
    else:
        # that's not what we expected
        errormessage = u'Input is neither a string nor a list: {}'.format(sms_numbers)
        log.logger.error(errormessage)
        raise UserWarning(errormessage)

    # convert and add each number to our return list
    for sms_number in sms_number_list:
        log.logger.debug(u'Converting {} to E.164 format'.format(sms_number))
        try:
            e164_number = smsnumber_to_e164(sms_number, iso2countrycode)
            if e164_number not in e164_numbers:
                e164_numbers.append()
        except Exception as e:
            raise UserWarning(e.errormessage)

    return e164_numbers


def smsnumber_to_e164(smsnumber, iso2countrycode):
    """Tries to convert a string into an E.164 formatted phone number
       Raises exception if it can't, returns the E.164 number as a string, if it can """

    try:
        if smsnumber.startswith('+'):
            smsnumber_obj = phonenumbers.parse(smsnumber)
        else:
            # country code not specified in number, so pass it in
            smsnumber_obj = phonenumbers.parse(smsnumber, iso2countrycode)
    except phonenumbers.NumberParseException as e:
        errormessage = u'SMS Unable to parse number {}. Error: {}'.format(smsnumber, e.message)
        log.logger.error(errormessage)
        raise UserWarning(errormessage)

    if not phonenumbers.is_possible_number(smsnumber_obj):
        errormessage = u'SMS Number is not possibly valid: {}.'.format(smsnumber)
        log.logger.error(errormessage)
        raise UserWarning(errormessage)

    if not phonenumbers.is_valid_number(smsnumber_obj):
        errormessage = u'SMS Number is not valid: {}.'.format(smsnumber)
        log.logger.error(errormessage)
        raise UserWarning(errormessage)

    try:
        e164_number = phonenumbers.format_number(smsnumber_obj, phonenumbers.PhoneNumberFormat.E164)
        if not e164_number:
            errormessage = u'SMS number {} could not be converted to E.164 for an unknown reason.'.format(smsnumber)
            log.logger.error(errormessage)
            raise UserWarning(errormessage)

        # all good, return it!
        return e164_number
    except Exception as e:
        errormessage = u'Exception thrown converting SMS number {} to E.164. Error: {}'.format(smsnumber, e.message)
        log.logger.error(errormessage)
        raise UserWarning(errormessage)
