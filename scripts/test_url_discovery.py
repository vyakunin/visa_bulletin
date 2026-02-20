#!/usr/bin/env python3
"""Test URL discovery to verify it creates correct URLs."""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from lib.ingest.registry import PluginRegistry


def main():
    # Get LCA plugin and test discovery
    plugins = PluginRegistry.list_plugins()
    for domain, source_type, plugin in plugins:
        if domain.value == "dol" and source_type.value == "lca":
            print(f"Testing {domain}:{source_type} discovery...")
            sources = plugin.discover_sources()
            print(f"Discovered {len(sources)} sources")
            print("\nFirst 5 URLs:")
            for i, src in enumerate(sources[:5]):
                print(f"  {i + 1}. {src.url}")
            print("\nLast 5 URLs:")
            for i, src in enumerate(sources[-5:]):
                print(f"  {i + 1}. {src.url}")

            # Check for malformed URLs
            bad_urls = [
                s
                for s in sources
                if "/agencies/eta/foreign-labor/performance/sites/" in s.url
            ]
            if bad_urls:
                print(f"\n❌ Found {len(bad_urls)} malformed URLs!")
                for s in bad_urls[:5]:
                    print(f"  - {s.url}")
            else:
                print("\n✅ All URLs look correct (no extra path prefix)")
            break

    # Test PERM plugin
    for domain, source_type, plugin in plugins:
        if domain.value == "dol" and source_type.value == "perm":
            print(f"\nTesting {domain}:{source_type} discovery...")
            sources = plugin.discover_sources()
            print(f"Discovered {len(sources)} sources")
            print("\nFirst 3 URLs:")
            for i, src in enumerate(sources[:3]):
                print(f"  {i + 1}. {src.url}")

            # Check for malformed URLs
            bad_urls = [
                s
                for s in sources
                if "/agencies/eta/foreign-labor/performance/sites/" in s.url
            ]
            if bad_urls:
                print(f"\n❌ Found {len(bad_urls)} malformed URLs!")
            else:
                print("\n✅ All URLs look correct")
            break


if __name__ == "__main__":
    main()
