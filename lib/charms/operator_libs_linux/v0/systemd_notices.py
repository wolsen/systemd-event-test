#!/usr/bin/python3
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

"""Systemd notices daemon for emitting Juju events."""

__all__ = ["Observer", "ServiceStartedEvent", "ServiceStoppedEvent"]

import argparse
import asyncio
import logging
import os
import re
import shutil
import signal
import sys
import textwrap
from pathlib import Path
from typing import Dict, List, Union, TypeVar

from dbus_next.aio import MessageBus
from dbus_next.errors import DBusError
from dbus_next.message import Message
from dbus_next.constants import BusType, MessageType

from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource, Handle, Object

PYDEPS = ["dbus-next>=0.2.3"]

LIBID = "TESTINGPURPOSESONLY"
LIBAPI = 0
LIBPATCH = 1

logger = logging.getLogger(__name__)

T = TypeVar('T')

SERVICE_STATES = {}
SERVICE_HOOK_RE = re.compile(r"service-(?P<service>[\w\\:-]*)-(?:started|stopped)")

DBUS_CHAR_MAPPINGS = {
    '_40': '@',
    '_2e': '.',
    '_5f': '_',
    '_2d': '-',
    '_5c': '\\',
}


class _ServiceEvent(EventBase):
    """Base event for service-related events."""

    def __init__(self, handle: Handle, service_name: str) -> None:
        super().__init__(handle)
        self._service_name = service_name

    def snapshot(self) -> Dict[str, str]:
        """Snapshot event."""
        return {"service_name": self._service_name}

    def restore(self, snapshot: Dict[str, str]) -> None:
        """Restore event snapshot."""
        self._service_name = snapshot["service_name"]

    @property
    def service_name(self) -> str:
        return self._service_name


class ServiceStartedEvent(_ServiceEvent):
    """Event emitted when service has started."""


class ServiceStoppedEvent(_ServiceEvent):
    """Event emitted when service has stopped."""


class _ServiceEvents(CharmEvents):
    """Events emitted based on an observed service's state."""

    service_started = EventSource(ServiceStartedEvent)
    service_stopped = EventSource(ServiceStoppedEvent)


class Observer(Object):
    """Observe systemd services and send notices based on current the current service state."""

    on = _ServiceEvents()

    def __init__(self, charm: CharmBase, services: Union[str, List[str]]) -> None:
        super().__init__(charm, 'systemd_notices.Observer')
        self._charm = charm
        self._services = [services] if type(services) == str else services
        unit_name = self._charm.unit.name.replace("/", "-")
        self._service_file = Path(f"/etc/systemd/system/juju-{unit_name}-systemd-notices.service")
        self._systemd = Systemd()

        # Define custom events for each observed service.
        for service in self._services:
            self.on.define_event(f"service_{service}_started", ServiceStartedEvent)
            self.on.define_event(f"service_{service}_stopped", ServiceStoppedEvent)

    def subscribe(self) -> None:
        """Subscribe observer to registered services."""
        # Generate hooks for observer events.
        for service in self._services:
            shutil.copy(f"{Path.cwd()}/dispatch", f"hooks/service-{service}-started")
            shutil.copy(f"{Path.cwd()}/dispatch", f"hooks/service-{service}-stopped")

        # Generate and start observer daemon using systemd.
        if self._service_file.exists():
            logger.debug(f"Overwriting existing service file {self._service_file.name}")
        self._service_file.write_text(
            textwrap.dedent(
                f"""
                [Unit]
                Description=Juju systemd notices daemon
                After=multi-user.target

                [Service]
                Type=simple
                Restart=always
                ExecStart=/usr/bin/python3 {__file__} {self._charm.unit.name}
                WorkingDirectory={Path.cwd()}
                Environment=PYTHONPATH={Path.cwd()/"venv"}

                [Install]
                WantedBy=multi-user.target
                """
            ).strip()
        )
        logger.debug(f"Service file {self._service_file.name} created. Reloading systemd")
        self._systemd.reload()
        svc = self._service_file.name
        logger.debug(f"Starting {svc} daemon")
        self._systemd.enable(svc)
        self._systemd.start_unit(svc, "fail")

    def stop(self) -> None:
        """Stop the observer from observing subscriptions."""
        svc = self._service_file.name
        logger.debug(f"Stopping {svc} daemon")
        self._systemd.stop_unit(svc)
        self._systemd.disable(svc)


