#!/usr/bin/env python3
"""
Unified ingest pipeline CLI - discover sources and run ingest pipeline

Usage:
    bazel run //scripts/ingest:run_pipeline -- discover --domain dol
    bazel run //scripts/ingest:run_pipeline -- run --source-id 123
    bazel run //scripts/ingest:run_pipeline -- run --all-pending
    bazel run //scripts/ingest:run_pipeline -- run --missing-only --domain dol
    bazel run //scripts/ingest:run_pipeline -- run --retry-failed
    bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --all-domains
    bazel run //scripts/ingest:run_pipeline -- download --domain dol
    bazel run //scripts/ingest:run_pipeline -- download --list-available
    bazel run //scripts/ingest:run_pipeline -- resume --run-id 456
    bazel run //scripts/ingest:run_pipeline -- status
    bazel run //scripts/ingest:run_pipeline -- check-completeness --domain dol
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Setup Django early
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from django_config.logging_config import setup_logging
from lib.ingest.registry import PluginRegistry
from lib.ingest.orchestrator import PipelineOrchestrator
from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin
from lib.ingest.plugins.visa_bulletin import VisaBulletinPlugin
from models.ingest.data_source import DataSource
from models.ingest.ingest_run import IngestRun
from models.ingest.ingest_version import IngestVersion
from models.ingest.enums import DataDomain, SourceType, IngestStatus, IngestStage
from django.utils import timezone
from lib.utils.logging_utils import ScriptLogger
from lib.utils.data_source_utils import get_data_source_filepath

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def register_plugins():
    """Register all plugins with the registry"""
    # Skip clustering for re-imports (employers already clustered)
    PluginRegistry.register(H1BSalaryDataSourcePlugin(skip_clustering=True))
    PluginRegistry.register(PERMSalaryDataSourcePlugin(skip_clustering=True))
    PluginRegistry.register(VisaBulletinPlugin())


def discover_sources(domain: str | None = None):
    """Discover new data sources"""
    register_plugins()
    
    discovered = []
    plugins = PluginRegistry.list_plugins()
    
    for plugin_domain, plugin_source_type, plugin in plugins:
        if domain and plugin_domain != domain:
            continue
        
        logger.info(f"Discovering sources for {plugin_domain}:{plugin_source_type}")
        sources = plugin.discover_sources()
        
        for source_info in sources:
            # Check if source already exists, use get_or_create to handle race conditions
            source, created = DataSource.objects.get_or_create(
                url=source_info.url,
                defaults={
                    'domain': source_info.domain,
                    'source_type': source_info.source_type,
                    'format_version': source_info.format_version,
                    'metadata': source_info.metadata or {}
                }
            )
            if created:
                discovered.append(source)
                logger.info(f"Discovered new source: {source.url}")
            else:
                logger.debug(f"Source already exists: {source_info.url}")
    
    logger.info(f"Discovered {len(discovered)} new sources")
    return discovered


def run_pipeline(
    source_id: int | None = None,
    url: str | None = None,
    all_pending: bool = False,
    missing_only: bool = False,
    retry_failed: bool = False,
    domain: str | None = None
):
    """
    Run ingest pipeline for source(s)
    
    Args:
        source_id: Specific source ID to ingest
        url: Specific source URL to ingest
        all_pending: Process all sources without completed runs
        missing_only: Process only sources with local files but no completed runs
        retry_failed: Retry sources that have failed runs
        domain: Filter by domain (dol, visa_bulletin, etc.)
    """
    import time
    from pathlib import Path
    
    # Register plugins
    PluginRegistry.register(H1BSalaryDataSourcePlugin(skip_clustering=True))
    PluginRegistry.register(PERMSalaryDataSourcePlugin(skip_clustering=True))
    PluginRegistry.register(VisaBulletinPlugin())
    
    if source_id:
        source = DataSource.objects.get(id=source_id)
        sources = [source]
        pipeline_context = None
    elif url:
        source, _ = DataSource.objects.get_or_create(
            url=url,
            defaults={'domain': DataDomain.DOL.value, 'source_type': SourceType.LCA.value}  # Defaults, will be updated
        )
        sources = [source]
        pipeline_context = None
    elif all_pending or missing_only or retry_failed:
        # Build query for sources
        sources_qs = DataSource.objects.all()
        
        # Filter by domain if specified
        if domain:
            sources_qs = sources_qs.filter(domain=domain)
        
        if missing_only:
            # Only sources with local files but no completed runs
            sources_with_completed = set(
                DataSource.objects.filter(runs__status=IngestStatus.COMPLETED)
                .values_list('id', flat=True)
                .distinct()
            )
            sources_qs = sources_qs.exclude(id__in=sources_with_completed)
            
            # Filter to only sources with local files
            sources_with_files = []
            for source in sources_qs:
                filepath = get_data_source_filepath(source)
                if filepath and filepath.exists():
                    sources_with_files.append(source)
            sources = sources_with_files
            
            logger.info(f"Found {len(sources)} sources with local files but no completed runs")
        elif retry_failed:
            # Sources with failed runs (but no completed runs)
            sources_with_completed = set(
                DataSource.objects.filter(runs__status=IngestStatus.COMPLETED)
                .values_list('id', flat=True)
                .distinct()
            )
            sources_with_failed = set(
                DataSource.objects.filter(runs__status=IngestStatus.FAILED)
                .values_list('id', flat=True)
                .distinct()
            )
            # Sources that have failed but not completed
            sources = list(sources_qs.filter(id__in=sources_with_failed).exclude(id__in=sources_with_completed))
            
            logger.info(f"Found {len(sources)} sources with failed runs (no completed runs)")
        elif all_pending:
            # Get all sources that haven't been successfully ingested
            # Sources with no completed runs
            sources_with_completed = set(
                DataSource.objects.filter(runs__status=IngestStatus.COMPLETED)
                .values_list('id', flat=True)
                .distinct()
            )
            sources = list(sources_qs.exclude(id__in=sources_with_completed))
            
            logger.info(f"Found {len(sources)} pending sources (no completed runs)")
        
        # Create pipeline context for ETA calculation
        pipeline_start = time.time()
        pipeline_context = {
            'pending_count': len(sources),
            'completed_count': 0,
            'start_time': pipeline_start
        }
        logger.info(f"Starting pipeline for {len(sources)} sources")
    else:
        logger.error("Must specify --source-id, --url, --all-pending, --missing-only, or --retry-failed")
        sys.exit(1)
    
    orchestrator = PipelineOrchestrator(
        adaptive_batch=True,
        prefilter_existing=True
    )
    
    for idx, source in enumerate(sources, 1):
        logger.info(f"Running pipeline for source {source.id} ({idx}/{len(sources)}): {source.url}")
        try:
            run = orchestrator.run(source, resume=True, pipeline_context=pipeline_context)
            logger.info(f"Pipeline completed: Run {run.id}")
        except Exception as e:
            logger.error(f"Pipeline failed for source {source.id}: {e}")
            # Do NOT raise here, just continue to next source
            # The run itself is already marked as FAILED by the orchestrator
            # raise
            continue
    
    # Final pipeline summary
    if pipeline_context and len(sources) > 0:
        total_time = time.time() - pipeline_context['start_time']
        logger.info(f"Pipeline completed: {len(sources)} sources processed in {total_time/60:.1f} min")


def discover_and_ingest(domain: str | None = None, all_domains: bool = False):
    """Discover new sources and ingest all pending"""
    logger.info("Discovering new sources...")
    discovered = discover_sources(domain if not all_domains else None)
    
    logger.info("Running pipeline for all pending sources...")
    run_pipeline(all_pending=True)


def download_sources(domain: str | None = None, all_domains: bool = False, list_available: bool = False):
    """Download sources without ingesting"""
    register_plugins()
    
    if list_available:
        # Just list available sources without downloading
        plugins = PluginRegistry.list_plugins()
        for plugin_domain, plugin_source_type, plugin in plugins:
            if domain and plugin_domain != domain:
                continue
            if all_domains or not domain:
                logger.info(f"\n{plugin_domain.upper()}:{plugin_source_type.upper()} - Available sources:")
            else:
                logger.info(f"\nAvailable sources:")
            
            sources = plugin.discover_sources()
            for source_info in sources:
                logger.info(f"  - {source_info.url}")
                if source_info.metadata:
                    for key, value in source_info.metadata.items():
                        logger.info(f"    {key}: {value}")
        return
    
    # Discover and download
    logger.info("Discovering sources...")
    discovered = discover_sources(domain if not all_domains else None)
    
    if not discovered:
        logger.info("No new sources to download")
        return
    
    logger.info(f"Downloading {len(discovered)} source(s)...")
    
    for idx, source in enumerate(discovered, 1):
        logger.info(f"Downloading source {source.id} ({idx}/{len(discovered)}): {source.url}")
        try:
            # Create a minimal run just for download tracking
            run = IngestRun.objects.create(
                source=source,
                status=IngestStatus.RUNNING,
                stage=IngestStage.DOWNLOADING
            )
            
            plugin = PluginRegistry.get_plugin(source.domain, source.source_type)
            if not plugin:
                logger.error(f"No plugin found for {source.domain}:{source.source_type}")
                run.status = IngestStatus.FAILED
                run.error_message = f"No plugin found for {source.domain}:{source.source_type}"
                run.save()
                continue
            
            # Download only (no parsing/ingesting) - use plugin's download method directly
            filepath = plugin.download(source, run)
            logger.info(f"✓ Downloaded: {filepath}")
            
            # Mark run as completed (download-only)
            run.status = IngestStatus.COMPLETED
            run.stage = IngestStage.DOWNLOADING  # Keep at downloading stage to indicate download-only
            run.completed_at = timezone.now()
            run.save()
            
        except Exception as e:
            logger.error(f"Download failed for source {source.id}: {e}")
            if 'run' in locals():
                run.status = IngestStatus.FAILED
                run.error_message = str(e)
                run.save()
            raise
    
    logger.info(f"✓ Downloaded {len(discovered)} source(s)")


def resume_run(run_id: int):
    """Resume an interrupted ingest run"""
    # Register plugins (skip clustering for re-imports)
    PluginRegistry.register(H1BSalaryDataSourcePlugin(skip_clustering=True))
    PluginRegistry.register(PERMSalaryDataSourcePlugin(skip_clustering=True))
    PluginRegistry.register(VisaBulletinPlugin())
    
    run = IngestRun.objects.get(id=run_id)
    if run.status == IngestStatus.COMPLETED:
        logger.warning(f"Run {run_id} is already completed")
        return
    
    orchestrator = PipelineOrchestrator(adaptive_batch=True, prefilter_existing=True)
    
    logger.info(f"Resuming run {run_id} from stage: {run.stage}")
    try:
        orchestrator.run(run.source, resume=True)
        logger.info(f"Run {run_id} completed")
    except Exception as e:
        logger.error(f"Run {run_id} failed: {e}")
        raise


def show_status(source_id: int | None = None):
    """Show status of ingest runs"""
    if source_id:
        sources = [DataSource.objects.get(id=source_id)]
    else:
        sources = DataSource.objects.all()[:20]  # Limit to recent 20
    
    for source in sources:
        latest_run = source.runs.order_by('-started_at').first()
        if latest_run:
            print(f"Source {source.id}: {source.url}")
            print(f"  Latest run: {latest_run.id} - {latest_run.status} ({latest_run.stage})")
            print(f"  Records: {latest_run.records_created:,} created, {latest_run.records_failed:,} failed")
            print(f"  Started: {latest_run.started_at}")
            if latest_run.completed_at:
                print(f"  Completed: {latest_run.completed_at}")
        else:
            print(f"Source {source.id}: {source.url} - No runs yet")


def check_completeness(domain: str | None = None):
    """
    Check if all available data sources have been ingested.
    
    Discovers available sources and compares with completed ingest runs.
    """
    logger.info("Checking data completeness...")
    
    # Step 1: Discover all available sources (to ensure we have latest list)
    logger.info("Step 1: Discovering available sources...")
    register_plugins()
    
    all_available_sources = []
    plugins = PluginRegistry.list_plugins()
    
    for plugin_domain, plugin_source_type, plugin in plugins:
        if domain and plugin_domain != domain:
            continue
        
        logger.info(f"  Discovering {plugin_domain}:{plugin_source_type}...")
        source_infos = plugin.discover_sources()
        
        for source_info in source_infos:
            # Get or create DataSource record
            source, created = DataSource.objects.get_or_create(
                url=source_info.url,
                defaults={
                    'domain': source_info.domain,
                    'source_type': source_info.source_type,
                    'format_version': source_info.format_version,
                    'metadata': source_info.metadata or {}
                }
            )
            all_available_sources.append(source)
            if created:
                logger.info(f"    ✓ Discovered new: {source.url}")
    
    logger.info(f"  Found {len(all_available_sources)} total available sources")
    
    # Step 2: Check which sources have completed ingest runs
    logger.info("Step 2: Checking ingestion status...")
    
    sources_with_completed = set(
        DataSource.objects.filter(
            runs__status=IngestStatus.COMPLETED
        ).values_list('id', flat=True).distinct()
    )
    
    ingested_sources = [s for s in all_available_sources if s.id in sources_with_completed]
    missing_sources = [s for s in all_available_sources if s.id not in sources_with_completed]
    
    # Step 3: Categorize missing sources
    broken_links = []  # Sources with 404 errors (files don't exist)
    not_ingested = []  # Sources that exist but haven't been ingested
    
    for source in missing_sources:
        runs = source.runs.all()
        is_404 = False
        if runs.exists():
            latest_run = runs.order_by('-started_at').first()
            # Check if error is 404
            if latest_run.error_message and '404' in latest_run.error_message:
                is_404 = True
        
        if is_404:
            broken_links.append(source)
        else:
            not_ingested.append(source)
    
    # Step 4: Show summary
    logger.info("")
    logger.info("=" * 80)
    logger.info("COMPLETENESS SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total available sources: {len(all_available_sources)}")
    logger.info(f"  ✓ Ingested: {len(ingested_sources)}")
    logger.info(f"  ✗ Not ingested (available): {len(not_ingested)}")
    logger.info(f"  ⚠ Broken links (404): {len(broken_links)}")
    
    if not_ingested:
        logger.info("")
        logger.info("NOT INGESTED (files exist but not ingested):")
        for source in sorted(not_ingested, key=lambda s: s.url):
            runs = source.runs.all()
            if runs.exists():
                latest_run = runs.order_by('-started_at').first()
                status_str = f"  {latest_run.get_status_display()} ({latest_run.get_stage_display()})"
                if latest_run.error_message and '404' not in latest_run.error_message:
                    status_str += f" - {latest_run.error_message[:100]}"
            else:
                status_str = "  No runs"
            
            logger.info(f"  - {source.url}")
            logger.info(f"    {status_str}")
            logger.info(f"    Domain: {source.get_domain_display()}, Type: {source.get_source_type_display()}")
    
    if broken_links:
        logger.info("")
        logger.info("BROKEN LINKS (404 - files don't exist yet or were removed):")
        for source in sorted(broken_links, key=lambda s: s.url):
            runs = source.runs.all()
            if runs.exists():
                latest_run = runs.order_by('-started_at').first()
                status_str = f"  {latest_run.get_status_display()} ({latest_run.get_stage_display()})"
                if latest_run.error_message:
                    # Extract just the 404 part
                    error_msg = latest_run.error_message
                    if '404' in error_msg:
                        status_str += f" - {error_msg[:120]}"
            else:
                status_str = "  No runs (link discovered but file doesn't exist)"
            
            logger.info(f"  - {source.url}")
            logger.info(f"    {status_str}")
            logger.info(f"    Domain: {source.get_domain_display()}, Type: {source.get_source_type_display()}")
    else:
        logger.info("")
        if broken_links:
            logger.info("✓ All available (non-404) sources have been ingested!")
            logger.info(f"  (Note: {len(broken_links)} sources have 404 errors and cannot be ingested)")
        else:
            logger.info("✓ All available sources have been ingested!")
    
    logger.info("")
    logger.info("=" * 80)
    
    return {
        'total': len(all_available_sources),
        'ingested': len(ingested_sources),
        'not_ingested': len(not_ingested),
        'broken_links': len(broken_links),
        'not_ingested_sources': not_ingested,
        'broken_link_sources': broken_links
    }


def main():
    parser = argparse.ArgumentParser(
        description='Unified ingest pipeline CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Discover command
    discover_parser = subparsers.add_parser('discover', help='Discover new data sources')
    discover_parser.add_argument('--domain', choices=[d.value for d in DataDomain], help='Domain to discover')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run ingest pipeline')
    run_group = run_parser.add_mutually_exclusive_group(required=True)
    run_group.add_argument('--source-id', type=int, help='Source ID to ingest')
    run_group.add_argument('--url', help='Source URL to ingest')
    run_group.add_argument('--all-pending', action='store_true', help='Run all pending sources (no completed runs)')
    run_group.add_argument('--missing-only', action='store_true', help='Run only sources with local files but no completed runs')
    run_group.add_argument('--retry-failed', action='store_true', help='Retry sources that have failed runs (but no completed runs)')
    run_parser.add_argument('--domain', choices=[d.value for d in DataDomain], help='Filter by domain (works with --all-pending, --missing-only, --retry-failed)')
    
    # Discover and ingest
    di_parser = subparsers.add_parser('discover-and-ingest', help='Discover and ingest in one command')
    di_group = di_parser.add_mutually_exclusive_group()
    di_group.add_argument('--domain', choices=[d.value for d in DataDomain], help='Domain to discover')
    di_group.add_argument('--all-domains', action='store_true', help='Discover all domains')
    
    # Download command
    download_parser = subparsers.add_parser('download', help='Download sources without ingesting')
    download_group = download_parser.add_mutually_exclusive_group()
    download_group.add_argument('--domain', choices=[d.value for d in DataDomain], help='Domain to download')
    download_group.add_argument('--all-domains', action='store_true', help='Download all domains')
    download_parser.add_argument('--list-available', action='store_true', help='List available sources without downloading')
    
    # Resume command
    resume_parser = subparsers.add_parser('resume', help='Resume interrupted run')
    resume_parser.add_argument('--run-id', type=int, required=True, help='Run ID to resume')
    
    # Status command
    status_parser = subparsers.add_parser('status', help='Show ingest status')
    status_parser.add_argument('--source-id', type=int, help='Show status for specific source')
    
    # Check completeness command
    completeness_parser = subparsers.add_parser('check-completeness', help='Check if all available data sources have been ingested')
    completeness_parser.add_argument('--domain', choices=[d.value for d in DataDomain], help='Domain to check (default: all)')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    script_logger.log_call(args=vars(args), context='Unified ingest pipeline CLI')
    
    try:
        if args.command == 'discover':
            discover_sources(args.domain)
        elif args.command == 'run':
            run_pipeline(
                args.source_id,
                args.url,
                args.all_pending,
                args.missing_only,
                args.retry_failed,
                args.domain
            )
        elif args.command == 'discover-and-ingest':
            discover_and_ingest(args.domain, args.all_domains)
        elif args.command == 'download':
            download_sources(args.domain, args.all_domains, args.list_available)
        elif args.command == 'resume':
            resume_run(args.run_id)
        elif args.command == 'status':
            show_status(args.source_id)
        elif args.command == 'check-completeness':
            check_completeness(args.domain)
    except Exception as e:
        logger.error(f"Command failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()

