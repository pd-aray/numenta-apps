#!/bin/bash

cd /home/numenta/apps \
  && ./install-htm-it.sh /opt/numenta/htm.it \
  && cd /home/numenta/apps/htm.it \
  && mkdir logs \
  && python setup.py init
