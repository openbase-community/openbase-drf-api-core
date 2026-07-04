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
        logger.warning(
            "Skipping app task module after import failure",
            app=app,
            module=tasks_module_name,
            error=str(exc),
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Skipping app task module after import failure",
            app=app,
            module=tasks_module_name,
            error=str(exc),
        )
        return

    tasks_module_path = getattr(tasks_module, "__path__", None)
    if tasks_module_path is None:
        logger.debug("Imported task module", app=app, module=tasks_module_name)
        return

    for _, modname, _ in pkgutil.iter_modules(tasks_module_path, f"{tasks_module_name}."):
        try:
            import_module(modname)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Skipping app task submodule after import failure",
                app=app,
                module=modname,
                error=str(exc),
            )

    logger.debug("Imported task package", app=app, module=tasks_module_name)
