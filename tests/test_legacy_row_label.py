"""The legacy parser must keep a data row's category label when it is a <th>.

Some legacy editions mark the row's leading category cell as <th> rather than <td>
(May/June 2004 are the clearest examples). The legacy row loop read only find_all("td"),
so on those pages the label was dropped and every value shifted one column left: the
"1st" cell vanished and the All-Chargeability date became the visa class. Nothing
raised — the row still had >1 cell, so it was ingested as a plausible-looking row.

That is the dangerous shape here: the failure is silent and lands in served data.
2004-05 and 2004-06 hold 18 cutoff rows each in prod against 52 for 2004-01 and 44 for
2004-07, which is what a shifted, partly-unmappable parse looks like from the outside.
The header row was never affected because it already used find_all(["td", "th"]).
"""

import unittest
from pathlib import Path

from lib.parsing.bulletin.parser import extract_tables_legacy

SAVED_PAGES = Path("data/bulletin/saved_pages")

# Editions whose data rows carry the category label in a <th> (the regression), and
# neighbours that use <td> throughout (must not regress).
_TH_LABEL_EDITIONS = ("may-2004", "june-2004")
_TD_LABEL_EDITIONS = ("january-2004", "april-2004", "july-2004")


def _family_table(edition: str):
    html = (SAVED_PAGES / f"visa-bulletin-for-{edition}.html").read_text(
        encoding="utf-8", errors="ignore"
    )
    for table in extract_tables_legacy(html):
        if table.title == "family_sponsored_final_actions":
            return table
    raise AssertionError(f"no family table parsed from {edition}")


class TestLegacyRowLabelSurvives(unittest.TestCase):
    def test_th_label_rows_keep_their_category(self):
        """A <th> label must survive: the row keeps its class and stays column-aligned."""
        for edition in _TH_LABEL_EDITIONS:
            table = _family_table(edition)
            for row in table.rows:
                self.assertEqual(
                    len(row),
                    len(table.headers),
                    f"{edition}: row {row} has {len(row)} cells but there are "
                    f"{len(table.headers)} headers — the label was dropped and the "
                    f"columns shifted",
                )
            # The leading cell is the visa class, never a date. A shifted row puts the
            # All-Chargeability *date* in this slot, which is the actual corruption.
            first_cells = [row[0] for row in table.rows]
            for cell in first_cells:
                self.assertIsInstance(
                    cell,
                    str,
                    f"{edition}: leading cell {cell!r} is a date, not a visa class — "
                    f"columns are shifted",
                )

    def test_td_label_editions_still_parse(self):
        """The all-<td> neighbours must be unaffected by the <th> fix."""
        for edition in _TD_LABEL_EDITIONS:
            table = _family_table(edition)
            self.assertTrue(table.rows, f"{edition}: no rows")
            for row in table.rows:
                self.assertEqual(len(row), len(table.headers), f"{edition}: {row}")

    def test_every_legacy_family_row_is_column_aligned(self):
        """Sweep: no legacy edition may yield a row whose width misses the headers.

        A shifted row never raises, so width-vs-headers across the whole corpus is the
        cheapest way to catch this class of corruption in editions nobody looked at.
        """
        misaligned = []
        for path in sorted(SAVED_PAGES.glob("*.html")):
            html = path.read_text(encoding="utf-8", errors="ignore")
            for table in extract_tables_legacy(html):
                if table.title != "family_sponsored_final_actions":
                    continue
                for row in table.rows:
                    if len(row) != len(table.headers):
                        misaligned.append(
                            f"{path.name}: {len(row)} cells vs {len(table.headers)} headers"
                        )
                        break
        self.assertEqual(misaligned, [], f"column-shifted legacy rows: {misaligned}")


if __name__ == "__main__":
    unittest.main()
