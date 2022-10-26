## What is it?
[![Community Supported](https://img.shields.io/badge/Support%20Level-Community%20Supported-457387.svg)](https://www.tableau.com/support-levels-it-and-developer-tools)

VizAlerts is a data-driven automation platform for Tableau Server. It allows any user to author dashboards that perform various actions based on any criteria you can define in your viz.

Actions currently supported are:

* Send email to any audience, with flexible control over who is sent what, and the ability to embed or attach images of your visualizations as PNGs or PDFs
* Send SMS messages to any audience using the Twilio service
* (Future) Export viz data and/or images to a file share

Once VizAlerts is installed and running, all of the work to build and manage your alerts happens in Tableau--no scripting required, and no separate interface necessary.

## Got any documentation?

Do we ever! There are two files included in the \docs folder, [install_guide.md](docs/install_guide.md) and [user_guide.md](docs/user_guide.md), intended for Tableau Server administrators and for alert authors, respectively. They're the best way to learn about what VizAlerts can do.

If you're an impatient Millennial like me, here's a [video](https://youtu.be/NQW3w64cXiU) that skims the very basics.

## How do I set it up?

Please see the [Install Guide](docs/install_guide.md) for installation instructions. Only the Tableau Server administrator needs to set it up. Once working, any user on Tableau Server who can publish may use VizAlerts.

## What versions of Tableau are supported?

Tableau Server version 8.2.5 and higher is required (ideally version 9--if you're using version 8, some things won't work as well). Tableau Online is not currently supported, though we are looking at ways we might be able to achieve that.

## How is it licensed?

Please see the LICENSE file in the root path for details.

## Is VizAlerts supported?

VizAlerts is supported by the community. While Tableau's Professional Services team may be engaged to assist with the deployment and usage of this tool, VizAlerts is not officially supported by Tableau Software: It is a community-built and community-supported tool.

For general questions or issues, please bring them to the [VizAlerts Group](http://community.tableau.com/vizalerts) created on the Tableau Community site.

Bugs discovered, and feature aspirations will be tracked via GitHub's [issue tracker](https://github.com/tableau/VizAlerts/issues).

## How can I contribute?

If you're interested in contributing to VizAlerts, please [email Matt](http://tinymailto.com/a65f) about what you're interested in doing. We've found it's the easiest way for us to coordinate planned changes amongst ourselves.

## What's the longer-term vision for this tool?

Initially, VizAlerts was born out of a hackathon we held at Tableau, and it was conceived of as a proof-of-concept of how data analyzed through Tableau could be used as a programming language of sorts to drive automation of various tasks. The most critical and simplest task to tackle first was email automation, so that's what has been primarily focused on to date. But more actions have been added recently, and we're interested in finding other ways that VizAlerts can be used to drive automation, such as exporting data to file shares, making changes to other content on Tableau Server, and generally hooking into APIs exposed by various other third-party services.
