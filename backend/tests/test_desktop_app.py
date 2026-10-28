"""The installed program: its folders, its lock, and the facts the installer must keep."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import paths  # noqa: E402
from app.launcher import InstanceLock, ensure_credentials  # noqa: E402


def _load_app():
    spec = importlib.util.spec_from_file_location("acq_app_under_test", ROOT / "desktop" / "acq_app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_your_files_and_the_program_files_are_different_folders(tmp_path, monkeypatch):
    """An update replaces the program; it must never replace the database."""
    monkeypatch.setenv("ACQ_DATA_DIR", str(tmp_path / "mine"))

    assert paths.data_root() == (tmp_path / "mine").resolve()
    assert paths.data_root() != paths.resource_root()
    # The read-only files stay with the program, not with the data.
    assert paths.resource_file("frontend", "dist").is_relative_to(paths.resource_root())


def test_running_from_source_still_uses_the_folder_it_was_extracted_into(monkeypatch):
    """A ZIP from an earlier version must open with the database it already has."""
    monkeypatch.delenv("ACQ_DATA_DIR", raising=False)
    monkeypatch.delenv("ACQ_PORTABLE", raising=False)
    assert paths.data_root() == paths.resource_root()


def test_the_installed_program_keeps_data_outside_its_own_folder(monkeypatch):
    monkeypatch.delenv("ACQ_DATA_DIR", raising=False)
    monkeypatch.delenv("ACQ_PORTABLE", raising=False)
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    resolved = paths.data_root()
    assert resolved.is_absolute()
    assert "AcquisitionsAssistant" in resolved.name
    assert resolved != paths.resource_root()


def test_an_older_program_folder_hands_its_database_over_without_losing_it(tmp_path, monkeypatch):
    program = tmp_path / "old-zip"
    (program / "data").mkdir(parents=True)
    (program / "data" / "acquisitions.db").write_bytes(b"SQLite format 3\x00")
    (program / ".env").write_text("APP_ACCESS_PASSWORD=kept-secret\n")
    monkeypatch.setattr(paths, "resource_root", lambda: program)
    target = tmp_path / "installed"

    assert paths.adopt_legacy_data(target) is True
    assert (target / "data" / "acquisitions.db").read_bytes().startswith(b"SQLite format 3")
    assert "kept-secret" in (target / ".env").read_text()
    # The original is untouched, and a second run does not copy again.
    assert (program / "data" / "acquisitions.db").exists()
    assert paths.adopt_legacy_data(target) is False


def test_adoption_never_overwrites_a_database_that_already_exists(tmp_path, monkeypatch):
    program = tmp_path / "old-zip"
    (program / "data").mkdir(parents=True)
    (program / "data" / "acquisitions.db").write_bytes(b"old")
    monkeypatch.setattr(paths, "resource_root", lambda: program)
    target = tmp_path / "installed"
    (target / "data").mkdir(parents=True)
    (target / "data" / "acquisitions.db").write_bytes(b"current")

    assert paths.adopt_legacy_data(target) is False
    assert (target / "data" / "acquisitions.db").read_bytes() == b"current"


def test_a_portable_copy_keeps_its_data_next_to_the_program(tmp_path, monkeypatch):
    monkeypatch.delenv("ACQ_DATA_DIR", raising=False)
    monkeypatch.setenv("ACQ_PORTABLE", "1")
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ACQ.exe"))
    assert paths.data_root() == (tmp_path / "ACQ-data").resolve()


def test_the_expected_folders_are_created(tmp_path):
    root = paths.ensure_data_dirs(tmp_path / "abc")
    assert (root / "data" / "backups").is_dir()
    assert (root / "logs").is_dir()


def test_the_bundled_interface_is_found_from_the_program_folder():
    assert paths.browser_ui_ready() is True


def test_the_default_database_lives_in_the_data_folder_not_the_build(monkeypatch, tmp_path):
    monkeypatch.setenv("ACQ_DATA_DIR", str(tmp_path / "data-home"))
    from app import config

    monkeypatch.setattr(config, "DATA_ROOT", tmp_path / "data-home")
    config.get_settings.cache_clear()
    try:
        settings = config.Settings(_env_file=None)
        assert str(tmp_path / "data-home") in settings.database_url
        assert "frontend" not in settings.database_url
    finally:
        config.get_settings.cache_clear()


def test_the_password_file_is_written_in_the_data_folder():
    module = _load_app()
    assert module.data_root() == paths.data_root()


def test_only_one_copy_can_hold_the_lock(tmp_path):
    first = InstanceLock(tmp_path / "acq.lock")
    second = InstanceLock(tmp_path / "acq.lock")

    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_a_stale_lock_from_a_crash_does_not_block_the_next_start(tmp_path):
    lock_file = tmp_path / "acq.lock"
    lock_file.write_text("999999\n")
    lock = InstanceLock(lock_file)
    assert lock.acquire() is True
    assert lock_file.read_text().strip() == str(os.getpid())
    lock.release()


def test_check_mode_reports_folders_without_starting_a_server(tmp_path, monkeypatch, capsys):
    module = _load_app()
    monkeypatch.setenv("ACQ_DATA_DIR", str(tmp_path / "checked"))
    assert module.main(["--check", "--port", "8123"]) == 0
    printed = capsys.readouterr().out
    assert str((tmp_path / "checked").resolve()) in printed
    assert "http://127.0.0.1:8123" in printed


def test_the_data_folder_can_be_printed_for_support(tmp_path, monkeypatch, capsys):
    module = _load_app()
    monkeypatch.setenv("ACQ_DATA_DIR", str(tmp_path / "support"))
    assert module.main(["--data-dir"]) == 0
    assert str((tmp_path / "support").resolve()) in capsys.readouterr().out


def test_a_missing_interface_stops_the_app_instead_of_serving_a_blank_page(monkeypatch):
    module = _load_app()
    monkeypatch.setattr(module, "browser_ui_ready", lambda: False)
    assert module.main(["--no-window", "--port", "8124"]) == 2


def test_the_installer_keeps_your_data_out_of_the_program_folder():
    script = (ROOT / "desktop" / "installer.iss").read_text(encoding="utf-8")
    assert r"DefaultDirName={localappdata}\Programs" in script
    # The uninstaller asks before touching the database folder.
    assert "Keep them so a future version opens with all your sellers?" in script
    assert "{localappdata}\\{#AppFolder}\\data" in script


def test_the_windows_build_carries_everything_the_app_needs_at_runtime():
    spec = (ROOT / "desktop" / "acq.spec").read_text(encoding="utf-8")
    for required in ('"frontend/dist"', '"backend/migrations"', '"backend/fixtures"', '"alembic.ini"'):
        assert required in spec, required
    assert "console=False" in spec


def test_the_build_script_pins_the_versions_shown_in_windows_explorer():
    script = (ROOT / "scripts" / "build_windows.py").read_text(encoding="utf-8")
    assert "FileVersion" in script and "ProductName" in script
    assert "GreenSeedTX LLC" in script


def _load_build_script():
    spec = importlib.util.spec_from_file_location("acq_build_windows", ROOT / "scripts" / "build_windows.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_build_script_runs_a_command_in_the_folder_it_was_given(tmp_path, monkeypatch):
    """npm must run inside frontend/, and a duplicate cwd= keyword used to raise TypeError."""
    build = _load_build_script()
    seen = {}

    def fake_run(command, check, cwd, **kwargs):
        seen["command"] = command
        seen["check"] = check
        seen["cwd"] = Path(cwd)

    monkeypatch.setattr(build.subprocess, "run", fake_run)
    build.run(["npm", "run", "build"], cwd=tmp_path)
    assert seen["cwd"] == tmp_path
    build.run(["npm", "run", "build"])
    assert seen["cwd"] == build.ROOT


def test_the_build_script_says_so_when_the_interface_cannot_be_compiled(monkeypatch):
    build = _load_build_script()
    monkeypatch.setattr(build.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="npm is required"):
        build.build_interface()


def test_credentials_survive_inside_the_data_folder(tmp_path):
    env_file = tmp_path / "data-home" / ".env"
    password, created = ensure_credentials(env_file, required=True)
    assert created and env_file.is_file()
    again, created_again = ensure_credentials(env_file, required=True)
    assert again == password and created_again is False


@pytest.mark.skipif(os.name != "nt", reason="The Windows-only path is exercised on Windows")
def test_windows_lock_uses_an_exclusive_byte_range(tmp_path):
    lock = InstanceLock(tmp_path / "win.lock")
    assert lock.acquire() is True
    lock.release()


# --------------------------------------------------------------------------- the window


def _fake_webview(behaviour="ok"):
    """A stand-in for pywebview so the window logic is tested without a display."""
    module = type(sys)("webview")
    calls = {}
    module.calls = calls

    def create_window(title, url, **kwargs):
        calls["window"] = (title, url, kwargs)

    def start(**kwargs):
        calls["start"] = kwargs
        if behaviour == "fail":
            raise RuntimeError("no WebView2 runtime")

    module.create_window = create_window
    module.start = start
    return module


def test_the_installed_program_opens_a_native_window_not_a_browser_tab(monkeypatch):
    module = _load_app()
    fake = _fake_webview()
    monkeypatch.setitem(sys.modules, "webview", fake)
    closed = []
    monkeypatch.setattr(module.webbrowser, "open", lambda url: closed.append(("browser", url)))

    assert module.native_window("http://127.0.0.1:8010", lambda: closed.append("closed")) is True
    assert fake.calls["window"][0] == "Acquisitions Assistant"
    assert fake.calls["window"][1] == "http://127.0.0.1:8010"
    assert closed == ["closed"], "a real window must not also open a browser tab"


def test_a_missing_webview_runtime_falls_back_without_pretending_it_worked(monkeypatch):
    module = _load_app()
    monkeypatch.setitem(sys.modules, "webview", _fake_webview("fail"))
    closed = []
    assert module.native_window("http://127.0.0.1:8010", lambda: closed.append("closed")) is False
    assert closed == [], "a failed window must not run the close hook"


def test_the_fallback_opens_the_browser_and_still_stops_cleanly(monkeypatch):
    module = _load_app()
    monkeypatch.setitem(sys.modules, "webview", _fake_webview("fail"))
    monkeypatch.setattr(module, "tk_window", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no tkinter")))
    opened, closed = [], []
    monkeypatch.setattr(module.webbrowser, "open", lambda url: opened.append(url))

    module.open_window("http://127.0.0.1:8010", "", [], lambda: closed.append(True))
    assert opened == ["http://127.0.0.1:8010"]
    assert closed == [True]


def test_no_window_mode_for_scripts_and_ci(monkeypatch):
    module = _load_app()
    monkeypatch.setenv("ACQ_NO_WINDOW", "1")
    opened = []
    monkeypatch.setattr(module.webbrowser, "open", lambda url: opened.append(url))
    closed = []
    module.open_window("http://127.0.0.1:8010", "", [], lambda: closed.append(True))
    assert opened == [] and closed == [True]
