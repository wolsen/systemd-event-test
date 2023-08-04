# systemd-event-test

This is a sample charm which puts in place a proof of concept for watching
systemd service events (start/stop) and calling hooks back into the juju charm.

When this charm is deployed, it installs a simple test systemd service. When the
service is stopped, the charm status will be updated to blocked indicating the service
is stopped. When the service is started, the charm status will be updated to
active indicating the service is started.

Note: this is only a POC at this point of time and the methodology is expected
to evolve.
