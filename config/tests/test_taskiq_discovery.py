import importlib
import sys

from config.taskiq_discovery import import_tasks_for_app


def test_import_tasks_for_app_supports_plain_tasks_module(tmp_path, monkeypatch):
    app_dir = tmp_path / "plain_app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (app_dir / "tasks.py").write_text("TASK_IMPORTED = True\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    import_tasks_for_app("plain_app")

    assert sys.modules["plain_app.tasks"].TASK_IMPORTED is True


def test_import_tasks_for_app_imports_task_package_submodules(tmp_path, monkeypatch):
    app_dir = tmp_path / "package_app"
    tasks_dir = app_dir / "tasks"
    tasks_dir.mkdir(parents=True)
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    (tasks_dir / "__init__.py").write_text("", encoding="utf-8")
    (tasks_dir / "daily.py").write_text("TASK_IMPORTED = True\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    import_tasks_for_app("package_app")

    assert sys.modules["package_app.tasks.daily"].TASK_IMPORTED is True


def test_import_tasks_for_app_skips_apps_without_tasks(tmp_path, monkeypatch):
    app_dir = tmp_path / "quiet_app"
    app_dir.mkdir()
    (app_dir / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    import_tasks_for_app("quiet_app")

    assert "quiet_app.tasks" not in sys.modules
