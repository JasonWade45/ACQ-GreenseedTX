"""The install and compose files are the parts users run when nothing else works.

They are executed here for real (bash is available), not merely parsed, because two real
defects shipped: ``--help`` broke when the script came through a pipe, and ``--no-https``
silently kept starting Caddy, which can never obtain a certificate for an IP address.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not installed here")


def run(args, stdin_file: Path | None = None):
    if stdin_file is None:
        return subprocess.run([BASH, *args], capture_output=True, text=True, timeout=90)
    with stdin_file.open("rb") as handle:
        return subprocess.run(
            [BASH, *args], stdin=handle, capture_output=True, text=True, timeout=90
        )


def test_every_shell_script_parses():
    scripts = [ROOT / "start-acq.sh", *sorted((ROOT / "deploy").glob("*.sh"))]
    assert scripts
    for script in scripts:
        result = run(["-n", str(script)])
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


def test_help_works_when_the_script_arrives_through_a_pipe():
    """The documented install command is `curl ... | sudo bash -s -- --domain ...`."""
    result = run(["-s", "--", "--help"], stdin_file=ROOT / "deploy" / "install.sh")
    assert result.returncode == 0
    assert "--no-https" in result.stdout
    assert "--domain" in result.stdout
    assert "No such file" not in result.stderr


def test_missing_domain_is_refused_with_an_actionable_message():
    result = run([str(ROOT / "deploy" / "install.sh"), "--dry-run"])
    assert result.returncode == 1
    assert "--domain is required" in result.stderr


def test_an_ip_address_needs_no_https_because_no_certificate_can_be_issued():
    result = run([str(ROOT / "deploy" / "install.sh"), "--domain", "203.0.113.10", "--dry-run"])
    assert result.returncode == 1
    assert "bare IP" in result.stderr


def test_dry_run_reports_every_step_and_changes_nothing():
    result = run(
        [str(ROOT / "deploy" / "install.sh"), "--domain", "acq.example.com", "--dry-run"]
    )
    assert result.returncode == 0, result.stderr
    assert "would run" in result.stdout
    assert "https://acq.example.com" in result.stdout
    assert "docker-compose.yml" in result.stdout


def test_no_https_publishes_the_port_instead_of_starting_caddy():
    result = run(
        [
            str(ROOT / "deploy" / "install.sh"),
            "--domain",
            "203.0.113.10",
            "--no-https",
            "--port",
            "8099",
            "--dry-run",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert "docker-compose-http.yml" in result.stdout
    assert "http://203.0.113.10:8099" in result.stdout
    assert "unencrypted" in result.stderr


def test_compose_files_agree_on_the_project_name_so_the_volume_is_shared():
    https = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text())
    http = yaml.safe_load((ROOT / "deploy" / "docker-compose-http.yml").read_text())
    assert https["name"] == http["name"]
    # The data volume must be the same in both, or switching mode would look like data loss.
    assert "app-data" in https["volumes"] and "app-data" in http["volumes"]
    assert https["services"]["app"]["volumes"] == http["services"]["app"]["volumes"]


def test_the_http_variant_exposes_no_caddy_and_publishes_a_port():
    http = yaml.safe_load((ROOT / "deploy" / "docker-compose-http.yml").read_text())
    assert "caddy" not in http["services"]
    assert any("8000" in str(entry) for entry in http["services"]["app"]["ports"])


def test_the_https_variant_keeps_the_app_unpublished_behind_caddy():
    https = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text())
    assert "ports" not in https["services"]["app"]
    assert "443:443" in https["services"]["caddy"]["ports"]
    # The proxy must forward the original Host, otherwise every write is refused as cross-origin.
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text()
    assert "header_up Host {host}" in caddyfile


def test_explicit_dockerfile_is_not_overridden_by_a_compose_guess():
    https = yaml.safe_load((ROOT / "deploy" / "docker-compose.yml").read_text())
    build = https["services"]["app"]["build"]
    assert build["dockerfile"] == "Dockerfile"
    assert build["context"] == ".."


def test_render_blueprints_differ_only_where_the_plan_forces_it():
    paid = yaml.safe_load((ROOT / "render.yaml").read_text())["services"][0]
    free = yaml.safe_load((ROOT / "render-free.yaml").read_text())["services"][0]
    assert paid["plan"] != free["plan"]
    assert paid["disk"] and not free.get("disk")
    # A free instance is replaced on every deploy, so auto-deploy would erase the data.
    assert free["autoDeploy"] is False
    assert free["healthCheckPath"] == paid["healthCheckPath"] == "/api/health"
    assert "APP_ACCESS_PASSWORD" in {item["key"] for item in free["envVars"]}
    assert all("value" not in item for item in free["envVars"] if item["key"] == "APP_ACCESS_PASSWORD")


def test_documentation_points_only_at_files_that_exist():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_references", ROOT / "scripts" / "check_references.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.broken_links() == []
    assert module.stale_references() == []
    assert module.missing_packaged_files() == []
