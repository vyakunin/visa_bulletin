"""
Unit tests for data_source_utils module.

Tests that verify:
1. get_data_source_filepath validates and returns file paths
2. get_file_stats analyzes Excel and CSV files correctly
3. count_file_rows extracts row counts correctly
4. Caching works for both new (dict) and old (int) formats
5. Backwards compatibility with old cache format
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from lib.utils.data_source_utils import (
    _get_cache_file_path,
    count_file_rows,
    get_data_source_filepath,
    get_file_stats,
    get_fiscal_year_from_filename,
    get_source_file_date,
)


class TestDataSourceUtils(unittest.TestCase):
    """Test data source utility functions"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_excel_file = self.temp_dir / "test.xlsx"
        self.test_csv_file = self.temp_dir / "test.csv"
        self.test_csv_content = "header1,header2,header3\nrow1_col1,row1_col2,row1_col3\nrow2_col1,row2_col2,row2_col3\nrow3_col1,row3_col2,row3_col3\n"

        # Create test CSV file
        with open(self.test_csv_file, "w") as f:
            f.write(self.test_csv_content)

        # Create test Excel file (empty, will be mocked)
        self.test_excel_file.touch()

        # Use isolated cache file for tests (in temp directory)
        # This prevents tests from interfering with production cache
        self.test_cache_file = self.temp_dir / "test_file_counts_cache.json"
        os.environ["FILE_STATS_CACHE_PATH"] = str(self.test_cache_file)

        # Reset cache state (forces reload with new cache path)
        import lib.utils.data_source_utils as dsu_module

        dsu_module._file_stats_cache = None
        dsu_module._cache_file_path = None

    def tearDown(self):
        """Clean up test fixtures"""
        # Remove environment variable override
        os.environ.pop("FILE_STATS_CACHE_PATH", None)

        # Reset cache state
        import lib.utils.data_source_utils as dsu_module

        dsu_module._file_stats_cache = None
        dsu_module._cache_file_path = None

        # Clean up temp directory (includes test cache file)
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_data_source_filepath_with_valid_path(self):
        """Test get_data_source_filepath returns path for valid file"""
        source = Mock()
        source.local_file_path = str(self.test_csv_file)

        result = get_data_source_filepath(source)

        self.assertIsNotNone(result)
        self.assertEqual(result, self.test_csv_file)
        self.assertTrue(result.exists())

    def test_get_data_source_filepath_with_none_path(self):
        """Test get_data_source_filepath returns None for missing local_file_path"""
        source = Mock()
        source.local_file_path = None

        result = get_data_source_filepath(source)

        self.assertIsNone(result)

    def test_get_data_source_filepath_with_nonexistent_file(self):
        """Test get_data_source_filepath returns None for non-existent file"""
        source = Mock()
        source.local_file_path = str(self.temp_dir / "nonexistent.xlsx")

        result = get_data_source_filepath(source)

        self.assertIsNone(result)

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_get_file_stats_excel(self, mock_load_workbook):
        """Test get_file_stats for Excel files"""
        # Mock workbook and worksheet
        mock_ws = Mock()
        mock_ws.max_row = 101  # 100 data rows + 1 header
        mock_ws.__getitem__ = Mock(
            return_value=[
                Mock(value="Header1"),
                Mock(value="Header2"),
                Mock(value="Header3"),
            ]
        )

        mock_wb = Mock()
        mock_wb.active = mock_ws
        mock_load_workbook.return_value = mock_wb

        result = get_file_stats(self.test_excel_file)

        self.assertIsNotNone(result)
        self.assertEqual(result["filename"], "test.xlsx")
        self.assertEqual(result["row_count"], 100)  # max_row - 1
        self.assertEqual(result["columns"], ["Header1", "Header2", "Header3"])
        self.assertIn("filepath", result)
        self.assertIn("size_bytes", result)

        # Verify workbook was closed
        mock_wb.close.assert_called_once()

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_get_file_stats_excel_with_empty_rows(self, mock_load_workbook):
        """Test get_file_stats for Excel files with no data rows"""
        mock_ws = Mock()
        mock_ws.max_row = 1  # Only header row
        mock_ws.__getitem__ = Mock(
            return_value=[
                Mock(value="Header1"),
            ]
        )

        mock_wb = Mock()
        mock_wb.active = mock_ws
        mock_load_workbook.return_value = mock_wb

        result = get_file_stats(self.test_excel_file)

        self.assertIsNotNone(result)
        self.assertEqual(result["row_count"], 0)

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_get_file_stats_excel_with_none_max_row(self, mock_load_workbook):
        """Test get_file_stats for Excel files with None max_row"""
        mock_ws = Mock()
        mock_ws.max_row = None
        mock_ws.__getitem__ = Mock(return_value=[])

        mock_wb = Mock()
        mock_wb.active = mock_ws
        mock_load_workbook.return_value = mock_wb

        result = get_file_stats(self.test_excel_file)

        self.assertIsNotNone(result)
        self.assertEqual(result["row_count"], 0)

    def test_get_file_stats_csv(self):
        """Test get_file_stats for CSV files"""
        result = get_file_stats(self.test_csv_file)

        self.assertEqual(result["filename"], "test.csv")
        self.assertEqual(result["row_count"], 3)  # 3 data rows (excluding header)
        self.assertEqual(result["columns"], ["header1", "header2", "header3"])
        self.assertIn("filepath", result)
        self.assertIn("size_bytes", result)

    def test_get_file_stats_nonexistent_file(self):
        """Test get_file_stats raises FileNotFoundError for non-existent file"""
        nonexistent = self.temp_dir / "nonexistent.xlsx"

        with self.assertRaises(FileNotFoundError):
            get_file_stats(nonexistent)

    def test_get_file_stats_unknown_file_type(self):
        """Test get_file_stats raises ValueError for unknown file type"""
        unknown_file = self.temp_dir / "test.txt"
        unknown_file.write_text("some content")

        with self.assertRaises(ValueError) as context:
            get_file_stats(unknown_file)

        self.assertIn("Unknown file type", str(context.exception))

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_get_file_stats_caching(self, mock_load_workbook):
        """Test get_file_stats caches results"""
        mock_ws = Mock()
        mock_ws.max_row = 101
        mock_ws.__getitem__ = Mock(
            return_value=[
                Mock(value="Header1"),
            ]
        )

        mock_wb = Mock()
        mock_wb.active = mock_ws
        mock_load_workbook.return_value = mock_wb

        # First call - should analyze file
        result1 = get_file_stats(self.test_excel_file)

        # Verify load_workbook was called on first call
        self.assertEqual(mock_load_workbook.call_count, 1)

        # Second call - should use cache (load_workbook should not be called again)
        mock_load_workbook.reset_mock()
        result2 = get_file_stats(self.test_excel_file)

        self.assertEqual(result1, result2)
        # load_workbook should not be called again (using cache)
        self.assertEqual(mock_load_workbook.call_count, 0)

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_count_file_rows_excel(self, mock_load_workbook):
        """Test count_file_rows for Excel files"""
        mock_ws = Mock()
        mock_ws.max_row = 101  # 100 data rows + 1 header

        mock_wb = Mock()
        mock_wb.active = mock_ws
        mock_load_workbook.return_value = mock_wb

        result = count_file_rows(self.test_excel_file)

        self.assertEqual(result, 100)  # max_row - 1

    def test_count_file_rows_csv(self):
        """Test count_file_rows for CSV files"""
        result = count_file_rows(self.test_csv_file)

        self.assertEqual(result, 3)  # 3 data rows (excluding header)

    def test_count_file_rows_nonexistent_file(self):
        """Test count_file_rows raises FileNotFoundError for non-existent file"""
        nonexistent = self.temp_dir / "nonexistent.xlsx"

        with self.assertRaises(FileNotFoundError):
            count_file_rows(nonexistent)

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_count_file_rows_caching(self, mock_load_workbook):
        """Test count_file_rows caches results"""
        mock_ws = Mock()
        mock_ws.max_row = 101

        mock_wb = Mock()
        mock_wb.active = mock_ws
        mock_load_workbook.return_value = mock_wb

        # First call - should analyze file
        result1 = count_file_rows(self.test_excel_file)

        # Second call - should use cache
        mock_load_workbook.reset_mock()
        result2 = count_file_rows(self.test_excel_file)

        self.assertEqual(result1, result2)
        # load_workbook should only be called once (first time, via get_file_stats)
        self.assertEqual(mock_load_workbook.call_count, 0)  # Cached, so not called

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_count_file_rows_backwards_compatibility_old_cache_format(
        self, mock_load_workbook
    ):
        """Test count_file_rows handles old cache format (int) for backwards compatibility"""
        # Manually set up cache with old format (int)
        cache_path = _get_cache_file_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_key = self.test_excel_file.as_uri()
        old_cache = {cache_key: 42}  # Old format: just int

        with open(cache_path, "w") as f:
            json.dump(old_cache, f)

        # Reset cache state to force reload
        import lib.utils.data_source_utils as dsu_module

        dsu_module._file_stats_cache = None

        # Should use cached int value directly
        result = count_file_rows(self.test_excel_file)

        self.assertEqual(result, 42)
        # Should not call load_workbook since we used cached int
        mock_load_workbook.assert_not_called()

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_count_file_rows_new_cache_format(self, mock_load_workbook):
        """Test count_file_rows handles new cache format (dict)"""
        # Manually set up cache with new format (dict)
        cache_path = _get_cache_file_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_key = self.test_excel_file.as_uri()
        new_cache = {
            cache_key: {
                "filepath": str(self.test_excel_file),
                "filename": "test.xlsx",
                "size_bytes": 1000,
                "row_count": 99,
                "columns": ["Header1"],
            }
        }

        with open(cache_path, "w") as f:
            json.dump(new_cache, f)

        # Reset cache state to force reload
        import lib.utils.data_source_utils as dsu_module

        dsu_module._file_stats_cache = None

        # Should extract row_count from cached dict
        result = count_file_rows(self.test_excel_file)

        self.assertEqual(result, 99)
        # Should not call load_workbook since we used cached dict
        mock_load_workbook.assert_not_called()

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_get_file_stats_with_cache_cleared(self, mock_load_workbook):
        """Test get_file_stats re-analyzes when cache is cleared"""
        mock_ws = Mock()
        mock_ws.max_row = 101
        mock_ws.__getitem__ = Mock(return_value=[Mock(value="Header1")])

        mock_wb = Mock()
        mock_wb.active = mock_ws
        mock_load_workbook.return_value = mock_wb

        # First call - should cache result
        result1 = get_file_stats(self.test_excel_file)
        self.assertEqual(mock_load_workbook.call_count, 1)

        # Clear cache
        import lib.utils.data_source_utils as dsu_module

        dsu_module._file_stats_cache = {}
        cache_path = _get_cache_file_path()
        if cache_path.exists():
            cache_path.unlink()

        # Second call after cache cleared - should analyze again
        mock_load_workbook.reset_mock()
        result2 = get_file_stats(self.test_excel_file)

        self.assertEqual(result1, result2)
        # load_workbook should be called again (cache was cleared)
        self.assertEqual(mock_load_workbook.call_count, 1)

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_count_file_rows_with_cache_cleared(self, mock_load_workbook):
        """Test count_file_rows re-analyzes when cache is cleared"""
        mock_ws = Mock()
        mock_ws.max_row = 101

        mock_wb = Mock()
        mock_wb.active = mock_ws
        mock_load_workbook.return_value = mock_wb

        # First call - should cache result
        result1 = count_file_rows(self.test_excel_file)
        self.assertEqual(mock_load_workbook.call_count, 1)

        # Clear cache
        import lib.utils.data_source_utils as dsu_module

        dsu_module._file_stats_cache = {}
        cache_path = _get_cache_file_path()
        if cache_path.exists():
            cache_path.unlink()

        # Second call after cache cleared - should analyze again
        mock_load_workbook.reset_mock()
        result2 = count_file_rows(self.test_excel_file)

        self.assertEqual(result1, result2)
        # load_workbook should be called again (cache was cleared, via get_file_stats)
        self.assertEqual(mock_load_workbook.call_count, 1)

    @patch("lib.utils.data_source_utils.load_workbook")
    def test_get_file_stats_excel_error_handling(self, mock_load_workbook):
        """Test get_file_stats raises exception when Excel loading fails"""
        mock_load_workbook.side_effect = Exception("Failed to load workbook")

        with self.assertRaises(Exception) as context:
            get_file_stats(self.test_excel_file)

        self.assertIn("Failed to load workbook", str(context.exception))

    def test_get_file_stats_csv_error_handling(self):
        """Test get_file_stats raises exception when CSV parsing fails"""
        # Create a file that will cause CSV parsing to fail
        # Actually, csv.reader is quite tolerant, so let's test with a file that doesn't exist
        bad_csv = self.temp_dir / "bad.csv"
        # Don't create the file - this will raise FileNotFoundError

        with self.assertRaises(FileNotFoundError):
            get_file_stats(bad_csv)

    def test_get_fiscal_year_from_filename(self):
        """Test fiscal year extraction from filename"""
        # Standard filenames with FY pattern
        self.assertEqual(get_fiscal_year_from_filename("LCA_FY2024_Q4.csv"), 2024)
        self.assertEqual(get_fiscal_year_from_filename("PERM_FY2023.csv"), 2023)
        self.assertEqual(
            get_fiscal_year_from_filename("H-1B_Disclosure_Data_FY2018_EOY.xlsx"), 2018
        )

        # Filenames with year pattern (no FY)
        self.assertEqual(get_fiscal_year_from_filename("test_2024_data.csv"), 2024)
        self.assertEqual(get_fiscal_year_from_filename("data_2019.xlsx"), 2019)

        # Artificial filenames (no year) - should return None
        self.assertIsNone(get_fiscal_year_from_filename("lca_367.xlsx"))
        self.assertIsNone(get_fiscal_year_from_filename("perm_123.xlsx"))
        self.assertIsNone(get_fiscal_year_from_filename("no_year.csv"))

        # Artificial filename with URL fallback - should extract from URL
        self.assertIsNone(
            get_fiscal_year_from_filename("lca_367.xlsx", fallback_url=None)
        )
        self.assertEqual(
            get_fiscal_year_from_filename(
                "lca_367.xlsx",
                fallback_url="https://example.com/H-1B_Disclosure_Data_FY2018_EOY.xlsx",
            ),
            2018,
        )
        self.assertEqual(
            get_fiscal_year_from_filename(
                "lca_369.xlsx",
                fallback_url="https://dol.gov/data/H-1B_Disclosure_Data_FY2019.xlsx",
            ),
            2019,
        )

        # URL fallback with file:// scheme
        self.assertEqual(
            get_fiscal_year_from_filename(
                "lca_366.xlsx", fallback_url="file://H-1B_Case_Data_FY2009.xlsx"
            ),
            2009,
        )

        # URL fallback with year pattern (no FY)
        self.assertEqual(
            get_fiscal_year_from_filename(
                "perm_123.xlsx", fallback_url="https://example.com/PERM_2010.xlsx"
            ),
            2010,
        )

        # 2-digit fiscal years (FY17 = 2017, FY16 = 2016, FY14 = 2014)
        self.assertEqual(
            get_fiscal_year_from_filename("H-1B_Disclosure_Data_FY17.xlsx"), 2017
        )
        self.assertEqual(
            get_fiscal_year_from_filename("H-1B_Disclosure_Data_FY16.xlsx"), 2016
        )
        # Test FY## followed by underscore (was failing with \b word boundary)
        self.assertEqual(get_fiscal_year_from_filename("H-1B_FY14_Q4.xlsx"), 2014)
        self.assertEqual(get_fiscal_year_from_filename("PERM_FY09.xlsx"), 2009)
        # Test FY## at end of filename
        self.assertEqual(get_fiscal_year_from_filename("LCA_FY17.xlsx"), 2017)
        # Test FY## followed by period
        self.assertEqual(get_fiscal_year_from_filename("Data_FY16.csv"), 2016)

        # 2-digit fiscal years in URL fallback
        self.assertEqual(
            get_fiscal_year_from_filename(
                "lca_362.xlsx", fallback_url="file://H-1B_Disclosure_Data_FY17.xlsx"
            ),
            2017,
        )

        # reimport:// URL scheme (4-digit year)
        self.assertEqual(
            get_fiscal_year_from_filename(
                "lca_368.xlsx",
                fallback_url="reimport:///path/to/H-1B_Disclosure_Data_FY2015.xlsx",
            ),
            2015,
        )

        # reimport:// URL scheme (2-digit year)
        self.assertEqual(
            get_fiscal_year_from_filename(
                "lca_365.xlsx", fallback_url="reimport:///path/to/H-1B_FY14_Q4.xlsx"
            ),
            2014,
        )

    def test_get_source_file_date_mtime_matches_year(self):
        """Test get_source_file_date when mtime year matches extracted fiscal year"""
        import os
        from datetime import datetime

        from django.utils import timezone

        from models.ingest.data_source import DataSource
        from models.ingest.enums import DataDomain, FormatVersion, SourceType

        # Create a test file with FY2024 in name
        test_file = self.temp_dir / "LCA_FY2024_Q4.xlsx"
        test_file.touch()

        # Set mtime to 2024 (matches fiscal year)
        target_time = datetime(2024, 6, 15, 10, 30, 0)
        if timezone.is_naive(target_time):
            target_time = timezone.make_aware(target_time)
        os.utime(test_file, (target_time.timestamp(), target_time.timestamp()))

        # Create DataSource
        data_source = DataSource(
            url=f"file://{test_file.name}",
            domain=DataDomain.DOL.value,
            source_type=SourceType.LCA.value,
            format_version=FormatVersion.MODERN.value,
        )

        result = get_source_file_date(test_file, data_source)

        # Should use mtime since year matches
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2024)
        # Should be close to the mtime we set (within 1 second)
        self.assertAlmostEqual(result.timestamp(), target_time.timestamp(), delta=1)

    def test_get_source_file_date_mtime_mismatch_uses_jan_1(self):
        """Test get_source_file_date when mtime year doesn't match extracted fiscal year"""
        import os
        from datetime import datetime

        from django.utils import timezone

        from models.ingest.data_source import DataSource
        from models.ingest.enums import DataDomain, FormatVersion, SourceType

        # Create a test file with FY2024 in name
        test_file = self.temp_dir / "LCA_FY2024_Q4.xlsx"
        test_file.touch()

        # Set mtime to 2025 (doesn't match fiscal year 2024)
        target_time = datetime(2025, 6, 15, 10, 30, 0)
        if timezone.is_naive(target_time):
            target_time = timezone.make_aware(target_time)
        os.utime(test_file, (target_time.timestamp(), target_time.timestamp()))

        # Create DataSource
        data_source = DataSource(
            url=f"file://{test_file.name}",
            domain=DataDomain.DOL.value,
            source_type=SourceType.LCA.value,
            format_version=FormatVersion.MODERN.value,
        )

        result = get_source_file_date(test_file, data_source)

        # Should use January 1st of extracted year (2024) since mtime doesn't match
        self.assertIsNotNone(result)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 1)

    def test_get_source_file_date_no_fiscal_year_uses_mtime(self):
        """Test get_source_file_date when no fiscal year can be extracted"""
        import os
        from datetime import datetime

        from django.utils import timezone

        from models.ingest.data_source import DataSource
        from models.ingest.enums import DataDomain, FormatVersion, SourceType

        # Create a test file without fiscal year in name
        test_file = self.temp_dir / "test_file.xlsx"
        test_file.touch()

        # Set mtime
        target_time = datetime(2024, 6, 15, 10, 30, 0)
        if timezone.is_naive(target_time):
            target_time = timezone.make_aware(target_time)
        os.utime(test_file, (target_time.timestamp(), target_time.timestamp()))

        # Create DataSource
        data_source = DataSource(
            url=f"file://{test_file.name}",
            domain=DataDomain.DOL.value,
            source_type=SourceType.LCA.value,
            format_version=FormatVersion.MODERN.value,
        )

        result = get_source_file_date(test_file, data_source)

        # Should use mtime since no fiscal year available
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.timestamp(), target_time.timestamp(), delta=1)

    def test_get_source_file_date_fallback_to_downloaded_at(self):
        """Test get_source_file_date falls back to DataSource.downloaded_at"""
        from datetime import datetime

        from django.utils import timezone

        from models.ingest.data_source import DataSource
        from models.ingest.enums import DataDomain, FormatVersion, SourceType

        # Create a test file that doesn't exist (no mtime)
        test_file = self.temp_dir / "nonexistent.xlsx"

        # Create DataSource with downloaded_at
        downloaded_time = datetime(2024, 3, 1, 12, 0, 0)
        if timezone.is_naive(downloaded_time):
            downloaded_time = timezone.make_aware(downloaded_time)

        data_source = DataSource(
            url=f"file://{test_file.name}",
            domain=DataDomain.DOL.value,
            source_type=SourceType.LCA.value,
            format_version=FormatVersion.MODERN.value,
            downloaded_at=downloaded_time,
        )

        result = get_source_file_date(test_file, data_source)

        # Should use downloaded_at as fallback
        self.assertIsNotNone(result)
        self.assertEqual(result, downloaded_time)
