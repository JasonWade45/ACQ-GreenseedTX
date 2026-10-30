"""The desktop launcher is the entry point non-server users actually run."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("acq_desktop", ROOT / "scripts" / "acq_desktop.py")
desktop = importlib.util.module_from_spec(SPEC)
sys.modules["acq_desktop"] = desktop
SPEC.loader.exec_module(desktop)


def test_env_roundtrip_keeps_comments_out_and_values_in(tmp_path):
    path = tmp_path / ".env"
    desktop.write_env(path, {"APP_ACCESS_PASSWORD": "Acq-abcdefghijklmnop", "SESSION_SECRET": "a" * 64})
    values = desktop.read_env(path)

    assert values["APP_ACCESS_PASSWORD"] == "Acq-abcdefghijklmnop"
    assert values["SESSION_SECRET"] == "a" * 64
    assert path.read_text().startswith("#")


def test_env_write_preserves_keys_the_user_added(tmp_path):
    path = tmp_path / ".env"
    path.write_text("APP_TIMEZONE=Africa/Cairo\nGROQ_ENABLED=false\n")
    desktop.write_env(path, {"APP_ACCESS_PASSWORD": "Acq-abcdefghijklmnop"})

    values = desktop.read_env(path)
    assert values["APP_TIMEZONE"] == "Africa/Cairo"
    assert values["GROQ_ENABLED"] == "false"
    assert values["APP_ACCESS_PASSWORD"] == "Acq-abcdefghijklmnop"


def test_env_file_is_private_on_posix(tmp_path):
    if sys.platform.startswith("win"):
        pytest.skip("POSIX file-permission bits do not exist on Windows")
    path = tmp_path / ".env"
    desktop.write_env(path, {"APP_ACCESS_PASSWORD": "Acq-abcdefghijklmnop"})
    assert path.stat().st_mode & 0o077 == 0


def test_first_run_generates_a_strong_password_and_second_run_keeps_it(tmp_path):
    path = tmp_path / ".env"
    first, created = desktop.ensure_credentials(path)
    second, created_again = desktop.ensure_credentials(path)

    assert created is True and created_again is False
    assert first == second
    assert len(first) >= desktop.MIN_PASSWORD
    assert first.startswith("Acq-")


def test_a_weak_saved_password_is_replaced(tmp_path):
    path = tmp_path / ".env"
    desktop.write_env(path, {"APP_ACCESS_PASSWORD": "short"})
    password, created = desktop.ensure_credentials(path)

    assert created is True
    assert len(password) >= desktop.MIN_PASSWORD
    assert desktop.read_env(path)["APP_ACCESS_PASSWORD"] == password


def test_a_short_session_secret_is_repaired_without_touching_the_password(tmp_path):
    path = tmp_path / ".env"
    desktop.write_env(path, {"APP_ACCESS_PASSWORD": "Acq-abcdefghijklmnop", "SESSION_SECRET": "tiny"})
    password, created = desktop.ensure_credentials(path)

    assert created is False and password == "Acq-abcdefghijklmnop"
    assert len(desktop.read_env(path)["SESSION_SECRET"]) >= 32


def test_local_only_mode_needs_no_password(tmp_path):
    password, created = desktop.ensure_credentials(tmp_path / ".env", required=False)
    assert password == "" and created is False


def test_lan_addresses_never_return_loopback():
    assert all(not ip.startswith("127.") for ip in desktop.lan_addresses())


def test_urls_are_built_for_the_chosen_port():
    assert desktop.local_url(8010) == "http://127.0.0.1:8010"
    assert desktop.lan_urls(8010, ["192.168.1.5", "10.0.0.7"]) == [
        "http://192.168.1.5:8010",
        "http://10.0.0.7:8010",
    ]


def test_qr_is_ascii_text_when_segno_is_available():
    lines = desktop.qr_lines("http://192.168.1.5:8010")
    if not lines:
        pytest.skip("segno is not installed in this environment")
    assert len(lines) > 5
    assert all(line.strip() for line in lines)


def test_port_probe_reports_a_bound_port_as_taken():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert desktop.port_is_free(port, host="127.0.0.1") is False


def test_banner_shows_every_address_and_never_hides_the_lan_one():
    text = desktop.banner(8010, "Acq-abcdefghijklmnop", True, True, ["192.168.1.5", "10.0.0.7"])
    assert "http://127.0.0.1:8010" in text
    assert "http://192.168.1.5:8010" in text
    assert "http://10.0.0.7:8010" in text
    assert "Acq-abcdefghijklmnop" in text


def test_banner_without_a_network_address_says_so_instead_of_lying():
    text = desktop.banner(8010, "Acq-abcdefghijklmnop", False, True, [])
    assert "no network address found" in text


def test_check_mode_exits_without_starting_a_server(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(desktop, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(desktop, "ROOT", ROOT)
    monkeypatch.delenv("APP_ACCESS_PASSWORD", raising=False)
    code = desktop.main(["--check", "--port", "8123", "--no-browser"])
    assert code == 0
    assert "http://127.0.0.1:8123" in capsys.readouterr().out


def test_show_password_prints_the_saved_value(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    desktop.write_env(path, {"APP_ACCESS_PASSWORD": "Acq-abcdefghijklmnop"})
    monkeypatch.setattr(desktop, "ENV_FILE", path)
    assert desktop.main(["--show-password"]) == 0
    assert "Acq-abcdefghijklmnop" in capsys.readouterr().out


def test_a_saved_password_is_not_printed_on_every_start():
    """A shared screen must not leak the workspace password."""
    text = desktop.banner(8010, "Acq-abcdefghijklmnop", False, True, ["192.168.1.5"])
    assert "Acq-abcdefghijklmnop" not in text
    assert "--show-password" in text


def test_the_first_run_still_prints_the_generated_password_once():
    text = desktop.banner(8010, "Acq-abcdefghijklmnop", True, True, ["192.168.1.5"])
    assert "Acq-abcdefghijklmnop" in text


def test_new_password_rotates_without_needing_a_previous_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".env"
    monkeypatch.setattr(desktop, "ENV_FILE", path)
    assert desktop.main(["--new-password"]) == 0
    written = desktop.read_env(path)["APP_ACCESS_PASSWORD"]
    assert written in capsys.readouterr().out
    assert len(written) >= desktop.MIN_PASSWORD
