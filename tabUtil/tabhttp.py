#! python
# -*- coding: utf-8 -*-
# This is a utility module to provide a single interface for interacting with Tableau Server over http.

import os
import urllib
import urllib2
import requests
import time
import datetime
import cgi
import codecs
import re
import ssl
import threading
from requests_ntlm import HttpNtlmAuth
from requests.packages.urllib3.exceptions import InsecureRequestWarning


class Format(object):
    CSV = 'csv'
    PNG = 'png'
    PDF = 'pdf'
    TWB = 'twb'


# Generate a trusted ticket
def get_trusted_ticket(server, sitename, username, encrypt, logger, certcheck=True, certfile=None, userdomain=None, clientip=None, tries=1):
    
    protocol = u'http'

    # overrides for https
    if encrypt:
        protocol = u'https'

    trustedurl = protocol + u'://{}/trusted'.format(server)

    # build the data to send in the POST request
    if userdomain:
        postdata = {'username': (userdomain + '\\' + username)}
    else:
        postdata = {'username': username}

    if clientip:
        postdata['client_ip'] = clientip

    if sitename != '':
        postdata['target_site'] = sitename

    data = urllib.urlencode(postdata)
    requestdetails = u'Server: {}, Site: {}, Username: {}, Url: {}, Postdata: {}.'.format(
                            server,
                            sitename,
                            username,
                            trustedurl,
                            data)
    logger.debug(u'Generating trusted ticket. Request details: {}'.format(requestdetails))

    ticket = 0
    while tries > 0:
        try:
            tries -= 1

            # If we're using SSL, and config says to validate the certificate, then do so
            if encrypt and certcheck:
                logger.debug('using SSL and verifying cert')
                request = urllib2.Request(trustedurl, data)
                response = urllib2.urlopen(request, cafile=certfile)
            else:
                # We're either not using SSL, or just not validating the certificate
                logger.debug('NOT using SSL and NOT verifying cert')
                context = ssl._create_unverified_context()
                request = urllib2.Request(trustedurl, data)
                response = urllib2.urlopen(request, context=context)

            ticket = response.read()
            logger.debug(u'Got ticket: {}'.format(ticket))

            if ticket == '-1' or not ticket:
                errormessage = u'Error generating trusted ticket. Value of ticket is {}.  Please see http://onlinehelp.tableau.com/current/server/en-us/trusted_auth_trouble_1return.htm Request details:'.format(ticket, requestdetails)
                logger.error(errormessage)
                raise UserWarning(errormessage)

        except urllib2.HTTPError as e:
            errormessage = cgi.escape(u'HTTPError generating trusted ticket: {}  Request details: {}'.format(str(e.reason), requestdetails))
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue
        except urllib2.URLError as e:
            errormessage = cgi.escape(u'URLError generating trusted ticket: {}  Request details: {}'.format(str(e.reason), requestdetails))
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue
        except UserWarning as e:
            errormessage = cgi.escape(u'UserWarning generating trusted ticket: {}  Request details: {}'.format(str(e.message), requestdetails))
            logger.error(errormessage)
            raise UserWarning(errormessage)
        except Exception as e:
            errormessage = cgi.escape(u'Generic exception generating trusted ticket: {}  Request details: {}'.format(str(e.message), requestdetails))
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue

        # no need for further retries
        return ticket


