import os
import sys
import unittest

import django
from django.conf import settings

if not settings.configured:
    sys.path.append(".")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
    django.setup()

from datetime import date
from unittest.mock import patch

from lib.business.vqs.supply.allocator import SupplyAllocator
from lib.business.vqs.supply.cascade import CascadeModel
from lib.business.vqs.supply.country_cap import CountryCapModel
from models.enums.country import Country


class TestSupplyModule(unittest.TestCase):
    def test_country_cap(self):
        model = CountryCapModel()
        # 140k annual limit -> ~11.6k monthly
        # 7% cap -> ~816 monthly
        # Buffer 1.2x -> ~980 capped limit

        # Test 1: ROW country (not capped)
        res = model.apply_cap(Country.ALL.value, 5000, date(2023, 1, 1))
        self.assertEqual(res, 5000)

        # Test 2: India (capped)
        # Should be capped at ~980
        res = model.apply_cap(Country.INDIA.value, 5000, date(2023, 1, 1))
        self.assertLess(res, 1200)
        self.assertGreater(res, 800)

        # Test 3: India (under cap)
        res = model.apply_cap(Country.INDIA.value, 500, date(2023, 1, 1))
        self.assertEqual(res, 500)

    @patch("lib.business.vqs.supply.cascade.is_current_at_date")
    @patch("lib.business.vqs.supply.cascade.get_monthly_supply")
    def test_cascade_model(self, mock_supply, mock_current):
        model = CascadeModel()
        knowledge_date = date(2023, 1, 1)
        sim_month = date(2023, 2, 1)

        # Setup: higher preference is "Current" (annual limit not binding).
        # A5-F2: must key off is_current_at_date, NOT get_cutoff_at_date is None
        # (the latter returns a stale non-None cutoff during a Current spell).
        mock_current.return_value = True
        # Setup: EB1 allocation is 1000
        mock_supply.return_value = 1000

        # Test EB2 (receives from EB1)
        bonus = model.estimate_cascade_bonus(
            "2nd", Country.INDIA.value, sim_month, knowledge_date
        )
        # Expect 35% of 1000 = 350
        self.assertEqual(bonus, 350)

        # Test EB1 (receives nothing)
        bonus = model.estimate_cascade_bonus(
            "1st", Country.INDIA.value, sim_month, knowledge_date
        )
        self.assertEqual(bonus, 0)

        # Test EB3 (receives from EB1 + EB2)
        # If EB1 and EB2 act identical (both Current/1000 supply)
        # EB3 gets bonus form both -> 350 + 350 = 700
        bonus = model.estimate_cascade_bonus(
            "3rd", Country.INDIA.value, sim_month, knowledge_date
        )
        self.assertEqual(bonus, 700)

    @patch("lib.business.vqs.supply.allocator.get_base_supply_estimator")
    @patch("lib.business.vqs.supply.cascade.CascadeModel.estimate_cascade_bonus")
    def test_allocator_integration(self, mock_cascade, mock_base):
        allocator = SupplyAllocator()

        mock_base.return_value = 1000
        mock_cascade.return_value = 200

        month = date(2023, 1, 1)
        kd = date(2022, 12, 1)

        # Test ROW (no cap)
        # Total = 1000 (base) + 200 (cascade) = 1200
        # Cap logic exists but ROW shouldn't be capped unless global logic applies?
        # CountryCapModel implementation checks if country in OVERSUBSCRIBED_COUNTRIES

        res = allocator.get_supply("2nd", Country.ALL.value, month, kd)
        self.assertEqual(res.total, 1200)
        self.assertEqual(res.cascade_bonus, 200)

        # Test India (capped)
        # Total proposed = 1200
        # Cap for India ~980. So should define result.

        res = allocator.get_supply("2nd", Country.INDIA.value, month, kd)
        self.assertLess(res.total, 1000)
        self.assertEqual(res.cascade_bonus, 200)


if __name__ == "__main__":
    unittest.main()
