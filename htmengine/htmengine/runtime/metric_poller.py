#!/usr/bin/env python

import datetime
import errno
import itertools
import json
import logging
import optparse
import os
import socket
import SocketServer
import threading
import time

from nta.utils.config import Config
from nta.utils.logging_support_raw import LoggingSupport
from nta.utils import threading_utils

from htmengine import raiseExceptionOnMissingRequiredApplicationConfigPath
from htmengine.htmengine_logging import getExtendedLogger
from htmengine.model_swapper.model_swapper_interface import (
    MessageBusConnector)
from nta.utils.message_bus_connector import MessageQueueNotFound

import signal
import urllib2
import base64


# Globals
LOGGER = getExtendedLogger(__name__)
gQueueName = None
gProfiling = False


class MetricPoller:
    stop = False
    graphite_url = None
    graphite_username = None
    graphite_password = None
    poll_frequency = None
    timestamp_format = "%Y%m%d_%H:%M:%S"

    def __init__(self, graphite_url, graphite_username, graphite_password, poll_frequency):
        signal.signal(signal.SIGINT, self.exit)
        signal.signal(signal.SIGTERM, self.exit)

        self.stop = False
        self.graphite_url = graphite_url
        self.graphite_username = graphite_username
        self.graphite_password = graphite_password
        self.poll_frequency = poll_frequency

    def exit(self, signum, frame):
        self.stop = True

    def poll(self):
        while not self.stop:
            time.sleep(self.poll_frequency)
            self.request_graphite_metrics()

    def request_graphite_metrics(self):
        graphite_creds = base64.encodestring('%s:%s' % (self.graphite_username, self.graphite_password))[:-1]
        graphite_from = '-%ds' % int(self.poll_frequency)
        graphite_to = datetime.datetime.now().strftime(self.timestamp_format)
        graphite_key = "stats.timers.automation.time_in_queue.sf-dallas-primary.all.percentile.95"

        url = "%s/render/?format=json&from=%s&to=%s&target=%s" % (self.graphite_url,
                                                                  graphite_from,
                                                                  graphite_to,
                                                                  graphite_key)

        request = urllib2.Request(url)
        request.add_header('Authorization', 'Basic %s' % graphite_creds)

        response = urllib2.urlopen(request)

        LOGGER.info("Request (%s): %s" % (self.graphite_url, url))
        LOGGER.info("Response: %s" % (response.read()))


@raiseExceptionOnMissingRequiredApplicationConfigPath
def run_metric_poller(graphite_url=None,
                      graphite_username=None,
                      graphite_password=None,
                      poll_frequency=None):
    global gQueueName
    global gProfiling

    # Parse config
    config = Config("application.conf", os.environ["APPLICATION_CONFIG_PATH"])
    gQueueName = config.get("metric_poller", "queue_name")
    gProfiling = (config.getboolean("debugging", "profiling") or LOGGER.isEnabledFor(logging.DEBUG))
    graphite_url = graphite_url or config.get("metric_poller", "graphite_url")
    graphite_username = graphite_username or config.get("metric_poller", "graphite_username")
    graphite_password = graphite_password or config.get("metric_poller", "graphite_password")
    poll_frequency = poll_frequency or config.getfloat("metric_poller", "poll_frequency")
    LOGGER.info("run_metric_poller(graphite_url=%s, graphite_username=%s, graphite_password=*****, poll_frequency=%s)" %
                (graphite_url, graphite_username, poll_frequency))

    # Begin polling
    metric_poller = MetricPoller(graphite_url,
                                 graphite_username,
                                 graphite_password,
                                 poll_frequency)
    metric_poller.poll()


if __name__ == "__main__":
    LoggingSupport.initService()
    run_metric_poller()
