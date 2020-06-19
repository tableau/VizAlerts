#! python
# -*- coding: utf-8 -*-
# This is a utility module to provide a single interface for interacting with Tableau Server over http.

import os
import urllib.request, urllib.parse, urllib.error
import urllib.request, urllib.error, urllib.parse
import requests
import time
import datetime
import html
import codecs
import re
import ssl
import threading
from . import config
from . import log
from requests_ntlm import HttpNtlmAuth
from requests.packages.urllib3.exceptions import InsecureRequestWarning


class Format(object):
    CSV = 'csv'
    PNG = 'png'
    PDF = 'pdf'
    TWB = 'twb'


# Generate a trusted ticket
def get_trusted_ticket(server, sitename, username, encrypt, certcheck=True, certfile=None, userdomain=None, clientip=None, tries=1):
    
    protocol = 'http'
    attempts = 0

    # overrides for https
    if encrypt:
        protocol = 'https'

    trustedurl = protocol + '://{}/trusted'.format(server)

    # build the data to send in the POST request
    if userdomain:
        postdata = {'username': (userdomain + '\\' + username)}
    else:
        postdata = {'username': username}

    if clientip:
        postdata['client_ip'] = clientip

    if sitename != '':
        postdata['target_site'] = sitename

    data = urllib.parse.urlencode(postdata).encode("utf-8")
    requestdetails = 'Server: {}, Site: {}, Username: {}, Url: {}, Postdata: {}.'.format(
                            server,
                            sitename,
                            username,
                            trustedurl,
                            data)
    log.logger.debug('Generating trusted ticket. Request details: {}'.format(requestdetails))

    ticket = 0
    while attempts < tries:
        try:
            attempts += 1

            # If we're using SSL, and config says to validate the certificate, then do so
            if encrypt and certcheck:
                if not certfile:
                    certfile = requests.utils.DEFAULT_CA_BUNDLE_PATH
                log.logger.debug('using SSL and verifying cert using certfile {}'.format(certfile))
                request = urllib.request.Request(trustedurl, data)
                context = ssl.create_default_context(cafile=certfile)
                response = urllib.request.urlopen(request, context=context)
            else:
                # We're either not using SSL, or just not validating the certificate
                if encrypt:
                    log.logger.debug('using SSL and NOT verifying cert')
                else:
                    log.logger.debug('NOT using SSL and NOT verifying cert')
                context = ssl._create_unverified_context()
                request = urllib.request.Request(trustedurl, data)
                response = urllib.request.urlopen(request, context=context)

            ticket = response.read().decode()
            log.logger.debug('Got ticket: {}'.format(ticket))

            if ticket == '-1' or not ticket:
                errormessage = 'Error generating trusted ticket. Value of ticket is {}.  Please see http://onlinehelp.tableau.com/current/server/en-us/trusted_auth_trouble_1return.htm Request details:'.format(ticket, requestdetails)
                log.logger.error(errormessage)
                raise UserWarning(errormessage)

        except urllib.error.HTTPError as e:
            errormessage = html.escape('HTTPError generating trusted ticket: {}  Request details: {}'.format(str(e.reason), requestdetails))
            log.logger.error(errormessage)
            if attempts >= tries:
                raise UserWarning(errormessage)
            else:
                continue
        except urllib.error.URLError as e:
            errormessage = html.escape('URLError generating trusted ticket: {}  Request details: {}'.format(str(e.reason), requestdetails))
            log.logger.error(errormessage)
            if attempts >= tries:
                raise UserWarning(errormessage)
            else:
                continue
        except UserWarning as e:
            errormessage = html.escape(u'UserWarning generating trusted ticket: {}  Request details: {}'.format(str(e.args[0]), requestdetails))
            log.logger.error(errormessage)
            raise UserWarning(errormessage)
        except Exception as e:
            errormessage = html.escape('Generic exception generating trusted ticket: {}  Request details: {}'.format(str(e.args[0]), requestdetails))
            log.logger.error(errormessage)
            if attempts >= tries:
                raise UserWarning(errormessage)
            else:
                continue

        # no need for further retries
        return ticket


