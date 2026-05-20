import functools
import importlib.metadata


@functools.cache
def get_installed_apps() -> list[str]:
    """Retrieve Django installed apps from registered entry points."""
    apps = []
    entry_points = importlib.metadata.entry_points()

    for entry_point in entry_points.select(group="api_core.installed_apps"):
        app_list_func = entry_point.load()
        if callable(app_list_func):
            apps.extend(app_list_func())

    return apps


def merge_settings_from_module(mod, target_globals):
    names = getattr(mod, "__all__", None) or dir(mod)
    for name in names:
        # copy only public, UPPERCASE names (typical Django convention)
        if not name.startswith("_") and name.isupper():
            target_globals[name] = getattr(mod, name)


def load_all_package_settings(target_globals):
    """Load settings from registered settings entry points."""
    entry_points = importlib.metadata.entry_points()
    for entry_point in entry_points.select(group="api_core.settings"):
        mod = entry_point.load()
        merge_settings_from_module(mod, target_globals)
