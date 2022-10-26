#! python
# -*- coding: utf-8 -*-
# Script to generate conditional automation against published views from a Tableau Server instance

__author__ = 'Matt Coles'
__credits__ = 'Jonathan Drummey'
__version__ = '2.2.1'

# generic modules
import logging
import sys
import os
import traceback
import datetime
import time
import fileinput
import codecs
import re
from queue import Queue
import threading
from operator import attrgetter
import argparse

# local modules
import vizalert
from vizalert import tabhttp
from vizalert import config
from vizalert import log
from vizalert import emailaction
from vizalert import smsaction
from vizalert import vizalert

# name of the file used for maintaining subscriptions state in schedule.state.dir
SCHEDULE_STATE_FILENAME = 'vizalerts.state'


class VizAlertWorker(threading.Thread):
    def __init__(self, threadname, alert_queue):
        threading.Thread.__init__(self, name=threadname)
        self.queue = alert_queue
        self.threadname = threadname

    def run(self):
        # loop infinitely, breaking when the queue is out of work (should add a timeout!)
        while 1 == 1:
            if self.queue.qsize() == 0:
                return
            else:
                # Get the work from the queue and expand the tuple
                alert = self.queue.get()

                log.logger.debug('Thread {} is processing subscription_id {}, view_id {}, '
                                 'site_name {}, customized_view_id {}, '
                                 'view_name {}'.format(
                                    self.threadname,
                                    alert.subscription_id,
                                    alert.view_id,
                                    alert.site_name,
                                    alert.customized_view_id,
                                    alert.view_name))

                # process the alert
                try:
                    alert.execute_alert()
                except Exception as e:
                    errormessage = 'Unable to process alert {} as {}, error: {}'.format(alert.view_name,
                                                                                         tabhttp.Format.CSV,
                                                                                         e.args[0])
                    log.logger.error(errormessage)
                    alert.error_list.append(errormessage)
                    alert.alert_failure()
                    continue


def main():

    try:
        # parse command-line arguments
        parser = argparse.ArgumentParser(description='Execute the VizAlerts process.')
        parser.add_argument('-c', '--configpath', help='Path to .yml configuration file')
        args = parser.parse_args()

        # validate and load configs from yaml file
        configfile = '.\\config\\vizalerts.yaml'
        if args.configpath is not None:
            configfile = args.configpath

        config.validate_conf(configfile)

        # initialize logging
        log.logger = logging.getLogger()
        if not len(log.logger.handlers):
            log.logger = log.LoggerQuickSetup(config.configs['log.dir'] + 'vizalerts.log', log_level=config.configs['log.level'])
    except Exception as e:
        print('Could not initialize configuration file due to an unknown error: {}'.format(e.args[0]))

    # we have our logger, so start writing
    log.logger.info('VizAlerts v{} is starting'.format(__version__))

    # cleanup old temp files
    try:
        cleanup_dir(config.configs['temp.dir'], config.configs['temp.dir.file_retention_seconds'])
    except OSError as e:
        # Send mail to the admin informing them of the problem, but don't quit
        errormessage = 'OSError: Unable to cleanup temp directory {}, error: {}'.format(config.configs['temp.dir'], e)
        log.logger.error(errormessage)
        email_instance = emailaction.Email(config.configs['smtp.address.from'], config.configs['smtp.address.to'], config.configs['smtp.subject'], errormessage)
        emailaction.send_email(email_instance)
    except Exception as e:
        errormessage = 'Unable to cleanup temp directory {}, error: {}'.format(config.configs['temp.dir'], e)
        log.logger.error(errormessage)
        email_instance = emailaction.Email(config.configs['smtp.address.from'], config.configs['smtp.address.to'], config.configs['smtp.subject'], errormessage)
        emailaction.send_email(email_instance)

    # cleanup old log files
    try:
        cleanup_dir(config.configs['log.dir'], config.configs['log.dir.file_retention_seconds'])
    except OSError as e:
        # Send mail to the admin informing them of the problem, but don't quit
        errormessage = 'OSError: Unable to cleanup log directory {}, error: {}'.format(config.configs['log.dir'], e)
        log.logger.error(errormessage)
        emailaction.send_email(config.configs['smtp.address.from'], config.configs['smtp.address.to'], config.configs['smtp.subject'], errormessage)
    except Exception as e:
        errormessage = 'Unable to cleanup log directory {}, error: {}'.format(config.configs['log.dir'], e)
        log.logger.error(errormessage)
        emailaction.send_email(config.configs['smtp.address.from'], config.configs['smtp.address.to'], config.configs['smtp.subject'], errormessage)

    # test ability to connect to Tableau Server and obtain a trusted ticket
    trusted_ticket_test()

    # if SMS Actions are enabled, attempt to obtain an sms client
    if config.configs['smsaction.enable']:
        try:
            smsaction.smsclient = smsaction.get_sms_client()
            log.logger.info('SMS Actions are enabled')
        except Exception as e:
            errormessage = 'Unable to get SMS client, error: {}'.format(e.args[0])
            log.logger.error(errormessage)
            quit_script(errormessage)

    # get the alerts to process
    try:
        alerts = get_alerts()
        log.logger.info('Processing a total of {} alerts'.format(len(alerts)))
    except Exception as e:
        errormessage = 'Unable to get alerts to process, error: {}'.format(e.args[0])
        log.logger.error(errormessage)
        quit_script(errormessage)

    if alerts:
        """Iterate through the list of applicable alerts, and process each"""

        alert_queue = Queue()
        for alert in sorted(alerts, key=attrgetter('priority')):
            log.logger.debug('Queueing subscription id {} for processing'.format(alert.subscription_id))
            alert_queue.put(alert)

        # create all worker threads
        for index in range(config.configs['threads']):
            threadname = index + 1  # start thread names at 1
            worker = VizAlertWorker(threadname, alert_queue)
            log.logger.debug('Starting thread with name: {}'.format(threadname))
            worker.start()

        # loop until work is done
        while 1 == 1:
            if threading.active_count() == 1:
                log.logger.info('Worker threads have completed. Exiting')
                return
            time.sleep(10)
            log.logger.info('Waiting on {} worker threads. Currently active threads:: {}'.format(
                threading.active_count() - 1,
                threading.enumerate()))