# Export a view to a file in the specified format based on a trusted ticket
def export_view(view_url_suffix, site_name, timeout_s, data_retrieval_tries, force_refresh, format,
                viz_png_width, viz_png_height, user_sysname, user_domain):

    # assign variables (clean this up later)
    site_name = str(site_name).replace('Default', '')

    if user_domain == 'local':  # leave it as None if Server uses local authentication
        user_domain = None

    attempts = 0

    server = config.configs['server']
    encrypt = config.configs['server.ssl']
    certcheck = config.configs['server.certcheck']
    certfile = config.configs['server.certfile']
    tempdir = config.configs['temp.dir']
    if config.configs['trusted.useclientip']:
        clientip = config.configs['trusted.clientip']
    else:
        clientip = None

    # variables used later in the script
    response = None
    ticket = None

    # overrides for various url components
    if config.configs['server.ssl']:
        protocol = 'https'
    else:
        protocol = 'http'

    #viewurlsuffix may be of form workbook/view
    #or workbook/view?param1=value1&param2=value2
    #in the latter case separate it out
    search = re.search('(.*?)\?(.*)', view_url_suffix)
    if search:
        viewurlsuffix = search.group(1)
        extraurlparameter = '?' + search.group(2)
    else:
        viewurlsuffix = view_url_suffix
        # always need a ? to add in the formatparam and potentially force_refresh URL parameters
        extraurlparameter = '?'

    # set up format
    # if user hasn't overriden PNG with size setting then use the default  
    if format == Format.PNG and ':size=' not in extraurlparameter:
            formatparam = '&:format=' + format + '&:size={},{}'.format(str(viz_png_width), str(viz_png_height))
    else:
        formatparam = '&:format=' + format

    if site_name != '':
        sitepart = '/t/' + site_name
    else:
        sitepart = site_name

    # get the full URL (minus the ticket) for logging and error reporting
    displayurl = protocol + '://' + server + sitepart + '/views/' + viewurlsuffix + extraurlparameter + formatparam
    if force_refresh:
        displayurl = displayurl + '&:refresh=y'   # show admin/users that we forced a force_refresh

    while attempts < data_retrieval_tries:
        try:
            attempts += 1

            # get a trusted ticket
            ticket = get_trusted_ticket(server, site_name, user_sysname, encrypt, certcheck, certfile, user_domain, clientip)
			
            # build final URL
            url = protocol + '://' + server + '/trusted/' + ticket + sitepart + '/views/' + viewurlsuffix + extraurlparameter + formatparam

            if force_refresh:
                url = url + '&:refresh=y'   # force a force_refresh of the data--we don't want alerts based on cached (stale) data

            log.logger.debug('Getting vizdata from: {}'.format(url))

            # Make the GET call to obtain the data
            response = None
            if user_domain:
                # Tableau Server is using AD auth (is this even needed? May need to remove later)
                if certcheck:
                    log.logger.debug('Validating cert for this request using certfile {}'.format(certfile))
                    if not certfile:
                        certfile = requests.utils.DEFAULT_CA_BUNDLE_PATH
                    response = requests.get(url, auth=HttpNtlmAuth(user_domain + '\\' + user_sysname, ''), verify=certfile, timeout=timeout_s)
                else:
                    log.logger.debug('NOT Validating cert for this request')
                    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)  # disable warnings for unverified certs
                    response = requests.get(url, auth=HttpNtlmAuth(user_domain + '\\' + user_sysname, ''), verify=False, timeout=timeout_s)
            else:
                # Server is using local auth
                if certcheck:
                    log.logger.debug('Validating cert for this request using certfile {}'.format(certfile))
                    if not certfile:
                        certfile = requests.utils.DEFAULT_CA_BUNDLE_PATH
                    response = requests.get(url, auth=(user_sysname, ''), verify=certfile, timeout=timeout_s)
                else:
                    log.logger.debug('NOT Validating cert for this request')
                    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)  # disable warnings for unverified certs
                    response = requests.get(url, auth=(user_sysname, ''), verify=False, timeout=timeout_s)
            response.raise_for_status()

            # Create the temporary file, datestring is down to microsecond to prevent dups since
            # we are excluding any extraurl parameters for space & security reasons
            # (users might obfuscate results by hiding URL parameters)
            datestring = datetime.datetime.now().strftime('%Y%m%d%H%M%S%f')
            filename = datestring + '_' + threading.current_thread().name + '_' + viewurlsuffix.replace('/', '-') + '.' + format
            filepath = tempdir + filename

            log.logger.info('Attempting to write to: {}'.format(filepath))

            if format == Format.CSV:
                f = open(filepath, 'wb')
                filebytes = response.content
                realstr = filebytes.decode(encoding='utf-8')
                lateststr = realstr.replace('\r\n', '\n')
                finalbinary = lateststr.encode()
                f.write(finalbinary) # remove extra carriage returns
            else:
                f = open(filepath, 'wb')
                for block in response.iter_content(1024):
                    if not block:
                        break
                    f.write(block)
            f.close()
            return filepath
        except requests.exceptions.Timeout as e:
            errormessage = html.escape('Timeout error. Could not retrieve vizdata from url {} within {} seconds, after {} tries'.format(displayurl, timeout_s, attempts))
            log.logger.error(errormessage)
            if attempts >= data_retrieval_tries:
                raise UserWarning(errormessage)
            else:
                continue
        except requests.exceptions.HTTPError as e:
            errormessage = html.escape('HTTP error getting vizdata from url {}. Code: {} Reason: {}'.format(displayurl, e.response.status_code, e.response.reason))
            log.logger.error(errormessage)
            if attempts >= data_retrieval_tries:
                raise UserWarning(errormessage)
            else:
                continue
        except requests.exceptions.SSLError as e:
            errormessage = html.escape('SSL error getting vizdata from url {}. Error: {}'.format(displayurl, e))
            log.logger.error(errormessage)
            if attempts >= data_retrieval_tries:
                raise UserWarning(errormessage)
            else:
                continue
        except requests.exceptions.RequestException as e:
            errormessage = html.escape('Request Exception getting vizdata from url {}. Error: {}'.format(displayurl, e))
            if response:
                errormessage += ' Response: {}'.format(response)
            if hasattr(e, 'code'):
                errormessage += ' Code: {}'.format(e.code)
            if hasattr(e, 'reason'):
                errormessage += ' Reason: {}'.format(e.reason)
            log.logger.error(errormessage)
            if attempts >= data_retrieval_tries:
                raise UserWarning(errormessage)
            else:
                continue
        except IOError as e:
            errormessage = html.escape('Unable to write the file {} for url {}, error: {}'.format(filepath, displayurl, e))
            log.logger.error(errormessage)
            if attempts >= data_retrieval_tries:
                raise UserWarning(errormessage)
            else:
                continue
        except Exception as e:
            errormessage = html.escape('Generic exception trying to export the url {} to {}, error: {}'.format(displayurl, format, e))
            if response:
                errormessage = errormessage + ', response: {}'.format(response)
            if hasattr(e, 'code'):
                errormessage += ' Code: {}'.format(e.code)
            if hasattr(e, 'reason'):
                errormessage += ' Reason: {}'.format(e.reason)
            log.logger.error(errormessage)
            if attempts >= data_retrieval_tries:
                raise UserWarning(errormessage)
            else:
                continue

        # got through with no errors
        break
