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
from requests_ntlm import HttpNtlmAuth


class Format(object):
    CSV = 'csv'
    PNG = 'png'
    PDF = 'pdf'


# Generate a trusted ticket
def get_trusted_ticket(server, sitename, username, encrypt, logger, userdomain=None, clientip=None, tries=1):

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

            request = urllib2.Request(trustedurl, data)
            response = urllib2.urlopen(request)
            ticket = response.read()
            logger.debug(u'Got ticket: {}'.format(ticket))

            if ticket == '-1' or not ticket:
                errormessage = u'Error generating trusted ticket. Value of ticket is {}.  Please see http://onlinehelp.tableau.com/current/server/en-us/trusted_auth_trouble_1return.htm Request details:'.format(ticket, requestdetails)
                logger.error(errormessage)
                raise UserWarning(errormessage)

        except urllib2.HTTPError as e:
            errormessage = cgi.escape(u'HTTPError generating trusted ticket: {}  Request details: {}'.format(str(e.code), requestdetails))
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue
        except urllib2.URLError as e:
            errormessage = cgi.escape(u'URLError generating trusted ticket: {}  Request details: {}'.format(str(e.message), requestdetails))
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
    viewname = unicode(view['view_name'])
    viewurlsuffix = view['view_url_suffix']
    username = view['subscriber_sysname']
    sitename = unicode(view["site_name"]).replace('Default', '')
    if view['subscriber_domain'] != 'local': # leave it as None if Server uses local authentication
        subscriberdomain = view['subscriber_domain']
    else:
        subscriberdomain = None
    timeout_s = view['timeout_s']
    refresh = view['force_refresh']
    tries = view["data_retrieval_tries"]

    server = configs["server"]
    encrypt = configs["server.ssl"]
    pngwidth = configs["viz.png.width"]
    pngheight = configs["viz.png.height"]
    tempdir = configs["temp.dir"]
    if configs["trusted.useclientip"]:
        clientip = configs["trusted.clientip"]
    else:
        clientip = None

    # variables used later in the script
    response = None
    ticket = None

    # overrides for various url components
    if configs["server.ssl"]:
        protocol = u'https'
    else:
        protocol = u'http'

    if format == Format.PNG:
        formatparam = u'?:format=' + format + u'&:size={},{}'.format(str(pngwidth), str(pngheight))
    else:
        formatparam = u'?:format=' + format

    if sitename != '':
        sitepart = u'/t/' + sitename
    else:
        sitepart = sitename

    # get the full URL (minus the ticket) for logging and error reporting
    displayurl = protocol + u'://' + server + sitepart + u'/views/' + viewurlsuffix + formatparam
    if refresh:
        displayurl = displayurl + u'&:refresh=y'   # show admin/users that we forced a refresh

    while tries > 0:
        try:
            tries -= 1

            # get a trusted ticket
            ticket = get_trusted_ticket(server, sitename, username, encrypt, logger, subscriberdomain, clientip)

            # build final URL
            url = protocol + u'://' + server + u'/trusted/' + ticket + sitepart + u'/views/' + viewurlsuffix + formatparam
            if refresh:
                url = url + u'&:refresh=y'   # force a refresh of the data--we don't want alerts based on cached (stale) data

            logger.debug(u'Getting vizdata from: {}'.format(url))

            # Make the GET call to obtain the data
            response = None
            if subscriberdomain:
                # Tableau Server is using AD auth (is this even needed? May need to remove later)
                response = requests.get(url, auth=HttpNtlmAuth(subscriberdomain + u'\\' + username, ''), verify=False, timeout=timeout_s)
            else:
                # Server is using local auth
                response = requests.get(url, auth=(username, ''), verify=False, timeout=timeout_s)
            if not response.ok:
                raise requests.RequestException

            # Create the temporary file
            timestamp = time.time()
            datestring = datetime.datetime.fromtimestamp(timestamp).strftime('%Y%m%d%H%M%S')
            filename = datestring + '_' + viewurlsuffix.replace('/', '-') + '.' + format
            filepath = tempdir + filename

            logger.info(u'Attempting to write to: {}'.format(filepath))

            if format == Format.CSV:
                f = open(filepath, 'w')
                f.write(response.content.replace('\r\n', '\r'))  # remove extra carriage returns
            else:
                f = open(filepath, 'wb')
                for block in response.iter_content(1024):
                    if not block:
                        break
                    f.write(block)
            f.close()
            return unicode(filepath)

        except urllib2.HTTPError as e:
            errormessage = cgi.escape(u'HTTP error getting vizdata from url {}. Code: {}, Reason data: {}'.format(displayurl, e.code, e.reason))
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue
        except requests.exceptions.RequestException as e:
            errormessage = cgi.escape(u'Unable to get vizdata from url {}. Cause: {}'.format(displayurl, e))
            if response:
                errormessage = errormessage + ', response: {}'.format(response)
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
            errormessage = cgi.escape(u'Unable to export the url {} to {}, error: {}'.format(displayurl, format, e))
            if response:
                errormessage = errormessage + ', response: {}'.format(response)
            logger.error(errormessage)
            if tries == 0:
                raise UserWarning(errormessage)
            else:
                continue

        # got through with no errors
        break