def trusted_ticket_test():
    """Test ability to generate a trusted ticket from Tableau Server"""
    # test for ability to generate a trusted ticket with the general username provided
    if config.configs['trusted.useclientip']:
        clientip = config.configs['trusted.clientip']
    else:
        clientip = None

    log.logger.debug('testing trusted ticket: {}, {}, {}, {}'.format(
        config.configs['server'],
        config.configs['server.user'],
        config.configs['server.user.domain'],
        clientip))
    sitename = ''  # this is just a test, use the default site
    test_ticket = None
    try:
        test_ticket = tabhttp.get_trusted_ticket(
            config.configs['server'],
            sitename,
            config.configs['server.user'],
            config.configs['server.ssl'],
            config.configs['server.certcheck'],
            config.configs['server.certfile'],
            config.configs['server.user.domain'],
            clientip)
        log.logger.debug('Generated test trusted ticket. Value is: {}'.format(test_ticket))
    except Exception as e:
        errormessage = e.args[0]
        log.logger.error(errormessage)
        quit_script(errormessage)


def get_alerts():
    """Get the set of VizAlerts from Tableau Server to check during this execution"""
    # package up the data from the source viz

    source_viz = vizalert.VizAlert(
        config.configs['vizalerts.source.viz'],
        config.configs['vizalerts.source.site'],
        config.configs['server.user'],
        config.configs['server.user.domain'])
    source_viz.view_name = 'VizAlerts Source Viz'
    source_viz.timeout_s = 30
    source_viz.force_refresh = True
    source_viz.data_retrieval_tries = 3

    log.logger.debug('Pulling source viz data down')

    try:
        source_viz.download_trigger_data()
        if len(source_viz.error_list) > 0:
            raise UserWarning(''.join(source_viz.error_list))
        results = source_viz.read_trigger_data()
        if len(source_viz.error_list) > 0:
            raise UserWarning(''.join(source_viz.error_list))

    except Exception as e:
        quit_script('Could not process source viz data from {} for the following reasons:<br/><br/>{}'.format(
			config.configs['vizalerts.source.viz'],
            e.args[0]))

    # test for regex invalidity
    try:
        fieldlist = ('allowed_from_address','allowed_recipient_addresses','allowed_recipient_numbers')
        currentfield = ''
        currentfieldvalue = ''
        for line in results:
            for field in fieldlist:
                currentfield = field
                currentfieldvalue = line[field]
                re.compile('{}'.format(currentfieldvalue))
    except Exception as e:
        quit_script('Could not process source viz data from {} for the following reason:<br/><br/>' \
		    'Invalid regular expression found. Could not evaluate expression \'{}\' in the field {}. Raw error:<br/><br/>{}'.format(
                config.configs['vizalerts.source.viz'],
                currentfieldvalue,
                currentfield,
                e.args[0]))

    # retrieve schedule data from the last run and compare to current
    statefile = config.configs['schedule.state.dir'] + SCHEDULE_STATE_FILENAME

    # list of all alerts we've retrieved from the server that may need to be run
    alerts = []

    # list of alerts to write to the state file again
    persistalerts = []

    # final list of views to execute alerts for
    execalerts = []
    try:
        if not os.path.exists(statefile):
            f = codecs.open(statefile, encoding='utf-8', mode='w+')
            f.close()
    except IOError as e:
        errormessage = 'Invalid schedule state file: {}'.format(e.args[0])
        log.logger.error(errormessage)
        quit_script(errormessage)

    # Create VizAlert instances for all the alerts we've retrieved
    try:
        results = source_viz.read_trigger_data() # get the results again to start at the beginning
        for line in results:
            # build an alert instance for each line            
            alert = vizalert.VizAlert(line['view_url_suffix'],
                                      line['site_name'],
                                      line['subscriber_sysname'],
                                      line['subscriber_domain'],
                                      line['subscriber_email'],
                                      line['view_name'])

            # Email actions
            alert.action_enabled_email = int(line['action_enabled_email'])
            alert.allowed_from_address = line['allowed_from_address']
            alert.allowed_recipient_addresses = line['allowed_recipient_addresses']            
            
            # SMS actions
            alert.action_enabled_sms = int(line['action_enabled_sms'])
            alert.allowed_recipient_numbers = line['allowed_recipient_numbers']
            alert.from_number = line['from_number']
            alert.phone_country_code = line['phone_country_code']

            alert.data_retrieval_tries = int(line['data_retrieval_tries'])

            if line['force_refresh'].lower() == 'true':
                alert.force_refresh = True
            else:
                alert.force_refresh = False

            alert.alert_type = line['alert_type']

            if line['notify_subscriber_on_failure'].lower() == 'true':
                alert.notify_subscriber_on_failure = True
            else:
                alert.notify_subscriber_on_failure = False

            alert.viz_data_maxrows = int(line['viz_data_maxrows'])
            alert.viz_png_height = int(line['viz_png_height'])
            alert.viz_png_width = int(line['viz_png_width'])
            alert.timeout_s = int(line['timeout_s'])
            alert.task_thread_count = int(line['task_threads'])

            # alert
            alert.alert_type = line['alert_type']
            if line['is_test'].lower() == 'true':
                alert.is_test = True
            else:
                alert.is_test = False

            if line['is_triggered_by_refresh'].lower() == 'true':
                alert.is_triggered_by_refresh = True
            else:
                alert.is_triggered_by_refresh = False

            # subscription
            if line['customized_view_id'] == '':
                alert.customized_view_id = None
            else:
                alert.customized_view_id = line['customized_view_id']

            alert.owner_email = line['owner_email']
            alert.owner_friendly_name = line['owner_friendly_name']
            alert.owner_sysname = line['owner_sysname']
            alert.project_id = int(line['project_id'])
            alert.project_name = line['project_name']
            alert.ran_last_at = line['ran_last_at']
            alert.run_next_at = line['run_next_at']
            alert.schedule_frequency = line['schedule_frequency']

            if line['schedule_id'] == '':
                alert.schedule_id = -1
            else:
                alert.schedule_id = int(line['schedule_id'])

            alert.schedule_name = line['schedule_name']

            if line['priority'] == '':
                alert.priority = -1
            else:
                alert.priority = int(line['priority'])

            if line['schedule_type'] == '':
                alert.schedule_type = -1
            else:
                alert.schedule_type = int(line['schedule_type'])

            alert.site_id = int(line['site_id'])
            alert.subscriber_license = line['subscriber_license']
            alert.subscriber_email = line['subscriber_email']
            alert.subscriber_user_id = int(line['subscriber_user_id'])
            alert.subscription_id = int(line['subscription_id'])
            alert.view_id = int(line['view_id'])
            alert.view_name = line['view_name']
            alert.view_owner_id = int(line['view_owner_id'])
            alert.workbook_id = int(line['workbook_id'])
            alert.workbook_repository_url = line['workbook_repository_url']

            # all done, now add it to the master list
            alerts.append(alert)
    except Exception as e:
        errormessage = 'Error instantiating alerts from list obtained from server: {}'.format(e)
        log.logger.error(errormessage)
        quit_script(errormessage)

    # now determine which actually need to be run now
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
                for alert in alerts:
                    # subscription_id is our unique identifier
                    if str(alert.subscription_id) == str(linedict['subscription_id']):

                        # preserve the last time the alert was scheduled to run
                        alert.ran_last_at = str(linedict['ran_last_at'])

                        # if the run_next_at date is greater for this alert since last we checked, mark it to run now
                        # the schedule condition ensures the alert doesn't run simply due to a schedule switch
                        # (note that CHANGING a schedule will still trigger the alert check...to be fixed later
                        if (
                                (datetime.datetime.strptime(str(alert.run_next_at), "%Y-%m-%d %H:%M:%S") \
                                         > datetime.datetime.strptime(str(linedict['run_next_at']),
                                                                       "%Y-%m-%d %H:%M:%S") \
                                         and str(alert.schedule_id) == str(linedict['schedule_id']))
                                # test alerts are handled differently
                                and not alert.is_test
                        ):

                                # For a test, run_next_at is anchored to the most recent comment, so use it as last run time
                                if alert.is_test:
                                    alert.ran_last_at = alert.run_next_at
                                else:
                                    alert.ran_last_at = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

                                seconds_since_last_run = \
                                    abs((
                                            datetime.datetime.strptime(str(linedict['ran_last_at']),
                                                                       "%Y-%m-%d %H:%M:%S") -
                                            datetime.datetime.utcnow()
                                        ).total_seconds())

                                execalerts.append(alert)

                        # else use the ran_last_at field, and write it to the state file? I dunno.

                        # add the alert to the list to write back to our state file
                        persistalerts.append(alert)

        # add NEW subscriptions that weren't in our state file
        # this is ugly I, know...sorry. someday I'll be better at Python.
        persist_sub_ids = []
        for alert in persistalerts:
            persist_sub_ids.append(alert.subscription_id)
        for alert in alerts:
            if alert.subscription_id not in persist_sub_ids:
                # if this is a test alert, and we haven't seen it before, run that puppy now!
                if alert.is_test:
                    execalerts.append(alert)
                persistalerts.append(alert)

        # write the next run times to file
        with codecs.open(statefile, encoding='utf-8', mode='w') as fw:
            fw.write('{}\t{}\t{}\t{}\t{}\t{}\t{}\n'.format("site_name", "subscription_id", "view_id",
                                                           "customized_view_id", "ran_last_at", "run_next_at",
                                                           "schedule_id"))
            for alert in persistalerts:
                fw.write('{}\t{}\t{}\t{}\t{}\t{}\t{}\n'.format(alert.site_name, alert.subscription_id,
                                                               alert.view_id, alert.customized_view_id,
                                                               alert.ran_last_at, alert.run_next_at,
                                                               alert.schedule_id))
    except IOError as e:
        errormessage = 'IOError accessing {} while getting views to process: {}'.format(e.filename, e.args[0])
        log.logger.error(errormessage)
        quit_script(errormessage)
    except Exception as e:
        errormessage = 'Error accessing {} while getting views to process: {}'.format(statefile, e)
        log.logger.error(errormessage)
        quit_script(errormessage)

    return execalerts

def quit_script(message):
    """"Called when a fatal error is encountered in the script"""
    try:
        email_instance = emailaction.Email(config.configs['smtp.address.from'], config.configs['smtp.address.to'],
                               config.configs['smtp.subject'], message)
        emailaction.send_email(email_instance)
    except Exception as e:
        log.logger.error('Unknown error-sending exception alert email: {}'.format(e.args[0]))
    sys.exit(1)

def cleanup_dir(path, expiry_s):
    """Deletes all files in the provided path with modified time greater than expiry_s"""
    files = os.listdir(path)
    for file in files:
        file = os.path.join(path, file)
        fileinfo = os.stat(file)
        if (datetime.datetime.now() - datetime.datetime.fromtimestamp(fileinfo.st_mtime)).total_seconds() > expiry_s:
            os.remove(file)

if __name__ == "__main__":
    exitcode = 0
    try:
        main()
        exitcode = 0
    except:
        log.logger.exception('An unhandled exception occurred: %s' % traceback.format_exc(sys.exc_info()))
        exitcode = 1
    finally:
        sys.exit(exitcode)
