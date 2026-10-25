r"""Prepare a local, read-only legacy database migration. Approval happens in the UI.

Example (Windows): .venv\Scripts\python.exe scripts\merge_workspaces.py --source "C:\\...\\backend\\acquisitions.db"
No vendor key is needed. Never upload either company database to a chat.
"""

import argparse
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)


def main():
    parser = argparse.ArgumentParser(
        description="Prepare a private, local backup-first workspace review; never auto-merge people"
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Full local path to the GitHub/Next backend/acquisitions.db; original is not modified",
    )
    args = parser.parse_args()
    try:
        from app.main import migrate
        from app.db import SessionLocal
        from app.seed import initialize_defaults
        from app.services.workspace_merge import prepare_merge

        migrate()
        with SessionLocal() as db:
            initialize_defaults(db)
            job = prepare_merge(db, args.source)
            print("Prepared local migration review:", job.id)
            print("Source sellers:", job.counts["source_leads"])
            print("Existing unified records and source database preserved.")
            print("No secret/settings activation, AI request, seller communication or CRM write occurred.")
            print("Start the app and open Import Center > Bring both workspaces together.")
            print("Choose separate/link/skip explicitly; nothing has been merged yet.")
    except (ValueError, OSError, sqlite3.Error) as exc:
        parser.exit(1, "Review preparation stopped: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
