#!/usr/bin/env python

import datetime
import logging
import os
import time
import signal
import urllib2
import base64
import json
from htmengine import raiseExceptionOnMissingRequiredApplicationConfigPath
from htmengine.htmengine_logging import getExtendedLogger
from htmengine.model_swapper.model_swapper_interface import (MessageBusConnector)
from htmengine.runtime.metric_listener import Protocol, parsePlaintext
from nta.utils.config import Config
from nta.utils.logging_support_raw import LoggingSupport
from nta.utils.message_bus_connector import MessageQueueNotFound


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
        data = MetricPoller.reformat_graphite_response(response)
        if len(data) > 0:
            MetricPoller.publish_metrics(data)

    @staticmethod
    def publish_metrics(data):
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

    @staticmethod
    def reformat_graphite_response(graphite_response):
        response = json.load(graphite_response)[0]
        key = response["target"]
        datapoints = response["datapoints"]

        data = []
        for datapoint in datapoints:
            value = datapoint[0]
            timestamp = datapoint[1]
            if value is not None:
                data.append("%s %s %s" % (key, value, timestamp))
        return data


@raiseExceptionOnMissingRequiredApplicationConfigPath
def run_metric_poller():
    global gQueueName
    global gProfiling

    # Parse config
    config = Config("application.conf", os.environ["APPLICATION_CONFIG_PATH"])
    gQueueName = config.get("metric_poller", "queue_name")
    gProfiling = (config.getboolean("debugging", "profiling") or LOGGER.isEnabledFor(logging.DEBUG))
    LOGGER.info("run_metric_poller(graphite_url=%s, graphite_username=%s, graphite_password=*****, poll_frequency=%s)" %
                (graphite_url, graphite_username, poll_frequency))
    graphite_url = config.get("metric_poller", "graphite_url")
    graphite_username = config.get("metric_poller", "graphite_username")
    graphite_password = config.get("metric_poller", "graphite_password")
    poll_frequency = config.getfloat("metric_poller", "poll_frequency")

    # Begin polling
    metric_poller = MetricPoller(graphite_url,
                                 graphite_username,
                                 graphite_password,
                                 poll_frequency)
    metric_poller.poll()


if __name__ == "__main__":
    LoggingSupport.initService()
    run_metric_poller()