class Systemd:

    @staticmethod
    async def _get_systemd_manager():
        """

        :return:
        """
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        api = await bus.introspect("org.freedesktop.systemd1", "/org/freedesktop/systemd1")
        proxy = bus.get_proxy_object("org.freedesktop.systemd1", "/org/freedesktop/systemd1", api)
        mgr = proxy.get_interface("org.freedesktop.systemd1.Manager")
        return mgr

    async def _async_dbus_call(self, function, *args, **kwargs) -> T:
        """

        :param function:
        :param args:
        :param kwargs:
        :return:
        """
        mgr = await self._get_systemd_manager()
        func = getattr(mgr, f"call_{function}")
        return await func(*args, **kwargs)

    def _dbus_call(self, function, *args, **kwargs) -> T:
        """

        :param function:
        :param args:
        :param kwargs:
        :return:
        """
        try:
            loop = asyncio.get_running_loop()
            return loop.run_until_complete(self._async_dbus_call(function, *args, **kwargs))
        except RuntimeError:
            return asyncio.run(self._async_dbus_call(function, *args, **kwargs))

    def reload(self):
        """Reloads the systemd service files.
        :return:
        """
        return self._dbus_call('reload')

    def start_unit(self, unit: Union[str, Path], mode: str = "fail"):
        """Starts the specified unit.
        """
        return self._dbus_call('start_unit', str(unit), mode)

    def stop_unit(self, unit: Union[str, Path], mode: str = "fail"):
        """Stops the specified unit.
        """
        return self._dbus_call('stop_unit', str(unit), mode)

    def enable(self, unit: Union[str, Path], runtime_only: bool = False,
               replace_symlinks: bool = True):
        """Enables the specified service/unit.

        :return:
        """
        return self._dbus_call('enable_unit_files', [str(unit)],
                               runtime_only, replace_symlinks)

    def disable(self, unit: Union[str, Path]):
        """

        :param unit:
        :return:
        """
        return self._dbus_call('disable_unit_files', str(unit))


def _name_to_dbus_path(name: str) -> str:
    """Converts the specified name into an org.freedesktop.systemd1.Unit path handle.

    :param name: the name of the service
    :return: string containing the dbus path
    """
    # DBUS Object names may only contain ASCII chars [A-Z][a-z][0-9]_
    # It's basically urlencoded but instead of a %, it uses a _
    path = name
    for key, value in DBUS_CHAR_MAPPINGS.items():
        path = path.replace(value, key)

    return f"/org/freedesktop/systemd1/unit/{path}"


def _dbus_path_to_name(path: str) -> str:
    """Converts the specified DBus path handle to a service name.

    :param path: the path to convert
    :return: string containing the service name
    """
    # DBUS Object names may oncly contain ASCII chars [A-Z][a-z][0-9]_
    name = os.path.basename(path)
    for key, value in DBUS_CHAR_MAPPINGS.items():
        name = name.replace(key, value)

    return name


def _systemd_unit_changed(msg: Message) -> bool:
    """Callback for systemd unit changes on the DBus bus.

    Invoked when a PropertiesChanged event occurs on an org.freedesktop.systemd1.Unit
    object across the dbus. These events are sent whenever a unit changes state, including
    starting and stopping.

    :param msg: the message to process in the callback
    :return: True if the event is processed, False otherwise
    """
    logger.debug(f"Received message: path: {msg.path}, interface: {msg.interface}, "
                 f"member: {msg.member}")
    service = _dbus_path_to_name(msg.path)
    properties = msg.body[1]
    if 'ActiveState' not in properties:
        return False

    global SERVICE_STATES
    if service not in SERVICE_STATES:
        logger.debug(f"Dropping event for unwatched service: {service}")
        return False

    curr_state = properties['ActiveState'].value
    prev_state = SERVICE_STATES[service]
    # Drop transitioning and duplicate events
    if curr_state.endswith("ing") or curr_state == prev_state:
        logger.debug(f"Dropping event - service: {service}, state: {curr_state}")
        return False

    SERVICE_STATES[service] = curr_state
    logger.debug(f"Service {service} changed state to {curr_state}")
    # Run the hook in a separate thread so the dbus notifications aren't
    # blocked from being received.
    asyncio.create_task(_send_juju_notification(service, curr_state))
    return True


async def _send_juju_notification(service: str, state: str) -> None:
    """Invokes a Juju hook to notify that a service state has changed.

    :param service: the name of the service which has changed state
    :param state: the state of the service
    :return: None
    """
    if service.endswith(".service"):
        service = service[0:-len(".service")]
    if state == "active":
        event_name = "started"
    else:
        event_name = "stopped"
    hook = f"service-{service}-{event_name}"
    cmd = [
        "/usr/bin/juju-exec",
        JUJU_UNIT,
        f"hooks/{hook}"
    ]

    logger.debug(f"Invoking hook {hook} with command: {' '.join(cmd)}")
    process = await asyncio.create_subprocess_exec(*cmd, )
    await process.wait()
    if process.returncode:
        logger.error(f"Hook command '{' '.join(cmd)}' failed with returncode "
                     f"{process.returncode}")
    else:
        logger.info(f"Hook command '{' '.join(cmd)}' succeeded.")


