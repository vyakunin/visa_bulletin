
import os
import sys
import django
import logging
from pathlib import Path

# Setup Django environment
sys.path.append(str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()

from models.ingest.enums import DataDomain, SourceType, IngestStatus
from models.ingest.data_source import DataSource
from lib.ingest.registry import PluginRegistry
from lib.ingest.orchestrator import PipelineOrchestrator

# Import plugins to ensure registration
import lib.ingest.plugins

logger = logging.getLogger(__name__)

def ingest_vqs_sources():
    """
    Ingest VQS supply data sources:
    1. USCIS I-485 Inventory
    2. DOS Monthly Issuance
    3. DOL PERM Supply (Disclosure)
    """
    targets = [
        (DataDomain.USCIS, SourceType.I485_INVENTORY),
        (DataDomain.DOS, SourceType.ISSUANCE),
        (DataDomain.DOL, SourceType.PERM_DISCLOSURE),
    ]
    
    orchestrator = PipelineOrchestrator(adaptive_batch=True)
    
    for domain, source_type in targets:
        print(f"\n=== Processing {domain.label} - {source_type.label} ===")
        plugin = PluginRegistry.get_plugin(domain, source_type)
        if not plugin:
            print(f"Error: No plugin found for {domain}:{source_type}")
            continue
            
        print("Discovering sources...")
        try:
            source_infos = plugin.discover_sources()
        except Exception as e:
            print(f"Discovery failed: {e}")
            continue
            
        print(f"Found {len(source_infos)} sources.")
        
        for info in source_infos:
            print(f"  Source: {info.url}")
            
            # Get or create DataSource
            ds, created = DataSource.objects.get_or_create(
                url=info.url,
                domain=info.domain,
                source_type=info.source_type,
                defaults={
                    'format_version': info.format_version,
                    'metadata': info.metadata
                }
            )
            
            if created:
                print(f"    Created new DataSource record (ID: {ds.id})")
            else:
                print(f"    Found existing DataSource record (ID: {ds.id})")
                
            # Run ingestion
            try:
                print(f"    Starting pipeline for DataSource {ds.id}...")
                run = orchestrator.run(ds, resume=True)
                print(f"    Run {run.id} finished with status: {run.status}")
            except Exception as e:
                print(f"    Ingestion failed: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ingest_vqs_sources()
