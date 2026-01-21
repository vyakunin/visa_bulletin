#!/usr/bin/env python3
"""
Smoke test for DoL file parsing.

Tests that the parsing logic can successfully parse sample rows from representative DoL files.
This catches regressions in parsing logic before full ingestion.
"""

import os
import sys
import unittest
from pathlib import Path

# Setup Django
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from lib.ingest.registry import PluginRegistry
from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin
from models.ingest.data_source import DataSource
from models.ingest.ingest_run import IngestRun
from models.ingest.enums import IngestStatus, IngestStage
from lib.utils.http_utils import get_workspace_dir


class TestDolParsingSmokeTest(unittest.TestCase):
    """Smoke test to validate DoL file parsing logic"""

    @classmethod
    def setUpClass(cls):
        """Register plugins once for all tests"""
        PluginRegistry.register(H1BSalaryDataSourcePlugin(skip_clustering=True))
        PluginRegistry.register(PERMSalaryDataSourcePlugin(skip_clustering=True))
        cls.workspace_dir = get_workspace_dir()

    def _validate_file(self, filename: str, domain: str, source_type: str, sample_rows: int = 5) -> dict:
        """
        Parse and validate a sample of rows from a file.
        
        Returns:
            dict with keys: success, parsed_count, transformed_count, errors
        """
        file_path = self.workspace_dir / 'data' / 'salary' / 'dol_data' / filename
        
        if not file_path.exists():
            return {
                'success': False,
                'parsed_count': 0,
                'transformed_count': 0,
                'errors': [f'File not found: {filename}']
            }
        
        plugin = PluginRegistry.get_plugin(domain, source_type)
        self.assertIsNotNone(plugin, f'No plugin found for {domain}:{source_type}')
        
        # Create mock source and run
        mock_source = DataSource(
            url=f'file://{file_path}',
            domain=domain,
            source_type=source_type,
            local_file_path=str(file_path)
        )
        
        mock_run = IngestRun(
            source=mock_source,
            status=IngestStatus.RUNNING,
            stage=IngestStage.PARSING,
            checkpoint={'filepath': str(file_path)}
        )
        
        parsed_count = 0
        transformed_count = 0
        errors = []
        
        try:
            for idx, parsed_record in enumerate(plugin.parse(file_path, mock_run)):
                if idx >= sample_rows:
                    break
                
                parsed_count += 1
                
                try:
                    model_instance = plugin.transform(parsed_record)
                    if model_instance:
                        transformed_count += 1
                        
                        # Validate required fields
                        if not getattr(model_instance, 'case_number', None):
                            errors.append(f'{filename} row {idx+1}: Missing case_number')
                        if hasattr(model_instance, 'employer_name') and not getattr(model_instance, 'employer_name', None):
                            errors.append(f'{filename} row {idx+1}: Missing employer_name')
                        if not getattr(model_instance, 'job_title', None):
                            errors.append(f'{filename} row {idx+1}: Missing job_title')
                except Exception as e:
                    errors.append(f'{filename} row {idx+1}: Transform failed - {str(e)}')
        
        except Exception as e:
            errors.append(f'{filename}: Parse failed - {str(e)}')
        
        return {
            'success': len(errors) == 0 and transformed_count > 0,
            'parsed_count': parsed_count,
            'transformed_count': transformed_count,
            'errors': errors
        }

    def test_perm_fy2020(self):
        """Test parsing of PERM FY2020 file (older format)"""
        file_path = self.workspace_dir / 'data' / 'salary' / 'dol_data' / 'PERM_FY2020.xlsx'
        if not file_path.exists():
            self.skipTest(f'Data file not available: {file_path}')
        
        result = self._validate_file('PERM_FY2020.xlsx', 'dol', 'perm')
        self.assertTrue(result['success'], f"PERM FY2020 parsing failed: {result['errors']}")
        self.assertGreater(result['transformed_count'], 0, 'No records transformed from PERM FY2020')
        self.assertEqual(result['parsed_count'], 5, 'Expected 5 parsed records')

    def test_perm_fy2024_q4(self):
        """Test parsing of PERM FY2024 Q4 file (recent format)"""
        file_path = self.workspace_dir / 'data' / 'salary' / 'dol_data' / 'PERM_Disclosure_Data_FY2024_Q4.xlsx'
        if not file_path.exists():
            self.skipTest(f'Data file not available: {file_path}')
        
        result = self._validate_file('PERM_Disclosure_Data_FY2024_Q4.xlsx', 'dol', 'perm')
        self.assertTrue(result['success'], f"PERM FY2024 Q4 parsing failed: {result['errors']}")
        self.assertGreater(result['transformed_count'], 0, 'No records transformed from PERM FY2024 Q4')
        self.assertEqual(result['parsed_count'], 5, 'Expected 5 parsed records')

    def test_lca_fy2020(self):
        """Test parsing of LCA FY2020 file (older format)"""
        file_path = self.workspace_dir / 'data' / 'salary' / 'dol_data' / 'LCA_Disclosure_Data_FY2020.xlsx'
        if not file_path.exists():
            self.skipTest(f'Data file not available: {file_path}')
        
        result = self._validate_file('LCA_Disclosure_Data_FY2020.xlsx', 'dol', 'lca')
        self.assertTrue(result['success'], f"LCA FY2020 parsing failed: {result['errors']}")
        self.assertGreater(result['transformed_count'], 0, 'No records transformed from LCA FY2020')
        self.assertEqual(result['parsed_count'], 5, 'Expected 5 parsed records')

    def test_lca_fy2024_q4(self):
        """Test parsing of LCA FY2024 Q4 file (recent format)"""
        file_path = self.workspace_dir / 'data' / 'salary' / 'dol_data' / 'LCA_Disclosure_Data_FY2024_Q4.xlsx'
        if not file_path.exists():
            self.skipTest(f'Data file not available: {file_path}')
        
        result = self._validate_file('LCA_Disclosure_Data_FY2024_Q4.xlsx', 'dol', 'lca')
        self.assertTrue(result['success'], f"LCA FY2024 Q4 parsing failed: {result['errors']}")
        self.assertGreater(result['transformed_count'], 0, 'No records transformed from LCA FY2024 Q4')
        self.assertEqual(result['parsed_count'], 5, 'Expected 5 parsed records')


if __name__ == '__main__':
    unittest.main()
