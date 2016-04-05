#! python
# -*- coding: utf-8 -*-
# This is a utility module for integrating SMS providers into VizAlerts.

import re

def get_sms_client(configs, logger):
    """Generic function get an SMS client object. This only works with Twilio at this time."""
    
    # check to see if there's a provider set
    if configs['smsaction.provider'] == None or len(configs['smsaction.provider']) == 0:
        errormessage = u'SMS Actions are enabled but smsaction.provider value is not set, exiting'
        logger.error(errormessage)
        raise ValueError(errormessage)        

    # load code for Twilio
    elif configs['smsaction.provider'].lower() == 'twilio': 
        # these need to be in the global name space to send SMS messages
        global twilio
        import twilio
        
        global twiliorest
        import twilio.rest as twiliorest
        
        global smsclient
        smsclient = twiliorest.TwilioRestClient(configs['smsaction.account_id'], configs['smsaction.auth_token'])    
        
        return smsclient

    # unknown SMS provider error
    else:
        errormessage = u'SMS Actions are enabled but found unknown smsaction.provider {}, exiting'.format(configs['smsaction.provider'])
        logger.error(errormessage)
        raise ValueError(errormessage)

        


def send_sms(configs, logger, smsclient, sms_from, sms_to, subject = None, content = None):
    """function to send an sms using Twilio's REST API, see https://www.twilio.com/docs/python/install for details.
    Presumes that numbers have gone through a first level of checks for validity"""

    logger.info(u'Sending SMS: {},{},{},{}'.format(sms_from, sms_to, subject, content))
    
    # shouldn't happen but setting content to '' if it's None
    if content == None:
        content == ''
   
    # shouldn't happen but setting subject to '' if it's None
    if subject == None:
        subject = ''

    # create the message body. if there's both subject & content then combine & label them.
    if len(subject) > 0 and len(content) > 0:
        msgbody = u'Subj: ' + subject + u'\nBody: ' + content
    elif len(subject) == 0 and len(content) == 0:
        raise ValueError(u'SMS message to {} has 0 length'.format(sms_to))
    else:
        msgbody = subject + content

    #get rid of everything but the numbers and prepend the + for the country
    sms_from = '+' + re.sub('[^0-9]','',sms_from)
    sms_to = '+' + re.sub('[^0-9]','',sms_to)

    # now to send the message
    try:
        message = smsclient.messages.create(body=msgbody, to=sms_to, from_=sms_from)

        # this may never happen since the Twilio REST API throws exceptions, it's a failsafe check
        if message.status == 'failed':
            raise ValueError(u'Failed to deliver SMS message to {} with body {}, no additional information is available')

    # check for Twilio REST API exceptions
    except twilio.TwilioRestException as e:
        errormessage = u'Could not send SMS message to {} with body {}.\nHTTP status {} returned for request: {} {}\nWith error {}: {} '.format(sms_to, msgbody, e.status, e.method, e.uri, e.code, e.msg)
        logger.error(errormessage)
        return errormessage

    # check for ValueError from try 
    except ValueError as e:
        logger.error(e)
        return e

    except Exception as e:
        errormessage = u'Could not send SMS message to {} with body {}, error {}'.format(sms_to, msgbody, e)
        logger.error(errormessage)
        return e
    
    return None