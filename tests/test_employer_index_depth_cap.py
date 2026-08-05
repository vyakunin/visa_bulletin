"""Depth cap on the /employers/ index — the anti-enumeration guard.

WHY THIS EXISTS
---------------
Deep index pagination is a free full-table export, and that is what a rotating
proxy pool harvests. Measured 2026-07-29 over 48h of origin logs: 955 requests
from 939 distinct IPs at 1.02 req/IP, 98% no-referer, walking
``?cursor=…&page=18..32``. Per-IP rate limiting cannot see that pattern, so the
fix removes the prize instead of arguing about who is asking.

The load-bearing subtlety these tests pin: the CURSOR selects the rows, not the
``page`` param. A cap enforced only on ``page`` is bypassed by sending
``page=1`` with a hand-built deep cursor. So the cursor is signed and carries
its own depth, and both halves are asserted here.
"""

import base64

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase

from lib.utils.pagination import (
    MAX_INDEX_PAGE,
    decode_keyset_cursor,
    encode_keyset_cursor,
)
from models.enums.visa_program import CaseStatus, VisaProgram
from models.salary import Employer, EmployerCluster, SalaryRecord


def _seed(n: int) -> None:
    """Seed n employers with descending filing counts so ordering is stable."""
    for i in range(n):
        cluster = EmployerCluster.objects.create(
            canonical_name=f"Corp {i:04d}",
            slug=f"corp-{i:04d}",
            total_lca_count=n - i,
            total_perm_count=0,
        )
        employer = Employer.objects.create(
            name=f"Corp {i:04d}",
            name_normalized=f"corp {i:04d}",
            city="San Francisco",
            state="CA",
            canonical_cluster=cluster,
        )
        SalaryRecord.objects.create(
            case_number=f"C-{i:05d}",
            employer=employer,
            employer_name=f"Corp {i:04d}",
            job_title="Engineer",
            wage_annual=100000,
            visa_program=VisaProgram.H1B,
            case_status=CaseStatus.CERTIFIED,
            fiscal_year=2023,
            worksite_state="CA",
            is_worksite=False,
        )


class CursorSigningTest(TestCase):
    """The cursor is a signed token, not an encoding."""

    def test_roundtrip_preserves_position_and_depth(self):
        cur = encode_keyset_cursor(500, 42, "next", page=4)
        decoded = decode_keyset_cursor(cur)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.direction, "next")
        self.assertEqual(decoded.order_value, 500)
        self.assertEqual(decoded.pk, 42)
        self.assertEqual(decoded.page, 4)

    def test_forged_cursor_is_rejected(self):
        """A hand-built cursor in the OLD unsigned format must not verify.

        This is the bypass: the attacker wants a deep keyset position while
        claiming a shallow page number.
        """
        forged = base64.urlsafe_b64encode(b"next:1:99999").decode("ascii")
        self.assertIsNone(decode_keyset_cursor(forged))

    def test_tampered_signature_is_rejected(self):
        cur = encode_keyset_cursor(500, 42, "next", page=4)
        self.assertIsNone(decode_keyset_cursor(cur[:-3] + "xxx"))

    def test_blank_cursor_is_none(self):
        self.assertIsNone(decode_keyset_cursor(""))
        self.assertIsNone(decode_keyset_cursor("   "))


class IndexDepthCapTest(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()
        # Comfortably deeper than the cap: 50/page * (cap + 4) pages.
        _seed(50 * (MAX_INDEX_PAGE + 4))

    def test_shallow_pages_still_serve(self):
        for page in (1, 2, MAX_INDEX_PAGE):
            resp = self.client.get(f"/employers/?program=all&page={page}")
            self.assertEqual(
                resp.status_code, 200, f"page={page} should serve, it is at/under the cap"
            )

    def test_page_past_cap_is_gone(self):
        resp = self.client.get(f"/employers/?program=all&page={MAX_INDEX_PAGE + 1}")
        self.assertEqual(resp.status_code, 410)

    def test_the_observed_farm_walk_is_gone(self):
        """The exact range the pool was walking (page=18..32) must not serve."""
        for page in (18, 25, 32):
            resp = self.client.get(f"/employers/?program=all&page={page}")
            self.assertEqual(resp.status_code, 410, f"page={page} must be capped")

    def test_deep_cursor_claiming_shallow_page_is_capped(self):
        """THE bypass: a signed deep cursor cannot be replayed at page=1.

        We mint a legitimate cursor for a depth past the cap (as only the server
        can) and then send it alongside `page=1`. The cursor's own bound depth
        must win, so the request is still refused.
        """
        deep = encode_keyset_cursor(5, 1, "next", page=MAX_INDEX_PAGE + 5)
        resp = self.client.get(f"/employers/?program=all&page=1&cursor={deep}")
        self.assertEqual(resp.status_code, 410)

    def test_unsigned_legacy_cursor_degrades_gracefully(self):
        """An old bookmarked URL must not 500 — it falls back to offset."""
        legacy = base64.urlsafe_b64encode(b"next:100:5").decode("ascii")
        resp = self.client.get(f"/employers/?program=all&page=2&cursor={legacy}")
        self.assertEqual(resp.status_code, 200)

    def test_no_next_link_is_rendered_at_the_cap(self):
        """A crawler following rendered links runs out of chain at the cap."""
        html = self.client.get(
            f"/employers/?program=all&page={MAX_INDEX_PAGE}"
        ).content.decode()
        self.assertNotIn(f"page={MAX_INDEX_PAGE + 1}", html)

    def test_next_link_present_below_the_cap(self):
        html = self.client.get("/employers/?program=all&page=1").content.decode()
        self.assertIn("page=2", html)
