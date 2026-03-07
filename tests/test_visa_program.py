"""Tests for VisaProgram enum (short_display and program labeling)."""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.test import TestCase

from models.enums.visa_program import VisaProgram


class VisaProgramShortDisplayTest(TestCase):
    """Test VisaProgram.short_display for UI labels."""

    def test_known_programs_return_short_label(self):
        self.assertEqual(VisaProgram.short_display(VisaProgram.H1B), "H-1B")
        self.assertEqual(VisaProgram.short_display(VisaProgram.H1B1), "H-1B1")
        self.assertEqual(VisaProgram.short_display(VisaProgram.E3), "E-3")
        self.assertEqual(VisaProgram.short_display(VisaProgram.PERM), "PERM")

    def test_integer_values_match_enum(self):
        self.assertEqual(VisaProgram.short_display(1), "H-1B")
        self.assertEqual(VisaProgram.short_display(2), "H-1B1")
        self.assertEqual(VisaProgram.short_display(3), "E-3")
        self.assertEqual(VisaProgram.short_display(4), "PERM")

    def test_invalid_or_unknown_returns_other(self):
        self.assertEqual(VisaProgram.short_display(VisaProgram.INVALID), "Other")
        self.assertEqual(VisaProgram.short_display(0), "Other")
        self.assertEqual(VisaProgram.short_display(99), "Other")
        self.assertEqual(VisaProgram.short_display(None), "Other")
