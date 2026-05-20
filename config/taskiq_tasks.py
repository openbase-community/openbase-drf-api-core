import pkgutil
from importlib import import_module

import structlog

from config.installed_apps import get_installed_apps
from users import tasks  # noqa: F401

logger = structlog.get_logger(__name__)

# Add enabled site tasks
for app in get_installed_apps():
    # Import the main tasks module
    tasks_module = import_module(f"{app}.tasks")

    # Import all submodules under {app}.tasks
    for _, modname, _ in pkgutil.iter_modules(tasks_module.__path__, f"{app}.tasks."):
        import_module(modname)
