#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Print the Final Action / Dates for Filing history for one preference + country.

Reads the archived DoS bulletin HTML in ``data/bulletin/saved_pages/`` and emits a
month-by-month series, so a claim about how a category has moved can be sourced from
the archive instead of from memory.

Inputs
------
--pref     Row label in the employment/family table ("2nd", "1st", "3rd",
           "Other Workers", "F2A", ...). Matched case-insensitively on a prefix.
--country  Column: row | china | india | mexico | philippines  (default: row,
           i.e. "All Chargeability Areas Except Those Listed").
--chart    final | filing   (default: final). "filing" reads the second (Dates for
           Filing) table on the page.
--from / --to   Inclusive YYYY-MM bounds (default: everything on disk).
--pages    Override the saved_pages dir.

Output
------
One ``YYYY-MM  <date>`` line per bulletin, oldest first, to stdout. Months whose
page is missing or unparseable are reported on stderr and skipped. Exit 1 if no
rows matched at all.

Prereqs: the archive must be populated (``data/bulletin/saved_pages/*.html``).

Examples
--------
    uv run scripts/bulletin/fad_history.py --pref 2nd --country row --from 2022-01
    uv run scripts/bulletin/fad_history.py --pref 1st --country india --from 2025-10
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

COLUMNS = {"row": 1, "china": 2, "india": 3, "mexico": 4, "philippines": 5}

DEFAULT_PAGES = Path(__file__).resolve().parents[2] / "data" / "bulletin" / "saved_pages"

_TABLE_RE = re.compile(r"<table.*?</table>", re.S | re.I)
_ROW_RE = re.compile(r"<tr.*?</tr>", re.S | re.I)
_CELL_RE = re.compile(r"<t[dh].*?</t[dh]>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _cells(row_html: str) -> list[str]:
    out = []
    for cell in _CELL_RE.findall(row_html):
        text = html.unescape(_TAG_RE.sub("", cell))
        out.append(re.sub(r"\s+", " ", text).strip())
    return out


def _preference_tables(page: str) -> list[list[list[str]]]:
    """Every table that looks like a preference chart, as lists of cell-rows."""
    tables = []
    for match in _TABLE_RE.finditer(page):
        rows = [_cells(r) for r in _ROW_RE.findall(match.group(0))]
        rows = [r for r in rows if r and any(r)]
        # A preference chart has a header naming the chargeability columns.
        if any("chargeability" in " ".join(r).lower() for r in rows):
            tables.append(rows)
    return tables


def _lookup(rows: list[list[str]], pref: str, col: int) -> str | None:
    want = pref.lower().replace(" ", "")
    for row in rows:
        label = row[0].lower().replace(" ", "").replace("-", "")
        if label.startswith(want) and len(row) > col:
            return row[col]
    return None


def _page_path(pages: Path, year: int, month: int) -> Path:
    return pages / f"visa-bulletin-for-{MONTHS[month - 1]}-{year}.html"


def _iter_months(start: tuple[int, int], end: tuple[int, int]):
    year, month = start
    while (year, month) <= end:
        yield year, month
        month += 1
        if month == 13:
            year, month = year + 1, 1


def _parse_ym(value: str) -> tuple[int, int]:
    year, month = value.split("-")
    return int(year), int(month)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pref", default="2nd")
    ap.add_argument("--country", default="row", choices=sorted(COLUMNS))
    ap.add_argument("--chart", default="final", choices=["final", "filing"])
    ap.add_argument("--from", dest="start", default=None, help="YYYY-MM")
    ap.add_argument("--to", dest="end", default=None, help="YYYY-MM")
    ap.add_argument("--pages", type=Path, default=DEFAULT_PAGES)
    args = ap.parse_args()

    if not args.pages.is_dir():
        print(f"no saved_pages dir at {args.pages}", file=sys.stderr)
        return 1

    available = sorted(
        (y, m)
        for y in range(1990, 2100)
        for m in range(1, 13)
        if _page_path(args.pages, y, m).exists()
    )
    if not available:
        print(f"no bulletin pages found in {args.pages}", file=sys.stderr)
        return 1

    start = _parse_ym(args.start) if args.start else available[0]
    end = _parse_ym(args.end) if args.end else available[-1]
    table_index = 0 if args.chart == "final" else 1

    found = 0
    for year, month in _iter_months(start, end):
        path = _page_path(args.pages, year, month)
        if not path.exists():
            continue
        tables = _preference_tables(path.read_text(encoding="utf-8", errors="replace"))
        # Employment charts follow the family ones; take the last pair on the page
        # so "2nd" resolves to employment-based rather than F2.
        emp = [t for t in tables if any(
            r[0].lower().startswith("other workers") for r in t)]
        pool = emp or tables
        if len(pool) <= table_index:
            print(f"{year}-{month:02d}: no {args.chart} chart", file=sys.stderr)
            continue
        value = _lookup(pool[table_index], args.pref, COLUMNS[args.country])
        if value is None:
            print(f"{year}-{month:02d}: no row {args.pref!r}", file=sys.stderr)
            continue
        print(f"{year}-{month:02d}  {value}")
        found += 1

    if not found:
        print("no rows matched", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
