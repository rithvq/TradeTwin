"""Legacy unit scenarios use an isolated demo context; security tests enable auth explicitly."""

import base64
import os
import secrets
import sys

import pytest

os.environ["PROFILE_AUTH_ENABLED"] = "false"
os.environ["DOCUMENT_ENCRYPTION_KEY"] = base64.b64encode(secrets.token_bytes(32)).decode()

_namespaces = {}


def pytest_collectreport(report):
    if report.result and any(isinstance(item, pytest.Function) for item in report.result):
        _namespaces[report.nodeid] = (
            {
                name: module
                for name, module in sys.modules.items()
                if name == "app" or name.startswith("app.")
            },
            list(sys.path),
        )


@pytest.fixture(autouse=True)
def service_namespace(request):
    # Each microservice intentionally has an app package; retain its collected module graph.
    snapshot = _namespaces.get(request.node.nodeid.split("::", 1)[0])
    if snapshot:
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        modules, paths = snapshot
        sys.modules.update(modules)
        sys.path[:] = paths
