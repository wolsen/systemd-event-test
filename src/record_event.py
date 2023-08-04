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

import argparse
import json
import logging
import os
from pathlib import Path


NOTICE_DIR = Path("/tmp/juju/systemd-notices/")
LOG_FILE = "/var/log/juju/systemd-events.log"

logger = logging.getLogger(__name__)


def record_event(service: str, unit: str, event: str) -> bool:
    """Records the event.

    :param service: the systemd service that the event refers to
    :param unit: the unit that is subscribed for notifications
    :param event: the event that occurred (e.g. started, stopped, etc)
    """
    event_file = NOTICE_DIR / f"{service.replace('-', '_')}.{event}"
    data = {"unit": unit}
    with open(event_file, 'w+') as f:
        json.dump(data, f)


def main():
    """Entry point"""
    logging.basicConfig(filename=LOG_FILE, encoding='utf-8', level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--service", type=str)
    parser.add_argument("-u", "--unit", type=str)
    parser.add_argument("-e", "--event", type=str)

    args = parser.parse_args()
    os.makedirs(NOTICE_DIR, exist_ok=True)

    logger.info(f"Recording event service: {args.service}, unit: {args.unit}, "
                f"event: {args.event}")
    record_event(args.service, args.unit, args.event)


if __name__ == "__main__":
    main()
