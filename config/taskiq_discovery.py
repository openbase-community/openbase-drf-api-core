import pkgutil
from importlib import import_module

import structlog

logger = structlog.get_logger(__name__)


def import_tasks_for_app(app: str) -> None:
    tasks_module_name = f"{app}.tasks"

    try:
        tasks_module = import_module(tasks_module_name)
    except ModuleNotFoundError as exc:
        if exc.name == tasks_module_name:
            logger.debug("No task module for app", app=app, module=tasks_module_name)
            return
        raise

    tasks_module_path = getattr(tasks_module, "__path__", None)
    if tasks_module_path is None:
        logger.debug("Imported task module", app=app, module=tasks_module_name)
        return

    for _, modname, _ in pkgutil.iter_modules(tasks_module_path, f"{tasks_module_name}."):
        import_module(modname)

    logger.debug("Imported task package", app=app, module=tasks_module_name)
