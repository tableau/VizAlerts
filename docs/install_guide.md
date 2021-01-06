Tableau – VizAlerts Installation Guide

# Table of Contents
-  [What is VizAlerts?](#what-is-vizalerts)
-  [What does it do?](#what-does-it-do)
-  [How does it work?](#how-does-it-work)
-  [Upgrading from VizAlerts 2.1.1](#upgrading-from-vizalerts-2_1_1)
-  [Installation Prerequisites](#installation-prerequisites)
	- [Tableau Server](#tableau-server)
	- [Tableau Desktop](#tableau-desktop)
	- [Host Machine](#host-machine)
	- [SMTP (Mail) Server](#smtp-mail-server)
- [Installation](#installation)
	- [Configure Tableau Server](#configure-tableau-server)
		- [Trusted Tickets](#trusted-tickets)
		- [Repository Access](#repository-access)
		- [Restart](#restart)
		- [Custom Subscription Schedules](#custom-subscription-schedules)
	- [Open the VizAlertsConfig Workbook](#open-the-vizalertsconfig-workbook)
	- [Configure the VizAlertsScheduledTriggerView Viz](#configure-the-vizalerts-scheduledtriggerview-viz)
		- [Calculated Fields](#calculated-fields)
		- [Regex Notation](#regex-notation)
	- [Publish the VizAlertsConfig Workbook](#publish-the-scheduledtriggerviews-viz)
	- [Install Python & Required Modules](#install-python-required-modules)
	- [Configure VizAlerts](#configure-vizalerts)
	- [Testing](#testing)
		- [Can VizAlerts Connect? Test](#can-vizalerts-connect-test)
		- [Simple Alert Test](#simple-alert-test)
		- [Put VizAlerts Through Its Paces Test](#put-vizalerts-through-its-paces-test)
		- [Optional: Send Yourself Some SMS Messages Test](#optional-send-yourself-some-sms-messages-test)
	- [Final Steps](#final-steps)
		- [Set up a Scheduled Task](#set-up-a-scheduled-task)
		- [Starter Workbook](#starter-workbook)
- [FAQ](#faq)
- [Common Errors](#common-errors)
- [Getting VizAlerts Help](#getting-vizalerts-help)
- [Contributing to VizAlerts](#contributing-to-vizalerts)
- [Appendix A.](#appendix-a)
	- [Installing Python modules with no Internet access](#installing-python-modules-with-no-internet-access)


What is VizAlerts?<a id="what-is-vizalerts"></a>
==================

VizAlerts is an automation platform intended to seamlessly integrate
with Tableau Server. The idea behind it is that **anyone** should be
able to easily build, share, and customize nearly **any** any email or
SMS **automation** based on their own Tableau Server viz data. In the
future, VizAlerts will be able to perform even more actions than these.

In its current form, VizAlerts exists simply as an application that is
set up by a system administrator to run at frequent and regular
intervals. All of the information it needs to enable data-driven email
and SMS alerting is derived from the Tableau Server PostgreSQL
repository, and the published views of the Tableau Server it is set to
run against.

What does it do? <a id="what-does-it-do"></a>
================

VizAlerts has been designed to support many use cases:

-   Sending notifications to subscribers when a condition has been met
    (or not!) like extract refresh failures, meeting or missing target
    thresholds, etc.

-   Halting emails from being sent to the group unless the data is up to
    date (while the workbook owner does get an email that the data isn’t
    up to date).

-   Notify data owners when data is corrupt in some way (extraneous
    values, too many Null values, too large a change, etc.)

-   Sending a one line email notification that could be forwarded
    through an email-to-sms gateway such as \#\#\#\#\#\#\#\#@txt.att.net
    or a messaging provider such as Twilio.

-   Batch reporting to distribution lists of non-Tableau users, for
    example emailing a weekly operations report to front-line staff who
    aren’t on Tableau.

-   Combining images and text into an HTML email for a more customized,
    professional look.

-   Merge multiple views into a single consolidated PDF, for example
    sending a company overview and per-region detail.

-   Blend views from separate workbooks in the same email, for example a
    view from the operations dashboard and a view from the
    finance dashboard.

-   Bursting reports, for example sending to a manager a dashboard for
    each of her direct reports.

-   Send SMS messages to escalate an issue to your support staff.

-   Whatever combinations of the above you can imagine!

How does it work? <a id="how-does-it-work"></a>
=================

While the details on how to *set up* alerts will be left in the User
Guide, it’s important for Administrators to know how things are working
behind the scenes.

The general flow of a single execution of VizAlerts goes like this:

1.  Connect to the PostgreSQL repository database of Tableau Server, and
    query it for a list of Views subscribed to on specially configured,
    disabled Schedules

2.  Compare Schedule information to last runtime information stored in a
    local text file—based on this, determine which Views are due for
    alert testing

3.  For each View found due for testing:

    1.  Generate a Trusted Ticket on behalf of the Subscriber of the
        View

    2.  Redeem the Trusted Ticket to export the CSV data for the View,
        impersonating the Subscriber

    3.  If one or more rows are found in the CSV:

        1.  For a “Simple Alert”, generate a new Trusted Ticket, export
            the PNG of the View, and email it to the Subscriber.

        2.  For an “Advanced Alert”, iterate through each row of the
            CSV, sending emails or performing other actions as
            instructed by the data itself.


Upgrading from VizAlerts 2.1.1<a id="upgrading-from-vizalerts-2_1_1"></a>
=====================================

**NOTE** There are two important changes in this release: 

-   A fix to the VizAlertsConfig workbook for Tableau Server 2020.4.1

-   Switch from Python 2 to Python 3

If you are running VizAlerts with the binary EXE file, and are not using Tableau Server 2020.4 or higher, there is little reason to upgrade to 2.2.0.
If you are running it as a Python script, it is recommended that you upgrade, as Python 2 has been discontinued.
If you are upgrading to Tableau Server 2020.4 or higher, you can choose to upgrade VizAlerts, or [edit your VizAlertsConfig workbook](https://github.com/tableau/VizAlerts/issues/175) instead (the simpler solution).

Upgrading to VizAlerts 2.2.0 when running as a Python script will require installing Python 3. My own experience was that it is best that you first remove Python 2 from your system by uninstalling it, and removing all references to it from your environment variables. Then, you need to [install Python 3](#install-python-required-modules). Please be aware that uninstalling Python 2 will begin a VizAlerts outage, so please TEST on a separate server first, and plan your deployment accordingly.

1. Backup your current VizAlerts directory to a separate location.

2. Download version 2.2.0 from <https://github.com/tableau/VizAlerts/releases>, and unzip to a *new* folder alongside your existing VizAlerts folder. You should have three folders at this point: The live, current installation, the backup of the current installation, and a new folder you unzipped v2.2.0 into.

3. Merge VizAlertsConfig changes into new workbook
	- There is a new version of \config\VizAlertsConfig.twb that contains an edit to the _is_valid_schedule_ calc. It's easiest to simply drop this minor change into your existing VizAlertsConfig workbook. To do so, here are the steps:
		- Download your existing VizAlertsConfig workbook from Tableau Server and open it in Tableau Desktop
		- Edit the _is_valid_schedule_ calc in your VizAlertsConfig workbook so that the first line is **[subscription_id] < 0** rather than **ISNULL(schedule_id)**
		- Now re-publish the current VizAlertsConfig workbook to Tableau Server, **making sure** that you are embedding the password in the connection. This will _not_ break v2.1.1 of VizAlerts.
<br><br>

4. Copy other config files
	- Copy the \config\vizalerts.yaml file from your *current* VizAlerts folder *over* the same file in the *new* VizAlerts folder
		- No changes were made to this file, so it will work just fine the way it is
	- If you're using SSL to connect to Tableau Server, and have a certificate file you're storing in the VizAlerts folder, make sure it's copied to the new location
	- If you've referenced any other files for passwords or anything else, make sure they're copied as well.
<br><br>

5. In Task Scheduler, disable the existing VizAlerts scheduled task.

6. <font color='red'>**VizAlerts outage begins**</font>

7. Uninstall Python 2, and remove references to it from your environmental variables (again, this is optional, but should make things simpler--if you're a power user that knows Python inside and out, feel free to disregard)

8. Download and install Python 3 and [required modules](#install-python-required-modules)

9. If you didn't already publish the updated version of VizAlertsConfig, publish it now, ensuring that you embed the password when you publish it!

10. Rename folders
	- Rename the existing VizAlerts folder with something like "-old" at the end of it
	- Rename the new VizAlerts folder whatever the old one was called
<br><br>
11. Testing
	- Open a command prompt, navigate to the VizAlerts folder, and execute VizAlerts one time. Ensure it runs properly, and review the logs if there are any errors.
	- Test a single alert by adding a test\_alert comment to a viz, and then run it again in the command prompt, again ensuring that no errors are logged.
<br><br>
12. **Optional**: If you want to ensure that no alerts were skipped during the upgrade, copy the \ops\vizalerts.state file from the -old VizAlerts folder to the current one.

13. In Task Scheduler, enable the VizAlerts task

14. <font color='green'>**VizAlerts outage ends**</font>

15. Remove the -old VizAlerts folder and any backups you made, whenever you feel comfortable


Installation Prerequisites <a id="installation-prerequisites"></a>
=====================================

Tableau Server <a id="tableau-server"></a>
--------------

The Tableau Server instance that you wish to run VizAlerts against must
fulfill the following requirements:

-   Must be v8.3 or higher.

-   The [readonly
    user](https://onlinehelp.tableau.com/current/server/en-us/perf_collect_server_repo.htm)
    must be granted access on the Tableau Server repository.

-   [Subscriptions](http://onlinehelp.tableau.com/current/server/en-us/subscribe.htm)
    must be enabled.

-   The host you plan to run VizAlerts from must have its IP address
    listed as a [Trusted
    Host](http://onlinehelp.tableau.com/current/server/en-us/trusted_auth_trustIP.htm)

-   If it wasn’t already obvious, you need to be a System Administrator
    on Tableau Server to set all this up.

-   A Project configured with appropriate (usually very limited)
    permissions for the VizAlerts schedule viz. The VizAlerts schedule
    viz pulls information from the Tableau Server repository (using the
    readonly user) and can be configured in a number of ways so in
    general you’ll want to limit access to the VizAlerts
    system administrator(s).

Tableau Desktop <a id="tableau-desktop"></a>
---------------

To install VizAlerts you’ll need to use Tableau Desktop Professional
once to publish the VizAlerts scheduled trigger viz. Here are the
requirements:

-   A version of Tableau Desktop appropriate to the Tableau Server
    version you are installing to. See
    <http://kb.tableau.com/articles/knowledgebase/desktop-and-server-compatibility>.
    If you don’t have Tableau Desktop or access to someone’s computer
    where you could use it then you can download a trial vesion of
    Tableau Desktop Professional from <http://tableau.com>.

-   The machine that is running Tableau Desktop will need to have a
    PostgreSQL driver installed, if you need one you can download it
    from <http://www.tableau.com/support/drivers>.

-   You’ll also need to make sure you can access the Tableau Server from
    your Tableau Desktop machine, you may need to open one or more
    firewalls to enable connection to Tableau Server and/or the
    PostgreSQL repository.

-   The machine where Tableau Desktop is located will need access to the
    …\\VizAlerts\\config\\ScheduledTriggerView.twb in order to
    publish it.

Host Machine <a id="host-machine"></a>
------------

This is where VizAlerts will be run from, which means that this machine
must be continually up and running for VizAlerts to function. This can
be one of the Tableau Server hosts if desired, but it doesn’t have to
be. It must have the following properties:

-   Static IP address

-   Always running

-   Within same domain as Tableau Server

-   You must have administrative rights to it

-   Should **not** need to have much processing power as heavy work is
    offloaded to Tableau Server

VizAlerts has been built and tested on Windows, but it’s also been known
to run on Linux and Mac.

  
SMTP (Mail) Server <a id="smtp-mail-server"></a>
------------------

VizAlerts needs to point to a mail server to send email. This can simply
be the same server you used when you set up Tableau Server for
subscriptions. If your mail server is set up to support SSL encryption,
that is ideal, but it’s not required.

Installation <a id="installation"></a>
============

You’ve got everything you need, now let’s get this thing running!

Configure Tableau Server <a id="configure-tableau-server"></a>
------------------------

Making any of these configuration changes requires a restart of Tableau
Server, so if this is being done on a live / production server, make
sure to do this during a maintenance window.

### Trusted Tickets  <a id="trusted-tickets"></a>

VizAlerts uses [Trusted
Authentication](http://onlinehelp.tableau.com/current/server/en-us/trusted_auth.htm)
to impersonate users and obtain access to Tableau Server views in CSV
and PNG format. To grant it this access, run the following command at a
command prompt on the Primary host of Tableau Server:

&nbsp;&nbsp;&nbsp;&nbsp;<strong>For versions 10.5 and higher:</strong><br />
&nbsp;&nbsp;&nbsp;&nbsp;tsm configuration set -k wgserver.trusted\_hosts -v &lt;HOSTNAME OF VIZALERTS HOST&gt;

&nbsp;&nbsp;&nbsp;&nbsp;<strong>For pre-10.5 versions:</strong><br />
&nbsp;&nbsp;&nbsp;&nbsp;tabadmin set wgserver.trusted\_hosts &lt;HOSTNAME OF VIZALERTS HOST&gt;

### Repository Access <a id="repository-access"></a>

The Tableau Server repository database contains information VizAlerts
needs to function. Grant it access by enabling the [readonly
user](http://onlinehelp.tableau.com/current/server/en-us/adminview_postgres_access.htm):

&nbsp;&nbsp;&nbsp;&nbsp;<strong>For versions 10.5 and higher:</strong><br />
&nbsp;&nbsp;&nbsp;&nbsp;tsm data-access repository-access enable --repository-username readonly --repository-password &lt;YOUR PASSWORD&gt;

&nbsp;&nbsp;&nbsp;&nbsp;<strong>For pre-10.5 versions:</strong><br />
&nbsp;&nbsp;&nbsp;&nbsp;tabadmin dbpass --username readonly &lt;YOUR PASSWORD&gt;

### Restart <a id="restart"></a>

Once you have finished the above steps, you must save the configuration
and restart Tableau Server. When you’re ready to do this, run the
following commands in the command prompt:

&nbsp;&nbsp;&nbsp;&nbsp;<strong>For versions 10.5 and higher:</strong><br />
&nbsp;&nbsp;&nbsp;&nbsp;tsm pending-changes apply<br />
&nbsp;&nbsp;&nbsp;&nbsp;tsm restart

&nbsp;&nbsp;&nbsp;&nbsp;<strong>For pre-10.5 versions:</strong><br />
&nbsp;&nbsp;&nbsp;&nbsp;tabadmin configure<br />
&nbsp;&nbsp;&nbsp;&nbsp;tabadmin restart

### Custom Subscription Schedules <a id="custom-subscription-schedules"></a>

A key component that allows VizAlerts to work in the intuitive way that
it does is that users who wish to schedule an alert are able to
subscribe to them on *disabled* Subscriptions schedules. These are
schedules that you must create in Tableau Server, then manually disable
so that no subscriptions are ever delivered for them. Since the data for
who subscribed to what views *on* these specific schedules exists in the
PostgreSQL repository, VizAlerts can use this information to tell itself
when it is appropriate to test those views for an alert condition.

You can create as many schedules as you like, on whatever intervals you
like. The important bit behind the schedules is the **naming
convention** that you use, because this is how VizAlerts knows which
schedules to consider “alert” schedules that it needs to pay attention
to. I recommend naming them like this:

ѴizAlerts – \[frequency\]

**Copy and paste that** when you create your schedules—the first letter
is actually the Cyrillic letter Ѵ, which will cause your Alerts
schedules to be sorted at the bottom of the list when someone goes to
subscribe. This can help users avoid subscribing to them by mistake when
they only mean to set up a standard subscription:

<img src="./media/image1.png" width="232" height="297" />

Note that you must have at least one **enabled** Subscriptions schedule
for anyone to subscribe to a viz on Tableau Server, so if you have just
enabled Subscriptions for the first time, you’ll also need to create a
single non-VizAlert schedule that isn’t disabled.

Create your new schedules like so:

­­­­­­<img src="./media/image2.png" width="350" height="151" />

<img src="./media/image3.png" width="511" height="392" />

<img src="./media/image4.png" width="512" height="318" />


If you wish to allow your users to trigger their VizAlerts **when the workbook they are a part 
of refreshes its data extract(s)**, then create two additional Subscription schedules using the 
same method you did for the others, except that instead of:

ѴizAlerts – \[frequency\]

...they should be named:

- ѴizAlerts – **On Refresh Success**
- ѴizAlerts – **On Refresh Failure**

These will automatically be picked up by VizAlerts when someone subscribes to them, and their 
alert will be executed when the corresponding refresh activity occurs on their workbook.  

Open the VizAlertsConfig Workbook <a id="open-the-vizalertsconfig-workbook"></a>
---------------------------------

VizAlerts gets the list of alerts that users want to run, and when they
should run, from Tableau Server’s own PostgreSQL repository database.
The way it accesses that information is through a Tableau workbook that
you’ll publish to Tableau Server. For this step you’ll need the instance
of Tableau Desktop. To publish the viz, do the following:

1.  Open Tableau Desktop.

2.  Open the …\\VizAlerts\\config\\VizAlertsConfig.twb workbook.

3.  You’ll get a prompt about Custom SQL. You can review the SQL if you
    like, then press “Yes”.

4.  Depending on the Tableau Desktop version, you may get a prompt about
    the workbook being newer. Press OK to continue. You will get a login
    prompt that looks like this:  
      
    <img src="./media/image5.png" width="269" height="278" />

5.  Click Edit connection. The dialog will change to this dialog:  
    <img src="./media/image6.png" width="263" height="269" />

6.  Enter the following information:

    1.  Server: your Tableau Server domain name

    2.  Port: the port for the PostgreSQL repository, default is 8060

    3.  Database: leave as workgroup

    4.  Authentication: Change to Username and Password.

    5.  Username: leave as readonly

    6.  Password: enter the readonly password that you
        previously configured.

    7.  Require SSL: check this box if you are requiring SSL to connect
        to the Tableau repository.

7.  Click Sign In to sign in.

8.  The Tableau view that appears looks like this:

<img src="./media/image7.png" width="624" height="342" />

Configure the VizAlerts ScheduledTriggerView Viz <a id="configure-the-vizalerts-scheduledtriggerview-viz"></a>
------------------------------------------------

The scheduled trigger view will initially show as empty because we
haven’t yet set up any VizAlerts. The main reason that a Tableau
workbook is used to tell VizAlerts what to do, is that it gives the
Admin a lot of flexibility in deciding which alerts should be processed
and *how* they should be processed. There are a number of parameters and
calculated fields that can be used to create a high degree of
customization, which we’ll talk about in a second, but to keep things
simple, there are only two settings that you **must** edit to get
started:

<img src="./media/image7.png" width="624" height="342" />

Substitute your own email domain name where you see “yourdomain” in both
fields. For example:

-   .\*tableau\\.com (only allows email to be sent to tableau.com
    addresses)  
    and…

-   vizalerts@tableau\\.com (only allows “from” address to
    be “vizalerts@tableau.com”)

If you’re just trying to get things up and running, skip to [Publish the
VizAlertsConfig workbook](#_Publish_the_ScheduledTriggerViews)

Here’s a list of the major calculated fields and the (default)
parameters associated with them:


<table>
<tbody>
<tr>
<td width="149">
<p><strong>General Settings</strong></p>
</td>
<td width="186">&nbsp;</td>
<td width="303">&nbsp;</td>
</tr>
<tr>
<td width="149">
<p><strong>Calculated Field</strong></p>
</td>
<td width="186">
<p><strong>Parameter for default value</strong></p>
</td>
<td width="303">
<p><strong>Description</strong></p>
</td>
</tr>
<tr>
<td width="149">
<p>data_retrieval_tries</p>
</td>
<td width="186">
<p>default_data_retrieval_tries</p>
</td>
<td width="303">
<p>The number of times VizAlerts will attempt to retrieve data for a particular viz before notifying of the failure.</p>
</td>
</tr>
<tr>
<td width="149">
<p>notify_subscriber_on_failure</p>
</td>
<td width="186">
<p>default_notify_subscriber_on_failure</p>
</td>
<td width="303">
<p>When true (the default), the subscriber to the simple alert or the owner of the advanced alert is notified when there is a failure.</p>
</td>
</tr>
<tr>
<td width="149">
<p>timeout_s</p>
</td>
<td width="186">
<p>default_timeout_s</p>
</td>
<td width="303">
<p>The number of seconds allowed to download a visualization before Tableau will notify of a failure. This prevents overloading Tableau Server with visualizations that are too slow to render</p>
</td>
</tr>
<tr>
<td width="149">
<p>task_threads</p>
</td>
<td width="186">
<p>default_task_threads</p>
</td>
<td width="303">
<p>The number of threads used for to process Email and SMS notifications for a given VizAlert. For high-volume alerts sending hundreds of notifications, 
a count of 5 or more could be necessary for timely processing. Discuss with your IT team so that you don't end up beating your SMTP server up 
too much!</p>
</td>
</tr>
<tr>
<td width="149">
<p>viz_data_maxrows</p>
</td>
<td width="186">
<p>default_data_maxrows</p>
</td>
<td width="303">
<p>The maximum number of rows that VizAlerts will attempt to process from any VizAlert, when the viz data is downloaded. This applies to both Simple and Advanced alerts.</p>
</td>
</tr>
<tr>
<td width="149">
<p>viz_png_height</p>
</td>
<td width="186">&nbsp;</td>
<td width="303">
<p>Sets the default height of downloaded images for Simple Alerts as well as the VIZ_IMAGE() content reference.</p>
</td>
</tr>
<tr>
<td width="149">
<p>viz_png_width</p>
</td>
<td width="186">&nbsp;</td>
<td width="303">
<p>Sets the default width of downloaded images for Simple Alerts as well as the VIZ_IMAGE() content reference</p>
</td>
</tr>
</tbody>
</table>
<table>
<tbody>
<tr>
<td width="152">
<p><strong>Email Action Settings</strong></p>
</td>
<td width="186">&nbsp;</td>
<td width="301">&nbsp;</td>
</tr>
<tr>
<td width="152">
<p><strong>Calculated Field</strong></p>
</td>
<td width="186">
<p><strong>Parameter for default value</strong></p>
</td>
<td width="301">
<p><strong>Description</strong></p>
</td>
</tr>
<tr>
<td width="152">
<p>action_enabled_email</p>
</td>
<td width="186">
<p>default_action_enabled_email</p>
</td>
<td width="301">
<p>Denotes whether alerts can send emails. 1 (the default) if email actions are supported, otherwise 0</p>
</td>
</tr>
<tr>
<td width="152">
<p>allowed_from_address</p>
</td>
<td width="186">
<p>default_allowed_from_address</p>
</td>
<td width="301">
<p>The email address you wish all email alerts to be sent from. <strong>Note</strong> that for Advanced Alerts, this is used only if the author did not specify their own &ldquo;from&rdquo; address in their viz. <strong>This uses Regex notation (see below for details).</strong></p>
</td>
</tr>
<tr>
<td width="152">
<p>allowed_recipient_addresses</p>
</td>
<td width="186">
<p>default_allowed_recipient_addresses</p>
</td>
<td width="301">
<p>The set of domains and addresses that email alerts can be sent to. <strong>This uses Regex notation (see below for details).</strong></p>
</td>
</tr>
</tbody>
</table>
<table>
<tbody>
<tr>
<td width="149">
<p><strong>SMS Action Settings</strong></p>
</td>
<td width="186">&nbsp;</td>
<td width="303">&nbsp;</td>
</tr>
<tr>
<td width="149">
<p><strong>Calculated Field</strong></p>
</td>
<td width="186">
<p><strong>Parameter for default value</strong></p>
</td>
<td width="303">
<p><strong>Description</strong></p>
</td>
</tr>
<tr>
<td width="149">
<p>action_enabled_sms</p>
</td>
<td width="186">
<p>default_action_enabled_sms</p>
</td>
<td width="303">
<p>1 if SMS actions are supported, 0 (the default) if not.</p>
</td>
</tr>
<tr>
<td width="149">
<p>allowed_recipient_numbers</p>
</td>
<td width="186">
<p>default_allowed_recipient_numbers</p>
</td>
<td width="303">
<p>The set of allowed recipient phone numbers (or partial numbers). <strong>This uses Regex notation (see below for details)</strong>.</p>
</td>
</tr>
<tr>
<td width="149">
<p>from_number</p>
</td>
<td width="186">
<p>default_from_number</p>
</td>
<td width="303">
<p>The default number that SMS messages will originate from. This must be a number registered with Twilio that can do outbound SMS and be of the form +[country code][full phone number]</p>
</td>
</tr>
<tr>
<td width="149">
<p>phone_country_code</p>
</td>
<td width="186">
<p>default_phone_country_code</p>
</td>
<td width="303">
<p>The default country code to use when recipient phone numbers do not have a country code.</p>
</td>
</tr>
</tbody>
</table>
<table>
<tbody>
<tr>
<td width="149">
<p><strong>Schedule Settings</strong></p>
</td>
<td width="186">&nbsp;</td>
<td width="303">&nbsp;</td>
</tr>
<tr>
<td width="149">
<p><strong>Calculated Field</strong></p>
</td>
<td width="186">
<p><strong>Parameter for default value</strong></p>
</td>
<td width="303">
<p><strong>Description</strong></p>
</td>
</tr>
<tr>
<td width="149">
<p>is_valid_schedule</p>
</td>
<td width="186">
<p>schedule_name_filter</p>
</td>
<td width="303">
<p>Use to determine what Tableau Server subscription schedules will be checked for alerts.</p>
</td>
</tr>
</tbody>
</table>


### Calculated Fields <a id="calculated-fields"></a>

The calculated fields such as action\_enabled\_email allow us to create
formulas inside Tableau to give us more fine-grained control. For
example, we can allow a specific user to send email to any address,
rather than use the default setting like so:

<img src="./media/image8.png" width="338" height="89" />

Translated, this simply means that if the user called “mcoles-test”
wants to email anyone in the world with VizAlerts, they can, but
everyone else’s email recipients will still be restricted to the pattern
you set for the default\_allowed\_recipient\_addresses parameter (e.g.,
only your company’s email addresses).

If you want to define even *more* extensive policies, well, that’s why
it’s a Tableau viz! You can build out that calculation further using
other criteria, or even blend or join other data sources to the original
connection. It allows for almost unlimited flexibility.

### Regex Notation <a id="regex-notation"></a>

VizAlerts uses Regex Notation in setting the
**allowed\_recipient\_addresses**, **allowed\_recipient\_numbers**, and
**allowed\_from\_address** values for maximum flexibility. Each
individual email address a VizAlerts is attempting to send mail to
**must** match the pattern the administrator has defined in the
configuration viz. So this feature will allow you to define a set of
rules like these:

-   myfriendlyAOLuser@aol.com

-   mydomain.com

-   subdomain.someotherdomain.com

That would allow email to <jane@mydomain.com>,
<bob@subdomain.someotherdomain.com>, and <myfriendlyAOLuser@aol.com>
while denying email to addresses like <jerry@someotherdomain.com> and
<icanhazallyourdata@aol.com>.

A full explanation of what you can do with regex notation is beyond the
scope of this document, for more information about regex we suggest you
use <http://www.regular-expressions.info>. Here are the key elements:

-   .\* is the wildcard pattern to accept all characters.

-   If any of the following characters are used, they must have a \\
    preceding them to be accepted: \\^$.|?\*+()\[{  
      
    Example: If I want to accept all datablick.com addresses then the
    regex would be .\*datablick\\.com

-   Separate domains or email addresses are separated by the pipe |
    character.  
      
    Example: To accept all datablick.com and tableau.com addresses then
    the regex would be .\*datablick\\.com|.\*tableau\\.com

<span id="_Publish_the_ScheduledTriggerViews" class="anchor"><span id="_Toc474388503" class="anchor"></span></span>Publish the VizAlertsConfig workbook<a id="publish-the-scheduledtriggerviews-viz"></a>
--------------------------------------------------------------------------------------------------------------------------------------------------------

Here’s how to publish the workbook:

1.  Go to Server-&gt;Publish Workbook… If you haven’t already signed in
    to Tableau Server and need to, you’ll be prompted to sign in. Once
    you’ve signed in the Publish Workbook dialog will appear:  
      
    <img src="./media/image9.png" width="372" height="457" />

2.  Change the Project and/or Name of the viz if you want, if you change
    the Name you’ll need to record this to use in the next section.

3.  Change the Permissions if need be. **Only Administrators should have
    rights to alter this workbook.**

4.  Under Data Sources click Edit. The Manage Data Sources dialog will
    appear:  
      
    <img src="./media/image10.png" width="616" height="253" />

5.  Set the Publish Type to Embedded in workbook.

6.  Set the Authentication to Embedded password.

7.  Click outside of the dialog to close it.

8.  Click Publish. Tableau will now publish the viz and open it in your
    default web browser:  
    <img src="./media/image11.png" width="496" height="353" />

9.  Click on the view to verify that it works as expected.

10. You can now close the browser window and Tableau Desktop.

Optional: Install Python & Required Modules <a id="install-python-required-modules"></a>
-----------------------------------

If you wish to run VizAlerts as a Python script rather than a binary executable, you will need to follow these steps. Otherwise, you can skip this section. Note that the rest of the documentation assumes that you are running the binary executable, so whenever you see instructions to run vizalerts.exe, know that you'll need to use *python .\vizalerts.py* instead. Additionally, please note that while these instructions are specific to Windows, VizAlerts can also be run on Linux.

1.  On the host you want to run VizAlerts from, download and install Python 3.7 or higher. This can be done in multiple ways, but we suggest the MSI installer from: <https://www.python.org/downloads/>. While it's possible to run two separate versions of Python, VizAlerts is only compatible with 3.7 and above, and it can be very confusing to sort out issues when both versions are installed on your machine.

2.  It's recommended that you ensure that Python is added to your environmental PATH variable, when given that option in the installer.

3.  Install the necessary Python modules by running the following commands:

        pip install pyyaml
        pip install requests
        pip install requests\_ntlm  
        pip install pypdf2  
        pip install twilio  
        pip install phonenumberslite
 
        *  If your computer does not have access to the Internet, see
        [Appendix A](#_Appendix_A).<br><br>

    **Note**: Despite the requirement to install the last two
    modules, deciding whether to *enable* the Twilio SMS integration
    feature is up to you—either at the environment level, or at more
    flexible sub-levels. Enabling the Twilio SMS integration
    requires a Twilio account (free accounts are available).  
      
    Also, please also note that it’s possible to send SMS messages
    *without* Twilio, as short email messages to subscribers who’s
    mobile network providers have an email-to-SMS gateway available.
    For example, <xxxxxxxxxx@txt.att.net> works in the USA. See the
    SMS Actions section of the VizAlerts User Guide for
    more details.

Configure VizAlerts <a id="configure-vizalerts"></a>
-------------------

Now that Python is installed, we can configure VizAlerts. Unzip the
VizAlerts.zip file to a folder of your choosing. For the purposes of
this manual, we’ll assume the files were extracted to C:\\VizAlerts.

1.  The next task is to give VizAlerts all the information it needs to
    connect to our Tableau Server instance. Open the file
    C:\\VizAlerts\\config\\vizalerts.yaml in a text editor. Each of the
    configuration settings in that file are commented to explain what
    they do, but we’ll go over the most important ones here:

<table>
<tbody>
<tr>
<td width="174">
<p><strong>Email Settings</strong></p>
</td>
<td width="450">&nbsp;</td>
</tr>
<tr>
<td width="174">
<p>smtp.serv</p>
</td>
<td width="450">
<p>This is the name of your SMTP server.</p>
</td>
</tr>
<tr>
<td width="174">
<p>smtp.address.from</p>
</td>
<td width="450">
<p>The email address you wish all email alerts to be sent from. <strong>Note</strong> that for Advanced Alerts, this is used only if the author did not specify their own &ldquo;from&rdquo; address in their viz.</p>
</td>
</tr>
<tr>
<td width="174">
<p>smtp.address.to</p>
</td>
<td width="450">
<p>When an alert fails to run, failure details will be sent to this address along with the Subscriber, so it makes the most sense to use your own address or Admin distribution list here.</p>
</td>
</tr>
<tr>
<td width="174">
<p>smtp.ssl</p>
</td>
<td width="450">
<p>When true, VizAlerts will attempt to use SSL for email encryption (which your SMTP server must support). If you do not wish to use encryption, leave it &ldquo;false&rdquo;.</p>
</td>
</tr>
<tr>
<td width="174">
<p>smtp.user</p>
</td>
<td width="450">
<p>Username for the account used to connect to your SMTP server. If no authentication is need, leave it &ldquo;null&rdquo;</p>
</td>
</tr>
<tr>
<td width="174">
<p>smtp.password</p>
</td>
<td width="450">
<p>Password for the account used to connect to your SMTP server. If no authentication is need, leave it &ldquo;null&rdquo;. The password must be enclosed in single quotes.</p>
<p><br /> If desired, this value can be a valid path to a .txt file containing the password, e.g. 'c:\users\mcoles\password.txt', rather than the password itself.</p>
</td>
</tr>
</tbody>
</table>
<table>
<tbody>
<tr>
<td width="180">
<p><strong>Tableau Server Settings</strong></p>
</td>
<td width="444">&nbsp;</td>
</tr>
<tr>
<td width="180">
<p>server</p>
</td>
<td width="444">
<p>Name of the Tableau Server you wish to run this instance of VizAlerts against.</p>
</td>
</tr>
<tr>
<td width="180">
<p>server.version</p>
</td>
<td width="444">
<p>Major version of the Tableau Server you are running VizAlerts against (this must be 8, 9, or 10)</p>
</td>
</tr>
<tr>
<td width="180">
<p>server.user</p>
</td>
<td width="444">
<p>This is ANY user licensed in Tableau Server--it does not need to be an Admin, as it is only used in authenticating over HTTP.</p>
<p>&middot; If you are using Active Directory authentication, prepend the domain name in front of the username, e.g. &ldquo;tableau.com\mcoles&rdquo;</p>
<p>&middot; If you are using Local Authentication, simply supply the username, e.g., &ldquo;mcoles&rdquo;</p>
</td>
</tr>
<tr>
<td width="180">
<p>server.user.domain</p>
</td>
<td width="444">
<p>The Active Directory domain for the server.user account, leave as null if using local authentication.</p>
</td>
</tr>
<tr>
<td width="180">
<p>server.ssl</p>
</td>
<td width="444">
<p>When set to true, use SSL to connect to Tableau Server (recommended if you have enabled SSL).</p>
</td>
</tr>
<tr>
<td width="180">
<p>vizalerts.source.viz</p>
</td>
<td width="444">
<p>This identifies the VizAlerts scheduled alert viz. it must be of the form workbook/viewname. The publishing information for this viz will be used</p>
</td>
</tr>
<tr>
<td width="180">
<p>vizalerts.source.site</p>
</td>
<td width="444">
<p>Identifies the Tableau Server site for the vizalerts.source.viz.</p>
</td>
</tr>
</tbody>
</table>
<table>
<tbody>
<tr>
<td width="180">
<p><strong>Security Settings</strong></p>
</td>
<td width="444">&nbsp;</td>
</tr>
<tr>
<td width="180">
<p>server.ssl</p>
</td>
<td width="444">
<p>When set to true, use SSL to connect to Tableau Server (recommended if you have enabled SSL).</p>
</td>
</tr>
<tr>
<td width="180">
<p>server.certcheck</p>
</td>
<td width="444">
<p>If using SSL then validate the certificate If set to true then you must also specify the server.certfile.</p>
</td>
</tr>
<tr>
<td width="180">
<p>server.certfile</p>
</td>
<td width="444">
<p>Full path to the set of trusted CA certificates in .pem format</p>
</td>
</tr>
</tbody>
</table>
<table>
<tbody>
<tr>
<td width="180">
<p><strong>SMS Action Settings</strong></p>
</td>
<td width="444">&nbsp;</td>
</tr>
<tr>
<td width="180">
<p>smsaction.enable</p>
</td>
<td width="444">
<p>Set to True to enable SMS Advanced Alerts to be sent. If set to False then all other smsaction fields are ignored. (Default False)</p>
</td>
</tr>
<tr>
<td width="180">
<p>smsaction.provider</p>
</td>
<td width="444">
<p>The only supported provider at this time is twilio.</p>
</td>
</tr>
<tr>
<td width="180">
<p>smsaction.account_id</p>
</td>
<td width="444">
<p>The account ID at the SMS provider.</p>
</td>
</tr>
<tr>
<td width="180">
<p>smsaction.auth_token</p>
</td>
<td width="444">
<p>Authorization token provided by the SMS provider.</p>
</td>
</tr>
</tbody>
</table>

Testing <a id="testing"></a>
-------

Whew! All that was lots of fun, but let’s get to the good stuff and test
this thing to see if we did everything right. We’ve got a few tests to
run to validate that everything is working, starting out from simple to
more complicated:

### Can VizAlerts Connect? Test <a id="can-vizalerts-connect-test"></a>

Run the following from a command prompt on the Windows host you set
VizAlerts up on. By default, VizAlerts will expect you are running it
within the context of the directory you created it in, so change to that
directory first, then run the script:

cd C:\\VizAlerts

C:\\VizAlerts\\vizalerts.exe

It should have successfully generated a Trusted Ticket, queried the
PostgreSQL database in Tableau Server, then realized there was nothing
to do and quit without error. If it didn’t, please see the [Common
Errors](#common-errors) section.

### Simple Alert Test <a id="simple-alert-test"></a>

Now for a more extensive test on a Simple Alert. Subscribe to any
Tableau Server View on a VizAlerts schedule that you set up (pick a view
that renders in less than 10 seconds or so). We recommend subscribing on
a VizAlerts schedule that runs every 15 minutes for this test, even if
you just remove it afterward. After you subscribe, run the command
again:

C:\\VizAlerts\\vizalerts.exe

Now, wait 15 minutes, then run the same command again. If data is
present in the viz, you should receive an email! If not, you shouldn’t.
Simple as that!

### Put VizAlerts Through Its Paces Test <a id="put-vizalerts-through-its-paces-test"></a>

For this test you are going to use the same Tableau workbook that the
VizAlerts contributors use to verify VizAlerts is working after we’ve
changed the code. Note that this workbook only works with Tableau
version 9.0 and up.

1.  In Tableau Desktop open \[VizAlerts
    Install Folder\]\\VizAlerts\\demo\\VizAlertsDemo.twb.

2.  Go to the Advanced Alerts view and set the VizAlerts From Email and
    VizAlerts To Email parameters to your test email address:  
    <img src="./media/image12.png" width="540" height="277" />

3.  Choose Server-&gt;Publish workbook… to start the publishing process.
    Use the default settings, which will include the External Files
    option:  
      
    <img src="./media/image13.png" width="508" height="553" />  
      
    We suggest you publish the workbook in a place where other users who
    will be configuring Advanced Alerts (see the User Guide) can see
    the workbook.

4.  Click through the warning(s) about including external files and
    publish the workbook.

5.  If you’re on Tableau v10 or higher you can skip this step. When the
    confirmation window appears, click Open in browser window to open
    the VizAlertsDemo workbook on Tableau Server.  
    <img src="./media/image14.png" width="298" height="206" />

6.  Login to Tableau Server if you need to and navigate to the Advanced
    Alerts Demo worksheet.

7.  Scroll down in the worksheet and enter a comment with the
    text “test\_alert”.

8.  After the comment has been posted, go back to your Windows command
    prompt and enter:  
      
    C:\\VizAlerts\\vizalerts.exe
      
    If the script runs and exits the first time without processing
    anything, run it again. (Tableau can take a moment to update the
    data with the “test\_alert” comment that acts as a trigger).
    VizAlerts will now generate 30+ emails with a variety of tests
    demonstrating the VizAlerts features. Read through the emails to
    understand what is expected of each. If you get any error messages
    then check the Common Errors section below as well as the FAQ in the
    User Guide.

### Optional: Send Yourself Some SMS Messages Test <a id="optional-send-yourself-some-sms-messages-test"></a>

If you have set up the integration with Twilio now’s the time to see if
it works, you’ll be using the same testing workbook from the prior demo.
that the VizAlerts contributors use. Note that this workbook only works
with Tableau version 9.0 and up.

1.  In Tableau Desktop open \[VizAlerts
    Install Folder\]\\VizAlerts\\demo\\VizAlertsDemo.twb.

2.  Go to the SMS Success Tests view and set the VizAlerts To SMS
    parameter to your test SMS phone number:  
      
    <img src="./media/image15.png" width="508" height="246" />

3.  Choose Server-&gt;Publish workbook… to start the publishing process.
    Use the default settings, which will include the External Files
    option:  
      
    <img src="./media/image16.png" width="445" height="493" />

4.  Click through the warning(s) about including external files and
    publish the workbook.

5.  If you’re on Tableau v10 you can skip this step. When the
    confirmation window appears, click Open in browser window to open
    the VizAlertsDemo workbook on Tableau Server.

6.  Login to Tableau Server if you need to and navigate to the SMS
    Success Tests worksheet.

7.  Scroll down in the worksheet and enter a comment with the
    text “test\_alert”.

8.  After the comment has been posted, go back to your Windows command
    prompt and enter:  
      
    C:\\VizAlerts\\vizalerts.exe
      
    If the script runs and exits the first time without processing
    anything, run it again. (Tableau can take a moment to update the
    data with the “test\_alert” comment that acts as a trigger).
    VizAlerts will now generate 10 SMS message with a variety of tests
    demonstrating the VizAlerts features. Read through the messages to
    understand what is expected of each. If you get any error messages
    (which will be delivered by email) then check the Common Errors
    section below as well as the FAQ in the User Guide.

Final Steps <a id="final-steps"></a>
-----------

### Set up a Scheduled Task <a id="set-up-a-scheduled-task"></a>

The last step, now that everything is working as expected, is to
automate this so that VizAlerts can run regularly when it is supposed
to. To do this, we need to set up a Scheduled Task on the Windows host
that VizAlerts runs from, which will run this for us on a regular basis.

First, let’s create a new Task:

<img src="./media/image17.png" width="634" height="385" />

Fill in the name and description. Make sure it will run whether the user
is logged in or not. The task should be set up to run under a service
account rather than a personal one, if possible. This account must have
full control permissions on the VizAlerts files, and if you specified
text files instead of passwords in the vizalerts.yaml config file, the
account will need rights to read those files.

<img src="./media/image18.png" width="444" height="336" />

Set up the Trigger (when will it run?). We strongly recommend running
this every **1 minute**, as this will keep alerts executing on time, and
the vast majority of executions will be quick checks that don’t actually
do any work:

<img src="./media/image19.png" width="502" height="384" />

Set the Action on the Task (what will it do?)

<img src="./media/image20.png" width="423" height="238" />

And save the task! You can now test out the task by subscribing the
VizAlertsDemo/AdvancedAlertsDemo view to a subscription and look for an
email.

### Starter Workbook <a id="starter-workbook"></a>

Last, but not least, publish the \[VizAlerts install
folder\]\\demo\\VizAlertsStarter.tbwx workbook to Tableau Tableau Server,
and grant permissions to anyone you wish to have an easier way to create
Advanced Alerts. This workbook gives users a shortcut to creating them, 
with all the necessary action fields and examples on how to use them.

### 

FAQ <a id="faq"></a>
===

-   **How many alerts can be run at once?**  
    
	Alerts are processed in parallel, according to the number of
    threads you set in the config\\vizalerts.yaml file. They are checked
    according to the Schedule they are associated with, in order of the
    “priority” field in the config workbook. Here’s an example: Alerts
    scheduled for 6:00AM will begin being checked at 6:00AM. If you’re
    running two threads and have three alerts to process then the two
    alerts with the lowest priority settings will be checked first. If
    those two alerts take five minutes each to process then the third
    alert wouldn’t be start to be processed until 6:05am. So two things
    to pay attention to are how long it takes alerts to process (which
    you can see in the VizAlerts logs), the timeout settings (since
    long-running alerts could be caused by a large volume of actions
    and/or views that are slow to render), and the number of alerts that
    are simultaneously scheduled.

	When an alert is triggered, it begins sending emails / SMS notifications.
	These tasks are *also* processed in parallel, according to the number 
	defined in the "task_threads" field in the VizAlertsConfig workbook.  

-   **Does VizAlerts use a database to log information about what it has
    done?**

	No, not in its current state, though this is the next logical
    progression for it. Currently it logs information into text
    files only.

Common Errors <a id="common-errors"></a>
=============================================================================================================

This section mostly focuses on errors found at installation time. Many
other common error situations are covered in the troubleshooting section
of the VizAlerts User Guide.

-   **Failed with unknown protocol**

    -   This likely means that you’ve enabled SSL in the vizalerts.yml,
        but haven’t set Tableau Server up for it. See [this
        portion](http://onlinehelp.tableau.com/current/server/en-us/ssl_config.htm)
        of the online help on how to do so.

-   **Parsing or yaml scanner errors**

    -   Generally this means that some bad character or formatting issue
        was introduced to the vizalerts.yml file (typically a tab
        character—replace them with spaces!). We recommend using this
        [online YAML validator](http://codebeautify.org/yaml-validator)
        to determine where the problem is (make sure to remove your
        passwords first!).

-   **Invalid regular expression found**

    -   If VizAlerts won’t start, and sends 
    -   you an email with this
        message, it means one of two things:

        -   You live in an area where the default delimiter is another
            character besides commas, such as semicolon. To fix this,
            just open config\\vizalerts.yaml, and change the
            data.coldelimter to ‘;’ instead of ‘,’.

        -   One of the regular expressions in your VizAlertsConfig.twb
            fields is not correct. Test it out at <http://regexr.com/>
            to make sure it’s behaving.

-   **HTTP 406 error**

    -   You might see the following error: export\_view - HTTP error
        getting vizdata from url
        [http://\[your](http://[your) server\]/views/VizAlerts/AlertList?&amp;:format=csv&amp;:refresh=y.
        Code: 406 Reason: Not Acceptable  
          
        This would be due to not embedding the password for the readonly
        user into the VizAlertsConfig workbook.

    -   If you see a 406 on a standard VizAlert, it generally means that
        Tableau Server could not export the view for some reason. This
        could be due to a variety of causes:

        -   The subscriber does not have access to the view

        -   The view could not connect to its data source for some
            reason

        -   A Tableau Server process crashed when it tried to load the
            view

        -   The view had an invalid calculation and couldn’t be loaded

-   **Trusted ticket failure**

    -   Check to ensure your trusted tickets were [configured
        properly](http://onlinehelp.tableau.com/current/server/en-us/trusted_auth_trustIP.htm).
        If things are still not working, try [this
        article](http://kb.tableau.com/articles/knowledgebase/testing-trusted-authentication)
        to test them further.

    -   A “-1” result could be due to several possible issues. Please
        see [this
        article](http://onlinehelp.tableau.com/current/server/en-us/trusted_auth_trouble_1return.htm)
        if you’re seeing this error.

-   **Unable to export … as CSV**

    -   This means that the attempt to export the view data for an alert
        to a CSV file failed, either because of internal errors, or
        because it took longer than the timeout you’ve set in the
        config file. If the view can be rendered successfully in your
        browser, it may simply be taking too long. Increasing the
        timeout settings may help with this, but a better solution is to
        try and optimize the viz to render more quickly. By default, the
        settings use stricter timeouts on more frequently-run alerts, as
        it’s assumed they’ll have more opportunities to be retried.

-   **Exporting Views - Unable to write to folder**

    -   The Tableau Server “run as” user must have read/write
        permissions on any folders used for exporting views.

Getting VizAlerts Help  <a id="getting-vizalerts-help"></a>
======================

First of all, check with any local admins and any local documentation
that might exist. After that, the center for all things VizAlerts is the
VizAlerts Group on the Tableau Community
<https://community.tableau.com/vizalerts>

Contributing to VizAlerts <a id="contributing-to-vizalerts"></a>
=======================================================================================================================

VizAlerts is an open source project distributed under the MIT License.
If you’d like to contribute ideas or code to VizAlerts, please visit the
VizAlerts GitHub site at <https://github.com/tableau/VizAlerts>.

Appendix A <a id="appendix-a"></a>
======================================================================================================

Installing Python modules with no Internet access <a id="installing-python-modules-with-no-internet-access"></a>
-------------------------------------------------

Setting VizAlerts up on a secure machine that isn’t connected to the
Internet can be done by following these instructions. It essentially
requires that you download the files that you need from a machine that
is connected to the Internet, then copy them over to the secured machine
you’ll be running VizAlerts from.

1.  First, download the Python [install file](#_Install_Python_&).
    Install it on the Internet-connected machine you’re using to
    download files, then copy it to your VizAlerts host and install
    Python there too. On both machines, you may wish to follow Step 2 as
    well, and add the Python executables to your PATH
    environment variable.

2.  From your Internet-connected machine, run the following commands to
    download all of the required Python modules (feel free to adjust the
    path they download to). These function as basically offline package
    repositories:

    *pip install --download c:\\mypythonpackages pyyaml*

    *pip install --download c:\\mypythonpackages requests*

    *pip install --download c:\\mypythonpackages requests\_ntlm*

    *pip install --download c:\\mypythonpackages pypdf2*

    *pip install --download c:\\mypythonpackages phonenumberslite*

    *pip install --download c:\\mypythonpackages twilio*


3.  Copy the entire folder to your offline machine (I'm assuming here
    that it's copied to the same path).

4.  On your offline machine, install the package from the newly copied
    folder:

    *pip install --no-index --find-links file:c:\\mypythonpackages
    pyyaml*

    *pip install --no-index --find-links file:c:\\mypythonpackages
    requests*

    *pip install --no-index --find-links file:c:\\mypythonpackages
    requests\_ntlm*

    *pip install --no-index --find-links file:c:\\mypythonpackages
    pypdf2 *

    *pip install --no-index --find-links file:c:\\mypythonpackages
    phonenumberslite*

    *pip install --no-index --find-links file:c:\\mypythonpackages
    twilio  

5.  Check for errors in the output. If there are none, you’ve
    successfully got Python and all the modules installed!

