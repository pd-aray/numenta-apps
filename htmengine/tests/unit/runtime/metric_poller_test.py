#!/usr/bin/env python

"""Tests the metric listener."""

import socket
import unittest
import mock
from mock import MagicMock, Mock, patch
from htmengine.runtime import metric_poller


class MetricPollerTest(unittest.TestCase):
  def test__reformat_graphite_response__returns_proper_format(self):
    response = {"target": "target1", "datapoints": [[1244, 1459966380], [982, 1459966440]]}
    expected_response = ["target1 1244 1459966380", "target1 982 1459966440"]

    actual_response = metric_poller.reformat_graphite_response(response)

    self.assertEqual(expected_response, actual_response)


if __name__ == "__main__":
  unittest.main()
