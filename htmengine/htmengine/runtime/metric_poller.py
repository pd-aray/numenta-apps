#!/usr/bin/env python

import datetime
import logging
import os
import time
import signal
import urllib2
import base64
import json
import sys
from htmengine import raiseExceptionOnMissingRequiredApplicationConfigPath
from htmengine.htmengine_logging import getExtendedLogger
from htmengine.model_swapper.model_swapper_interface import (MessageBusConnector)
from htmengine.runtime.metric_listener import Protocol, parsePlaintext
from nta.utils.config import Config
from nta.utils.logging_support_raw import LoggingSupport
from nta.utils.message_bus_connector import MessageQueueNotFound


# Globals
LOGGER = getExtendedLogger(__name__)
CURRENT_MODULE = sys.modules[__name__]
gQueueName = None
gProfiling = False


class MetricPoller:
    stop = False
    graphite_url = None
    graphite_username = None
    graphite_password = None
    graphite_keys = None
    poll_frequency = None
    timestamp_format = "%Y%m%d_%H:%M:%S"

    def __init__(self,
                 graphite_url,
                 graphite_username,
                 graphite_password,
                 graphite_keys,
                 poll_frequency):
        signal.signal(signal.SIGINT, self.exit)
        signal.signal(signal.SIGTERM, self.exit)

        self.stop = False
        self.graphite_url = graphite_url
        self.graphite_username = graphite_username
        self.graphite_password = graphite_password
        self.graphite_keys = graphite_keys
        self.poll_frequency = poll_frequency

    def exit(self, signum, frame):
        self.stop = True

    def poll(self):
        while not self.stop:
            time.sleep(self.poll_frequency)
            response = self.request_graphite_metrics()
            response = CURRENT_MODULE.reformat_graphite_reponse(response)
            CURRENT_MODULE.publish_metrics(response)

    def request_graphite_metrics(self):
        for graphite_key in self.graphite_keys:
            graphite_creds = base64.encodestring('%s:%s' % (self.graphite_username, self.graphite_password))[:-1]
            graphite_from = '-%ds' % int(self.poll_frequency)
            graphite_to = datetime.datetime.now().strftime(self.timestamp_format)

            url = "%s/render/?format=json&from=%s&to=%s&target=%s" % (self.graphite_url,
                                                                      graphite_from,
                                                                      graphite_to,
                                                                      graphite_key)

            LOGGER.info("Requesting Graphite data from %s" % url)
            request = urllib2.Request(url)
            request.add_header('Authorization', 'Basic %s' % graphite_creds)

            response = urllib2.urlopen(request)
            LOGGER.info("Received response: %r" % response)

            response = json.load(response)
            if response:
                response = response[0]
            return response


def reformat_graphite_response(response):
    data = []
    if not response:
        return data

    print "Loaded JSON response: %r" % response
    key = response["target"]
    datapoints = response["datapoints"]

    for datapoint in datapoints:
        value = datapoint[0]
        timestamp = datapoint[1]
        if value is not None:
            data.append("%s %s %s" % (key, value, timestamp))
    return data


def publish_metrics(data):
    if not data:
        return False

    LOGGER.info("Parsed data: %r" % data)

    if gProfiling:
        start_time = time.time()

    with MessageBusConnector() as messageBus:
        message = json.dumps({"protocol": Protocol.PLAIN, "data": data})
        try:
            LOGGER.info("Publishing message: %s", message)
            messageBus.publish(mqName=gQueueName, body=message, persistent=True)
        except MessageQueueNotFound:
            LOGGER.info("Creating message queue that doesn't exist: %s", gQueueName)
            messageBus.createMessageQueue(mqName=gQueueName, durable=True)
            LOGGER.info("Re-publishing message: %s", message)
            messageBus.publish(mqName=gQueueName, body=message, persistent=True)

        LOGGER.info("forwarded batchLen=%d", len(data))

        if gProfiling and data:
            now = time.time()
            try:
                for sample in data:
                    metric_name, _value, timestamp = parsePlaintext(sample)
                    LOGGER.info(
                        "{TAG:CUSLSR.FW.DONE} metricName=%s; timestamp=%s; duration=%.4fs",
                        metric_name, timestamp.isoformat() + "Z", now - start_time)
            except Exception:
                LOGGER.exception("Profiling failed for sample=%r in data=[%r..%r]",
                                 sample, data[0], data[-1])
    return True


@raiseExceptionOnMissingRequiredApplicationConfigPath
def run_metric_poller():
    global gQueueName
    global gProfiling

    # Parse config
    config = Config("application.conf", os.environ["APPLICATION_CONFIG_PATH"])
    gQueueName = config.get("metric_poller", "queue_name")
    gProfiling = (config.getboolean("debugging", "profiling") or LOGGER.isEnabledFor(logging.DEBUG))
    enabled = config.getboolean("metric_poller", "enabled")
    graphite_url = config.get("metric_poller", "graphite_url")
    graphite_username = config.get("metric_poller", "graphite_username")
    graphite_password = config.get("metric_poller", "graphite_password")
    graphite_keys = config.getlist("metric_poller", "graphite_keys")
    poll_frequency = config.getfloat("metric_poller", "poll_frequency")
    LOGGER.info("run_metric_poller(enabled=%r, graphite_url=%s, graphite_username=%s, graphite_password=*****, graphite_keys=%s, poll_frequency=%s)" %
                (enabled, graphite_url, graphite_username, graphite_keys, poll_frequency))

    # Begin polling
    if enabled:
        metric_poller = MetricPoller(graphite_url,
                                     graphite_username,
                                     graphite_password,
                                     graphite_keys,
                                     poll_frequency)
        metric_poller.poll()


if __name__ == "__main__":
    LoggingSupport.initService()
    run_metric_poller()
