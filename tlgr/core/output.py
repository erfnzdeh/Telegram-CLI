"""Output formatters for JSON, plain (TSV), and human-readable modes."""

from __future__ import annotations

import json
import sys
from typing import Any, Sequence


def _tsv_escape(value: Any) -> str:
    s = str(value) if value is not None else ""
    return s.replace("\t", " ").replace("\n", " ")


def output_json(data: Any, *, flood_wait: int | None = None) -> None:
    """Write JSON to stdout."""
    if flood_wait:
        if isinstance(data, dict):
            data["flood_wait"] = flood_wait
        else:
            data = {"result": data, "flood_wait": flood_wait}
    json.dump(data, sys.stdout, default=str, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.stdout.flush()


def output_plain(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
    """Write TSV to stdout (no colors, stable for piping)."""
    print("\t".join(columns))
    for row in rows:
        print("\t".join(_tsv_escape(row.get(c)) for c in columns))
    sys.stdout.flush()


def output_human(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
    *,
    headers: Sequence[str] | None = None,
) -> None:
    """Write space-padded columns to stdout (kubectl / docker style)."""
    display_headers = headers or columns
    cells = [[str(row.get(c, "")) for c in columns] for row in rows]

    widths = [len(h) for h in display_headers]
    for cell_row in cells:
        for i, v in enumerate(cell_row):
            widths[i] = max(widths[i], len(v))

    gap = "   "
    header_line = gap.join(h.upper().ljust(w) for h, w in zip(display_headers, widths))
    print(header_line.rstrip())
    for cell_row in cells:
        line = gap.join(v.ljust(w) for v, w in zip(cell_row, widths))
        print(line.rstrip())
    sys.stdout.flush()


def output_result(
    data: Any,
    *,
    fmt: str = "human",
    columns: Sequence[str] | None = None,
    headers: Sequence[str] | None = None,
    flood_wait: int | None = None,
) -> None:
    """Dispatch to the correct output formatter.

    *fmt* is one of ``"json"``, ``"plain"``, or ``"human"``.
    For ``"json"`` *data* is emitted as-is.
    For ``"plain"`` and ``"human"`` *data* must be a list of dicts
    and *columns* selects which keys to display.
    """
    if fmt == "json":
        output_json(data, flood_wait=flood_wait)
        return

    if not isinstance(data, list):
        data = [data] if isinstance(data, dict) else [{"result": data}]

    cols = columns or (list(data[0].keys()) if data else ["result"])

    if fmt == "plain":
        output_plain(data, cols)
    else:
        output_human(data, cols, headers=headers)
