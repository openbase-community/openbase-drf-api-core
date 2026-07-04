from config.installed_apps import get_installed_apps
from config.taskiq_discovery import import_tasks_for_app
from users import tasks  # noqa: F401

# Add enabled site tasks
for app in get_installed_apps():
    import_tasks_for_app(app)
