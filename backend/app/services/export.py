"""CSV export helpers with spreadsheet formula-injection protection."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Iterable, Sequence

from app.services.normalization import csv_safe


def rows_to_csv(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow([csv_safe(h) for h in headers])
    for row in rows:
        writer.writerow([csv_safe(cell) for cell in row])
    return buffer.getvalue()


def export_filename(prefix: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}.csv"
