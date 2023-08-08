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

"""Sample charm for testing systemd events."""

import logging

import ops

from charms.operator_libs_linux.v1.systemd import daemon_reload, service_start
from charms.operator_libs_linux.v0.systemd_notices import Observer
from ops.charm import CharmEvents
from ops.model import ActiveStatus, BlockedStatus
from ops.framework import EventBase, EventSource
import os
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


class ServiceTestStarted(EventBase):
    """Emitted when systemd service has started."""


class ServiceTestStopped(EventBase):
    """Emitted when the systemd service has stopped."""


class SystemdServiceEvents(CharmEvents):
    """Slurmd emitted events."""

    service_test_started = EventSource(ServiceTestStarted)
    service_test_stopped = EventSource(ServiceTestStopped)


class SystemdEventTestCharm(ops.CharmBase):
    """Charm the application."""

    on = SystemdServiceEvents()

    def __init__(self, *args):
        super().__init__(*args)
        self._observer = Observer(self, services=["test"])
        self._observer.subscribe()

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.service_test_started, self._on_service_test_started)
        self.framework.observe(self.on.service_test_stopped, self._on_service_test_stopped)

    def _on_install(self, event: ops.InstallEvent):
        """Handle the install event."""
        environment = Environment(loader=FileSystemLoader("src/templates/"))

        unit_name = self.unit.name.replace('/', '-')
        data = {
            "charm_dir": os.getcwd(),
            "unit": unit_name,
            "service": "test",
        }

        # Install the systemd service for the test service
        template = environment.get_template("test.service.tmpl")
        content = template.render(data)
        with open("/etc/systemd/system/test.service", "w+") as f:
            f.writelines(content)

        # Reload the systemd daemon to read the new service files
        daemon_reload()

    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        service_start("test")
        self.unit.status = ActiveStatus()

    def _on_service_test_started(self, event: ServiceTestStarted):
        """Handle service started event from systemd notices"""
        logger.info("The test service has started")
        self.unit.status = ActiveStatus("Test service has started.")

    def _on_service_test_stopped(self, event: ServiceTestStopped):
        """Handle service stopped event from systemd notices"""
        logger.info("The test service has stopped")
        self.unit.status = BlockedStatus("Test service has stopped.")


if __name__ == "__main__":  # pragma: nocover
    ops.main(SystemdEventTestCharm)  # type: ignore
