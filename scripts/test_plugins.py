"""
Verify plugin registration and instantiation.
"""

import sys

import django
from django.conf import settings

if not settings.configured:
    sys.path.append(".")
    django.setup()

from lib.ingest.registry import PluginRegistry
from models.ingest.enums import DataDomain, SourceType


def test_plugins():
    print("Listing registered plugins...")
    plugins = PluginRegistry.list_plugins()
    found = set()
    for domain, source_type, plugin in plugins:
        print(
            f"Domain: {domain} | Source: {source_type} | Class: {plugin.__class__.__name__}"
        )
        found.add((domain, source_type))

    expected = {
        ("uscis", "i485_inventory"),
        ("dos", "issuance"),
        ("dol", "perm_disclosure"),
    }

    missing = expected - found
    if missing:
        print(f"ERROR: Missing plugins: {missing}")
        sys.exit(1)
    else:
        print("SUCCESS: All VQS plugins registered.")

    # Test instantiation and basic method calls
    print("\nTesting retrieval...")
    uscis = PluginRegistry.get_plugin(DataDomain.USCIS, SourceType.I485_INVENTORY)
    if not uscis:
        print("ERROR: Could not retrieve USCIS plugin")
        sys.exit(1)
    print(f"Retrieved: {uscis}")

    dos = PluginRegistry.get_plugin(DataDomain.DOS, SourceType.ISSUANCE)
    if not dos:
        print("ERROR: Could not retrieve DOS plugin")
        sys.exit(1)
    print(f"Retrieved: {dos}")

    perm = PluginRegistry.get_plugin(DataDomain.DOL, SourceType.PERM_DISCLOSURE)
    if not perm:
        print("ERROR: Could not retrieve PERM plugin")
        sys.exit(1)
    print(f"Retrieved: {perm}")

    # --- Data Processing Verification ---
    print("\n--- Testing Data Processing (Parse -> Transform) ---")

    from pathlib import Path

    # Dummy objects to satisfy plugin interface
    class DummySource:
        format_version = "modern"
        url = "http://example.com/file.csv"
        metadata = {}

    class DummyRun:
        def __init__(self):
            self.checkpoint = {}
            self.source = DummySource()
            self.id = 1

    run = DummyRun()

    # 1. USCIS Inventory
    inventory_file = Path("data/sources/uscis_inventory/sample_inventory.csv")
    if inventory_file.exists():
        print(f"\nProcessing USCIS Inventory: {inventory_file}")
        count = 0
        for record in uscis.parse(inventory_file, run):
            fact = uscis.transform(record)
            if fact:
                print(
                    f"  Generated Fact: {fact.dimensions['country']} {fact.dimensions['visa_class']} {fact.value}"
                )
                count += 1
        print(f"  Total Facts: {count}")
    else:
        print(f"WARNING: File not found: {inventory_file}")

    # 2. DOS Issuance
    issuance_file = Path("data/sources/dos_issuance/sample_issuance.csv")
    if issuance_file.exists():
        print(f"\nProcessing DOS Issuance: {issuance_file}")
        count = 0
        for record in dos.parse(issuance_file, run):
            fact = dos.transform(record)
            if fact:
                print(
                    f"  Generated Fact: {fact.dimensions['country']} {fact.dimensions['visa_class']} {fact.value}"
                )
                count += 1
        print(f"  Total Facts: {count}")
    else:
        print(f"WARNING: File not found: {issuance_file}")

    # 3. DOL PERM Supply
    perm_file = Path("data/sources/dol_perm/sample_perm.csv")
    if perm_file.exists():
        print(f"\nProcessing DOL PERM Supply: {perm_file}")
        count = 0
        for record in perm.parse(perm_file, run):
            fact = perm.transform(record)
            if fact:
                print(
                    f"  Generated Fact: {fact.dimensions['country']} {fact.dimensions['visa_class']} {fact.dimensions['status']} val={fact.value}"
                )
                count += 1
        print(f"  Total Facts: {count}")
    else:
        print(f"WARNING: File not found: {perm_file}")


if __name__ == "__main__":
    test_plugins()
