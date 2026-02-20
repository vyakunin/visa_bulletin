#!/usr/bin/env python3
"""
Production smoke check: verify key pages return 200 and expected content.

Checks both HTTP status and response body (titles, key strings). Use after
deploy or to validate prod without manual clicking.

Usage:
  bazel run //scripts:smoke_check_production
  bazel run //scripts:smoke_check_production -- --base https://visa-bulletin.us
  bazel run //scripts:smoke_check_production -- --base http://localhost:8000 --timeout 15
"""

import argparse
import re
import sys
import urllib.error
import urllib.request


def fetch(url: str, timeout: int = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "SmokeCheck/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def check(
    base: str,
    path: str,
    status_expected: int,
    content_checks: list[tuple[str, str]],
    timeout: int,
) -> tuple[bool, str]:
    url = base.rstrip("/") + path
    try:
        status, body = fetch(url, timeout=timeout)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} at {path}"
    except urllib.error.URLError as e:
        return False, f"Request failed at {path}: {e.reason}"
    except TimeoutError:
        return False, f"Timeout at {path} (>{timeout}s)"
    text = body.decode("utf-8", errors="replace")
    if status != status_expected:
        return False, f"Expected {status_expected}, got {status} at {path}"
    for name, pattern in content_checks:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            continue
        return False, f"Missing content '{name}' at {path}"
    return True, f"OK {path} (200 + content)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Production smoke check (status + content)"
    )
    parser.add_argument(
        "--base",
        default="https://visa-bulletin.us",
        help="Base URL (default: https://visa-bulletin.us)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="Request timeout per URL in seconds (default: 45)",
    )
    args = parser.parse_args()
    base = args.base.rstrip("/")
    timeout = args.timeout

    checks = [
        (
            "/",
            200,
            [
                (
                    "title",
                    r"<title>[^<]*[Vv]isa [Bb]ulletin|Priority [Dd]ate[^<]*</title>",
                )
            ],
        ),
        (
            "/employment-based/india/",
            200,
            [
                ("title india eb", r"<title>[^<]*India[^<]*[Ee]mployment[^<]*</title>"),
                ("dashboard js", r"updateVisaClasses|autoSubmitForm"),
            ],
        ),
        (
            "/family-sponsored/philippines/",
            200,
            [
                ("title philippines", r"<title>[^<]*[Pp]hilippines[^<]*</title>"),
                ("canonical slug", r"family-sponsored/philippines"),
            ],
        ),
        (
            "/salaries/",
            200,
            [("salary page", r"<title>[^<]*[Ss]alary|[Hh]-1[Bb][^<]*</title>")],
        ),
        (
            "/job-titles/",
            200,
            [("job title page", r"<title>[^<]*[Jj]ob [Tt]itle[^<]*</title>")],
        ),
        (
            "/employers/",
            200,
            [("employer page", r"<title>[^<]*[Ee]mployer[^<]*</title>")],
        ),
        (
            "/sitemap.xml",
            200,
            [
                ("sitemap urlset", r"<urlset"),
                (
                    "slug urls",
                    r"employment-based/philippines|family-sponsored/philippines",
                ),
            ],
        ),
        ("/robots.txt", 200, [("sitemap line", r"Sitemap:\s*https?://")]),
    ]

    failed = []
    for path, status_expected, content_checks in checks:
        ok, msg = check(base, path, status_expected, content_checks, timeout)
        if ok:
            print(f"  OK  {path}")
        else:
            print(f"  FAIL {path}  -> {msg}")
            failed.append((path, msg))

    print("")
    if failed:
        print(f"Smoke check failed: {len(failed)} of {len(checks)} checks failed")
        for path, msg in failed:
            print(f"  - {path}: {msg}")
        return 1
    print(f"Smoke check passed: all {len(checks)} checks (status + content)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
