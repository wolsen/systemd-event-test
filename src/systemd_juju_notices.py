#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Sends events to charms based on systemd events.

This works by configuring systemd post start exec scripts to record events
which occur in the system and then monitors for these events to send events
back into the Juju unit which is configured to watch.

A rough outline with how this works is that a systemd override is installed
for the service specified which adds a ExecStartPost hook which will record
which service has started and which juju unit needs to be notified with this
event. A background task is run that will evaluate the services that have
started and will invoke the juju handler for this event.
"""

import logging
import os
import time
import json
import subprocess
from pathlib import Path

# NOTE(wolsen) This probably needs to change.
NOTICE_DIR = "/tmp/juju/systemd-notices/"
LOG_FILE = "/var/log/juju/systemd-notices.log"


logger = logging.getLogger(__name__)


def send_event(unit: str, event: str) -> True:
    """Sends the event to Juju.

    :param unit: the name of the unit
    :param event: the event to send to juju
    :return: True if the event was sent, False otherwise.
    """
    cmd = [
        "/usr/bin/juju-exec",
        unit,
        f"hooks/{event}"
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError:
        logger.exception("Failed to send event:")
        return False


def process_notices():
    """Collects events that need to raised."""
    paths = sorted(Path(NOTICE_DIR).iterdir(), key=os.path.getmtime)
    for notice in paths:
        logger.debug(f"Processing notice {notice}")
        with open(notice, 'r') as f:
            info = json.load(f)

        # Turn unit-name-0 into unit-name/0
        unit = "/".join(info["unit"].rsplit("-", 1))
        service_name = str(notice.name)[:-len(notice.suffix)]
        # remove the . from the suffix (event name)
        event = f"service-{service_name}-{notice.suffix[1:]}"

        # If the event is successfully sent, unlink the file so
        # the event does not get processed again.
        if send_event(unit, event):
            logger.info(f"Sending event {event} for unit {unit} was successful.")
            notice.unlink(missing_ok=True)
        else:
            logger.warning(f"Sending event {event} for unit {unit} was unsuccessful.")


def main():
    """Entry point"""
    logging.basicConfig(filename=LOG_FILE, encoding='utf-8', level=logging.DEBUG)
    logging.info("Starting systemd juju notices daemon")
    os.makedirs(NOTICE_DIR, exist_ok=True)

    while True:
        process_notices()
        time.sleep(15)


if __name__ == "__main__":
    main()
