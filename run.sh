#!/bin/bash

cd /home/numenta/apps \
  && ./install-htm-it.sh /opt/numenta/htm.it \
  && cd /home/numenta/apps/htm.it \
  && mkdir -p logs \
  && python setup.py init
