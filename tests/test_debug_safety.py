"""
Regression test for DEBUG-in-production leak.

Background: on 2026-04-19 prod briefly served Django's debug 404 page
(exposed URL conf). Root cause: settings.py derived DEBUG from SECRET_KEY
being non-default, so any missing/reset env var silently flipped DEBUG on.

These tests guard the hardened behavior:
- assert_debug_is_safe raises when DEBUG=True and ALLOWED_HOSTS contains
  a production hostname.
- It is a no-op when DEBUG=False regardless of ALLOWED_HOSTS.
- It is a no-op when DEBUG=True but no production hostname is present.
"""

import unittest

from django.core.exceptions import ImproperlyConfigured

from django_config.debug_safety import PRODUCTION_HOSTNAMES, assert_debug_is_safe


class DebugSafetyTests(unittest.TestCase):
    def test_debug_false_is_always_safe(self):
        assert_debug_is_safe(False, list(PRODUCTION_HOSTNAMES))
        assert_debug_is_safe(False, ["localhost", "127.0.0.1"])
        assert_debug_is_safe(False, [])

    def test_debug_true_with_localhost_only_is_safe(self):
        assert_debug_is_safe(True, ["localhost", "127.0.0.1", "testserver"])

    def test_debug_true_with_production_hostname_raises(self):
        for host in PRODUCTION_HOSTNAMES:
            with self.subTest(host=host):
                with self.assertRaises(ImproperlyConfigured):
                    assert_debug_is_safe(True, ["localhost", host])

    def test_production_hostnames_include_bare_and_www(self):
        self.assertIn("visa-bulletin.us", PRODUCTION_HOSTNAMES)
        self.assertIn("www.visa-bulletin.us", PRODUCTION_HOSTNAMES)


if __name__ == "__main__":
    unittest.main()
