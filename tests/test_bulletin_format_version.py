"""Format-version detection for Visa Bulletin pages.

Regression cover for the ten months (2015-01..2015-10) that silently ingested
nothing for years. The bulletin's layout changed with the NOVEMBER 2015 edition, but
the format boundary was year-only (``year < 2015 -> LEGACY``), so every 2015 edition
was classified MODERN. The modern extractor finds zero tables in the legacy layout,
so ``transform()`` never ran, no ``Bulletin`` row was created, and the run failed far
downstream with "Bulletin not found for publication date" — a message that points at
the database rather than the parser. Each of those ten sources accrued ~1,190 FAILED
ingest runs before the retry gate parked them.

The load-bearing test here is ``test_every_bulletin_parses_under_its_format``: it
asserts the property the boundary exists to guarantee — the format we pick must
actually be able to read the page — across the whole committed corpus, rather than
restating the boundary constant. It fails on exactly those ten files under the old
rule and passes on all 291 under the new one.
"""

import re
import unittest
from datetime import datetime
from pathlib import Path

from lib.ingest.plugins.visa_bulletin import (
    MODERN_FORMAT_START,
    VisaBulletinPlugin,
    format_version_for_bulletin,
)
from lib.parsing.bulletin.parser import extract_tables_legacy, extract_tables_modern
from models.ingest.enums import FormatVersion

SAVED_PAGES = Path("data/bulletin/saved_pages")
_SLUG_RE = re.compile(r"visa-bulletin-for-([a-z]+)-(\d{4})", re.IGNORECASE)

_BASE = "https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin"


class TestFormatVersionForBulletin(unittest.TestCase):
    def test_boundary_is_november_2015_not_january(self):
        """The layout changed with the Nov-2015 edition; Jan-Oct 2015 are still legacy."""
        self.assertEqual(MODERN_FORMAT_START, (2015, 11))

        for month in (
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october",
        ):
            url = f"{_BASE}/2015/visa-bulletin-for-{month}-2015.html"
            self.assertEqual(
                format_version_for_bulletin(url),
                FormatVersion.LEGACY,
                f"{month}-2015 predates the Nov-2015 layout change",
            )

        for month in ("november", "december"):
            url = f"{_BASE}/2016/visa-bulletin-for-{month}-2015.html"
            self.assertEqual(
                format_version_for_bulletin(url),
                FormatVersion.MODERN,
                f"{month}-2015 is the new layout",
            )

    def test_fiscal_year_directory_does_not_override_the_bulletin_year(self):
        """Oct-Dec editions live under FY=year+1; a bare \\d{4} scan reads the wrong year."""
        # FY dir says 2016, but the October-2015 bulletin is still the legacy layout.
        self.assertEqual(
            format_version_for_bulletin(
                f"{_BASE}/2016/visa-bulletin-for-october-2015.html"
            ),
            FormatVersion.LEGACY,
        )

    def test_surrounding_years(self):
        self.assertEqual(
            format_version_for_bulletin(f"{_BASE}/2015/visa-bulletin-for-december-2014.html"),
            FormatVersion.LEGACY,
        )
        self.assertEqual(
            format_version_for_bulletin(f"{_BASE}/2004/visa-bulletin-for-april-2004.html"),
            FormatVersion.LEGACY,
        )
        self.assertEqual(
            format_version_for_bulletin(f"{_BASE}/2026/visa-bulletin-for-july-2026.html"),
            FormatVersion.MODERN,
        )

    def test_unparseable_slug_is_unknown_so_parse_auto_detects(self):
        """UNKNOWN makes parse() auto-detect, which beats committing to a guess."""
        for bad in ("garbage.html", "visa-bulletin-for-smarch-2015.html", ""):
            self.assertEqual(format_version_for_bulletin(bad), FormatVersion.UNKNOWN, bad)

    def test_plugin_get_format_version_uses_the_same_rule(self):
        plugin = VisaBulletinPlugin()
        self.assertEqual(
            plugin.get_format_version(Path("visa-bulletin-for-july-2015.html")),
            FormatVersion.LEGACY,
        )
        self.assertEqual(
            plugin.get_format_version(Path("visa-bulletin-for-november-2015.html")),
            FormatVersion.MODERN,
        )


class TestCorpusParsesUnderClassifiedFormat(unittest.TestCase):
    """The property the boundary exists to guarantee, asserted over every saved page."""

    def test_every_bulletin_parses_under_its_format(self):
        files = sorted(SAVED_PAGES.glob("*.html"))
        self.assertGreater(len(files), 250, "saved_pages corpus missing")

        extractors = {
            FormatVersion.LEGACY: extract_tables_legacy,
            FormatVersion.MODERN: extract_tables_modern,
        }
        zero_table_files = []
        for path in files:
            if not _SLUG_RE.search(path.name):
                continue
            fmt = format_version_for_bulletin(path.name)
            self.assertIn(fmt, extractors, f"{path.name} classified {fmt}")
            html = path.read_text(encoding="utf-8", errors="ignore")
            if not extractors[fmt](html):
                zero_table_files.append(path.name)

        self.assertEqual(
            zero_table_files,
            [],
            "These bulletins extract ZERO tables under their classified format, so they "
            "would ingest no cutoff rows and fail with a misleading 'Bulletin not found': "
            f"{zero_table_files}",
        )

    def test_old_year_only_boundary_would_still_fail(self):
        """Pin the bug: the retired rule breaks exactly the ten 2015 editions."""
        broken = []
        for path in sorted(SAVED_PAGES.glob("*.html")):
            match = _SLUG_RE.search(path.name)
            if not match:
                continue
            year = int(match.group(2))
            old_fmt = FormatVersion.LEGACY if year < 2015 else FormatVersion.MODERN
            extract = (
                extract_tables_legacy
                if old_fmt == FormatVersion.LEGACY
                else extract_tables_modern
            )
            if not extract(path.read_text(encoding="utf-8", errors="ignore")):
                broken.append(datetime.strptime(
                    "-".join(match.groups()), "%B-%Y"
                ).strftime("%Y-%m"))

        self.assertEqual(
            sorted(broken),
            [f"2015-{m:02d}" for m in range(1, 11)],
            "the year-only boundary is expected to break exactly 2015-01..2015-10",
        )


if __name__ == "__main__":
    unittest.main()
