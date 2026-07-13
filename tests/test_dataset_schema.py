"""Site-wide Dataset JSON-LD (E-E-A-T / GEO data provenance).

Locks the global schema.org/Dataset block added to base.html (Notion 39962b8d…faab,
item 5): every page extending base.html declares the site's data as a citable
Dataset with a named creator + government-source provenance, and it lives in
<head> so it renders no visible DOM (zero CLS). A regression — block dropped,
invalid JSON, wrong author entity, missing a source, or moved into <body> — fails
here.
"""
import json
import re

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from django.core.cache import cache
from django.test import Client, TestCase


def _jsonld_blocks(html: str) -> list[dict]:
    """Every application/ld+json payload on the page, parsed (invalid JSON fails the test)."""
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>', html, re.DOTALL
    )
    return [json.loads(b) for b in blocks]


def _dataset(html: str) -> dict:
    datasets = [b for b in _jsonld_blocks(html) if b.get("@type") == "Dataset"]
    assert len(datasets) == 1, f"expected exactly one Dataset JSON-LD block, got {len(datasets)}"
    return datasets[0]


class DatasetSchemaTest(TestCase):
    # Static pages that extend base.html and render reliably against the empty test DB.
    PAGES = ("/methodology/", "/corrections/")

    def setUp(self):
        self.client = Client()
        cache.clear()

    def test_dataset_block_present_and_valid_on_base_pages(self):
        for path in self.PAGES:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f"{path} must return 200")
            ds = _dataset(resp.content.decode())  # exactly one, valid JSON
            self.assertEqual(ds["@context"], "https://schema.org")
            # Named author entity — the E-E-A-T signal; must match the /about/ Person.
            self.assertEqual(ds["creator"]["name"], "Vladimir Yakunin", path)
            self.assertEqual(ds["creator"]["url"], "https://visa-bulletin.us/about/", path)
            self.assertIn("publisher", ds)
            self.assertTrue(ds.get("isAccessibleForFree"))
            self.assertIn("temporalCoverage", ds)
            self.assertIn("license", ds)
            # All three government sources credited (provenance for citation).
            source_names = " ".join(s.get("name", "") for s in ds["isBasedOn"])
            self.assertEqual(len(ds["isBasedOn"]), 3, "must credit all 3 gov sources")
            self.assertIn("Department of Labor", source_names)
            self.assertIn("Department of State", source_names)
            self.assertIn("USCIS", source_names)

    def test_dataset_is_head_only_so_no_layout_shift(self):
        # JSON-LD in <head> renders no visible DOM -> zero CLS. Pin the Dataset block
        # inside <head>: it can never contribute a layout shift on any template.
        html = self.client.get("/methodology/").content.decode()
        head = html.split("</head>", 1)[0]
        self.assertIn('"@type": "Dataset"', head, "Dataset JSON-LD must live in <head> (CLS-safe)")