# Export a view to a file in the specified format based on a trusted ticket
def export_view(configs, view, format, logger):

    # assign variables (clean this up later)
    viewname = unicode(view.view_name)

    username = view.subscriber_sysname
    sitename = unicode(view.site_name).replace('Default', '')
    if view.subscriber_domain != 'local': # leave it as None if Server uses local authentication
        subscriberdomain = view.subscriber_domain
    else:
        subscriberdomain = None

    timeout_s = view.timeout_s
    refresh = view.force_refresh
    tries = view.data_retrieval_tries
    pngwidth = view.viz_png_width
    pngheight = view.viz_png_height

    server = configs['server']
    encrypt = configs['server.ssl']
    certcheck = configs['server.certcheck']
    certfile = configs['server.certfile']
    tempdir = configs['temp.dir']
    if configs['trusted.useclientip']:
        clientip = configs['trusted.clientip']
    else:
        clientip = None

    # variables used later in the script
    response = None
    ticket = None

    # overrides for various url components
    if configs['server.ssl']:
        protocol = u'https'
    else:
        protocol = u'http'

    #viewurlsuffix may be of form workbook/view
    #or workbook/view?param1=value1&param2=value2
    #in the latter case separate it out
    search = re.search(u'(.*?)\?(.*)', view.view_url_suffix)
    if search:
        viewurlsuffix = search.group(1)
        extraurlparameter = '?' + search.group(2)
    else:
        viewurlsuffix = view.view_url_suffix
        # always need a ? to add in the formatparam and potentially refresh URL parameters
        extraurlparameter = '?'

    # set up format
    # if user hasn't overriden PNG with size setting then use the default  
    if format == Format.PNG and ':size=' not in extraurlparameter:
            formatparam = u'&:format=' + format + u'&:size={},{}'.format(str(pngwidth), str(pngheight))
    else:
        formatparam = u'&:format=' + format

    if sitename != '':
        sitepart = u'/t/' + sitename
    else:
        sitepart = sitename

    # get the full URL (minus the ticket) for logging and error reporting
    displayurl = protocol + u'://' + server + sitepart + u'/views/' + viewurlsuffix + extraurlparameter + formatparam
    if refresh:
        displayurl = displayurl + u'&:refresh=y'   # show admin/users that we forced a refresh

    while tries > 0:
        try:
            tries -= 1

            # get a trusted ticket
            ticket = get_trusted_ticket(server, sitename, username, encrypt, logger, certcheck, certfile, subscriberdomain, clientip)

            # build final URL
            url = protocol + u'://' + server + u'/trusted/' + ticket + sitepart + u'/views/' + viewurlsuffix + extraurlparameter + formatparam
            if refresh:
                url = url + u'&:refresh=y'   # force a refresh of the data--we don't want alerts based on cached (stale) data

            logger.debug(u'Getting vizdata from: {}'.format(url))

            # Make the GET call to obtain the data
            response = None
            if subscriberdomain:
                # Tableau Server is using AD auth (is this even needed? May need to remove later)
                if certcheck:
                    logger.debug('Validating cert for this request')
                    response = requests.get(url, auth=HttpNtlmAuth(subscriberdomain + u'\\' + username, ''), verify=certfile, timeout=timeout_s)
                else:
                    logger.debug('NOT Validating cert for this request')
                    requests.packages.urllib3.disable_warnings(InsecureRequestWarning) # disable warnings for unverified certs
                    response = requests.get(url, auth=HttpNtlmAuth(subscriberdomain + u'\\' + username, ''), verify=False, timeout=timeout_s)
            else:
                # Server is using local auth
                if certcheck:
                    logger.debug('Validating cert for this request')
                    response = requests.get(url, auth=(username, ''), verify=certfile, timeout=timeout_s)
                else:
                    logger.debug('NOT Validating cert for this request')
                    requests.packages.urllib3.disable_warnings(InsecureRequestWarning) # disable warnings for unverified certs
                    response = requests.get(url, auth=(username, ''), verify=False, timeout=timeout_s)
            response.raise_for_status()

            # Create the temporary file, datestring is down to microsecond to prevent dups since
            # we are excluding any extraurl parameters for space & security reasons
            # (users might obfuscate results by hiding URL parameters)
            datestring = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
            filename = datestring + '_' + threading.current_thread().name + '_' + viewurlsuffix.replace('/', '-') + '.' + format
            filepath = tempdir + filename

            logger.info(u'Attempting to write to: {}'.format(filepath))

            if format == Format.CSV:
                f = open(filepath, 'w')
                f.write(response.content.replace('\r\n', '\n')) # remove extra carriage returns
            else:
                f = open(filepath, 'wb')
                for block in response.iter_content(1024):
                    if not block:
                        break
                    f.write(block)
            f.close()
            return unicode(filepath)
        except requests.exceptions.HTTPError as e:
            errormessage = cgi.escape(u'HTTP error getting vizdata from url {}. Code: {}, Response data:<br><br> {}'.format(displayurl, e.response.status_code, e.response.text))
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue
        except requests.exceptions.SSLError as e:
            errormessage = cgi.escape(u'SSL error getting vizdata from url {}. Error: {}'.format(displayurl, e))
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue
        except requests.exceptions.RequestException as e:
            errormessage = cgi.escape(u'Request Exception getting vizdata from url {}. Error: {}'.format(displayurl, e))
            if response:
                errormessage += ' Response: {}'.format(response)
            if hasattr(e, 'code'):
                errormessage += ' Code: {}'.format(e.code)
            if hasattr(e, 'reason'):
                errormessage += ' Reason: {}'.format(e.reason)

            #errormessage = errormessage + ', Error: {}, status: {}, response: {}. '.format(response.error, response.status_code, response.text)
            #if response:
                
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue
        except IOError as e:
            errormessage = cgi.escape(u'Unable to write the file {} for url {}, error: {}'.format(filepath, displayurl, e))
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue
        except Exception as e:
            errormessage = cgi.escape(u'Generic exception trying to export the url {} to {}, error: {}'.format(displayurl, format, e))
            if response:
                errormessage = errormessage + ', response: {}'.format(response)
            if hasattr(e, 'code'):
                errormessage += ' Code: {}'.format(e.code)
            if hasattr(e, 'reason'):
                errormessage += ' Reason: {}'.format(e.reason)
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue

        # got through with no errors
        break