async def _get_state(bus: MessageBus, service: str) -> str:
    """Retrieves the current state of the specified service.

    :param bus: the message bus to query on
    :param service: the service to query the state of
    :return: the state of the service, active or inactive
    """
    obj_path = _name_to_dbus_path(service)
    try:
        logger.debug(f"Retrieving state for service {service} at object path: {obj_path}")
        introspection = await bus.introspect("org.freedesktop.systemd1", obj_path)
        proxy = bus.get_proxy_object("org.freedesktop.systemd1", obj_path, introspection)
        properties = proxy.get_interface('org.freedesktop.DBus.Properties')
        state = await properties.call_get('org.freedesktop.systemd1.Unit', 'ActiveState')  # noqa
        return state.value
    except DBusError:
        # This will be thrown if the unit specified does not currently exist,
        # which happens if the application needs to install the service, etc.
        return "unknown"


def _load_services_sync():
    """Sync method for load_services_async.

    This is a synchronous form of the _load_services method. This is called from a
    signal handler which cannot take coroutines, thus this method will schedule a
    task to run in the current running loop. If a running loop cannot be found, it
    will run it using the asyncio.run() method.
    """
    try:
        # Make sure an event loop is running to schedule as a task
        asyncio.get_running_loop()
        asyncio.create_task(_load_services())
    except RuntimeError:
        # No async event loop running
        asyncio.run(_load_services())


async def _load_services():
    """Loads the services from hooks for the unit.

    Parses the hook names found in the charm hooks directory and determines
    if this is one of the services that the charm is interested in observing.
    The hooks will match one of the following names:

      - service-{service_name}-started
      - service-{service_name}-stopped

    Any other hooks are ignored and not loaded into the set of services
    that should be watched. Upon finding a service hook it's current ActiveState
    will be queried from systemd to determine it's initial state.

    :return: None
    """
    global JUJU_UNIT
    hooks_dir = Path(f"{os.getcwd()}/hooks")
    logger.info(f"Loading services from hooks in {hooks_dir}")

    if not hooks_dir.exists():
        logger.warning(f"Hooks dir {hooks_dir} does not exist.")
        return

    watched_services = []
    # Get service-{service}-(started|stopped) hooks defined by the charm.
    for hook in filter(lambda p: SERVICE_HOOK_RE.match(p.name), hooks_dir.iterdir()):
        match = SERVICE_HOOK_RE.match(hook.name)
        watched_services.append(match.group("service"))

    logger.info(f"Services from hooks are {watched_services}")
    if not watched_services:
        return

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    # Loop through all the services and be sure that a new watcher is
    # started for new ones.
    for service in watched_services:
        # The .service suffix is not necessary and will cause lookup
        # failures of the service unit when readying the watcher.
        if not service.endswith(".service"):
            service = f"{service}.service"

        if service not in SERVICE_STATES:
            state = await _get_state(bus, service)
            logger.debug(f"Adding service '{service}' with initial state: {state}")
            SERVICE_STATES[service] = state


async def _main():
    """Main async entrypoint which will set up the service to listen for events.

    Connects to the system message bus and registers for signals/events on the
    org.freedesktop.systemd1.Unit object looking for any PropertyChanged events.

    This method additionally sets up signal handlers for various signals to either
    terminate the process or reload the configuration from the hooks directory.

    :return: None
    """
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    loop.add_signal_handler(signal.SIGINT, stop_event.set)
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)
    loop.add_signal_handler(signal.SIGHUP, _load_services_sync)

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    await _load_services()

    reply = await bus.call(Message(
        destination='org.freedesktop.DBus',
        path='/org/freedesktop/DBus',
        interface='org.freedesktop.DBus',
        member='AddMatch',
        signature='s',
        body=["path_namespace='/org/freedesktop/systemd1/unit',type='signal',"
              "interface='org.freedesktop.DBus.Properties'"],
        serial=bus.next_serial(),
    ))
    assert reply.message_type == MessageType.METHOD_RETURN
    bus.add_message_handler(_systemd_unit_changed)
    await stop_event.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    parser.add_argument("unit", type=str)
    args = parser.parse_args()

    console_handler = logging.StreamHandler()
    if args.debug:
        logger.setLevel(logging.DEBUG)
        console_handler.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
        console_handler.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    # Intentionally set as global.
    JUJU_UNIT = args.unit

    if not JUJU_UNIT:
        parser.print_usage()
        sys.exit(2)

    logger.info("Starting systemd notices service")
    asyncio.run(_main())
