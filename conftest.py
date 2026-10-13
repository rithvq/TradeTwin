"""Legacy unit scenarios use an isolated demo context; security tests enable auth explicitly."""

import base64
import inspect
import os
import secrets
import sys
from types import ModuleType

import pytest

os.environ["PROFILE_AUTH_ENABLED"] = "false"
os.environ["DOCUMENT_ENCRYPTION_KEY"] = base64.b64encode(secrets.token_bytes(32)).decode()

_namespaces = {}


@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makeitem(collector, name, obj):
    if isinstance(collector, pytest.Module) and (
        (name.startswith("test_") and inspect.isfunction(obj))
        or (name.startswith("Test") and inspect.isclass(obj))
    ):
        # Collect reports can be delivered after another service's module was imported.
        # Capture while this module's test items are being made instead.
        _namespaces[collector.nodeid] = (
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
        # Package attributes also retain lazy imports between tests. Restore them along
        # with sys.modules so exception/model classes cannot cross service namespaces.
        for module in modules.values():
            if not hasattr(module, "__path__"):
                continue
            for key, value in list(vars(module).items()):
                if isinstance(value, ModuleType) and value.__name__.startswith("app."):
                    if value.__name__ not in modules:
                        delattr(module, key)
            for name, child in modules.items():
                parent, _, attribute = name.rpartition(".")
                if parent == module.__name__:
                    setattr(module, attribute, child)
        sys.path[:] = paths
