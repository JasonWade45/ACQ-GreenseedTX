"""Package public source and the prebuilt UI, never databases or private runtime files."""

import argparse
import hashlib
import os
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".gitattributes",
    ".env.example",
    ".gitignore",
    "LICENSE",
    "README.md",
    "PROJECT_STATUS.md",
    "START_HERE_WINDOWS_AR.md",
    "START-WINDOWS.cmd",
    "UPDATE-WINDOWS.cmd",
    "UPDATE-WINDOWS.ps1",
    "MERGE-WORKSPACES.cmd",
    "MERGE-WORKSPACES.ps1",
    "alembic.ini",
    "pyproject.toml",
}
PUBLIC_FOLDERS = {"backend", "frontend", "scripts", "docs", "examples"}
EXCLUDED_FOLDERS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".vite",
    "playwright-report",
    "test-results",
    "data",
    "backups",
    "release",
}
EXCLUDED_NAMES = {"official-docs.bundle.txt"}


def public_files():
    files = [ROOT / name for name in ROOT_FILES]
    for folder in sorted(PUBLIC_FOLDERS):
        for directory, subdirectories, names in os.walk(ROOT / folder):
            subdirectories[:] = sorted(name for name in subdirectories if name not in EXCLUDED_FOLDERS)
            for name in sorted(names):
                path = Path(directory) / name
                if (
                    name in EXCLUDED_NAMES
                    or name.startswith((".env", ".preview"))
                    or name.endswith((".pyc", ".log", ".tsbuildinfo", ".db", ".db-wal", ".db-shm", ".bak"))
                ):
                    continue
                files.append(path)
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing regular public file: {path.relative_to(ROOT)}")
    required = [
        ROOT / "frontend/dist/index.html",
        ROOT / "backend/migrations/versions/0a6d91cf17b2_unified_plans_and_workspace_merges.py",
        ROOT / "backend/fixtures/legacy-workspace.sql",
    ]
    if any(path not in files for path in required):
        raise ValueError("Build the final frontend and retain the unified migration/fixture before packaging")
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "acquisitions-assistant-v1.2.zip")
    parser.add_argument("--replace", action="store_true", help="Explicitly replace this release ZIP only")
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.suffix.lower() != ".zip":
        parser.error("The release output must end in .zip")
    if output.exists() and not args.replace:
        parser.error("Output exists; select another filename or explicitly use --replace")
    output.parent.mkdir(parents=True, exist_ok=True)
    files = public_files()
    manifest = []
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".release-", suffix=".part", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                relative = path.relative_to(ROOT).as_posix()
                data = path.read_bytes()
                manifest.append(f"{hashlib.sha256(data).hexdigest()}  {relative}")
                archive.write(path, "acquisitions-assistant/" + relative)
            archive.writestr("acquisitions-assistant/RELEASE_FILES.sha256", "\n".join(manifest) + "\n")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(digest + "  " + output.name + "\n", encoding="utf-8")
    print(f"Release: {output.name}; {len(files) + 1} files; {output.stat().st_size:,} bytes")
    print("SHA-256:", digest)
    print("Included: source, tests, documentation, fictional fixtures and prebuilt UI.")
    print("Excluded: all databases, snapshots, private environment/password files, dependencies and logs.")


if __name__ == "__main__":
    main()
