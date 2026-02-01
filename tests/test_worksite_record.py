"""Tests for WorksiteRecord model"""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests
setup_django_for_tests()

import unittest
from decimal import Decimal
from django.test import TestCase

from models.salary import WorksiteRecord
from models.enums.visa_program import VisaProgram, WageUnit, CaseStatus


class TestWorksiteRecord(TestCase):
    """Tests for WorksiteRecord model"""
    
    def test_create_worksite_record(self):
        """Test creating a basic worksite record"""
        record = WorksiteRecord.objects.create(
            case_number='I-200-12345-6789',
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            worksite_city='San Francisco',
            worksite_state='CA',
            worksite_zip='94105',
            job_title='Software Engineer',
            soc_code='15-1132',
            soc_title='Software Developers, Applications',
            wage_from=Decimal('150000'),
            wage_unit=WageUnit.YEAR,
            fiscal_year=2024,
            source_file='LCA_Worksites_FY2024_Q4.xlsx'
        )
        
        # Check record was created
        self.assertEqual(record.case_number, 'I-200-12345-6789')
        self.assertEqual(record.worksite_city, 'San Francisco')
        self.assertEqual(record.worksite_state, 'CA')
        self.assertEqual(record.wage_annual, 150000.0)
    
    def test_worksite_record_annual_wage_calculation(self):
        """Test annual wage calculation in WorksiteRecord"""
        # Yearly wage
        record = WorksiteRecord(
            case_number='I-200-11111-1111',
            visa_program=VisaProgram.H1B,
            worksite_city='Seattle',
            worksite_state='WA',
            job_title='Engineer',
            wage_from=Decimal('120000'),
            wage_unit=WageUnit.YEAR,
            fiscal_year=2024
        )
        self.assertEqual(record.calculate_annual_wage(), 120000.0)
        
        # Hourly wage
        record.wage_from = Decimal('75')
        record.wage_unit = WageUnit.HOUR
        self.assertEqual(record.calculate_annual_wage(), 156000.0)  # 75 * 2080
        
        # Monthly wage
        record.wage_from = Decimal('10000')
        record.wage_unit = WageUnit.MONTH
        self.assertEqual(record.calculate_annual_wage(), 120000.0)  # 10000 * 12
        
        # Weekly wage
        record.wage_from = Decimal('2500')
        record.wage_unit = WageUnit.WEEK
        self.assertEqual(record.calculate_annual_wage(), 130000.0)  # 2500 * 52
        
        # Bi-weekly wage
        record.wage_from = Decimal('5000')
        record.wage_unit = WageUnit.BI_WEEKLY
        self.assertEqual(record.calculate_annual_wage(), 130000.0)  # 5000 * 26
    
    def test_worksite_record_save_calculates_annual_wage(self):
        """Test that save() automatically calculates wage_annual"""
        record = WorksiteRecord(
            case_number='I-200-22222-2222',
            visa_program=VisaProgram.H1B,
            worksite_city='Austin',
            worksite_state='TX',
            job_title='Developer',
            wage_from=Decimal('100'),
            wage_unit=WageUnit.HOUR,
            fiscal_year=2024
        )
        record.save()
        
        # wage_annual should be calculated automatically
        self.assertEqual(record.wage_annual, 208000.0)  # 100 * 2080
    
    def test_worksite_record_str_representation(self):
        """Test string representation of WorksiteRecord"""
        record = WorksiteRecord.objects.create(
            case_number='I-200-33333-3333',
            visa_program=VisaProgram.H1B,
            worksite_city='New York',
            worksite_state='NY',
            job_title='Data Scientist',
            fiscal_year=2024
        )
        
        self.assertIn('I-200-33333-3333', str(record))
        self.assertIn('New York', str(record))
        self.assertIn('NY', str(record))
        self.assertIn('Data Scientist', str(record))
    
    def test_worksite_record_str_without_city(self):
        """Test string representation when city is missing"""
        record = WorksiteRecord.objects.create(
            case_number='I-200-44444-4444',
            visa_program=VisaProgram.H1B,
            worksite_state='CA',
            job_title='Manager',
            fiscal_year=2024
        )
        
        self.assertIn('I-200-44444-4444', str(record))
        self.assertIn('CA', str(record))
    
    def test_worksite_record_unique_case_number(self):
        """Test that case_number must be unique"""
        WorksiteRecord.objects.create(
            case_number='I-200-55555-5555',
            visa_program=VisaProgram.H1B,
            worksite_state='WA',
            job_title='Engineer',
            fiscal_year=2024
        )
        
        # Attempting to create duplicate should raise IntegrityError
        with self.assertRaises(Exception):  # IntegrityError
            WorksiteRecord.objects.create(
                case_number='I-200-55555-5555',
                visa_program=VisaProgram.H1B,
                worksite_state='CA',
                job_title='Another Engineer',
                fiscal_year=2024
            )










