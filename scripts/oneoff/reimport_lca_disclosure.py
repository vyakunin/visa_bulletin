#!/usr/bin/env python3
"""Re-import every H-1B LCA disclosure file under the current routing.

Each file's salary_record and worksite_record rows are deleted and the file is loaded
again, so its I-200 rows land in salary_record as H-1B and its E-3/H-1B1 rows carry their
own program. A file is deleted only once its download is on disk. The salary indexes are
dropped for the load and rebuilt at the end. Clustering, stats and slugs are not run
here: `refresh_staging.sh cluster` follows. Ticket 3f062b8d409f8145a64ed3137cc35a94.

Usage
    python -m scripts.oneoff.reimport_lca_disclosure --dry-run
    python -m scripts.oneoff.reimport_lca_disclosure --source-id 1 --keep-indexes   # pilot
    python -m scripts.oneoff.reimport_lca_disclosure                               # every file

Progress is kept in logs/reimport_lca_state.json; a rerun skips the sources it lists.
"""

import argparse
import json
import logging
import os
import resource
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.db.models.functions import Lower  # noqa: E402

from lib.ingest.orchestrator import PipelineOrchestrator  # noqa: E402
from lib.ingest.plugins.dol_lca import (  # noqa: E402
    LCA_FILE_RE,
    H1BSalaryDataSourcePlugin,
)
from lib.ingest.registry import PluginRegistry  # noqa: E402
from lib.parsing.salary.file_detection import (  # noqa: E402
    is_appendix_file,
    is_worksite_file,
)
from lib.utils.http_utils import get_workspace_dir  # noqa: E402
from lib.utils.logging_utils import log_context  # noqa: E402
from models.ingest.data_source import DataSource  # noqa: E402
from models.ingest.enums import DataDomain, IngestStatus, SourceType  # noqa: E402
from models.salary import SalaryRecord, WorksiteRecord  # noqa: E402
from scripts.ingest.run_pipeline import register_plugins  # noqa: E402

logger = logging.getLogger(__name__)
STATE_FILE = get_workspace_dir() / "logs" / "reimport_lca_state.json"


def url_filename(source: DataSource) -> str:
    return unquote(Path(urlparse(source.url).path).name)


def disclosure_sources() -> list[DataSource]:
    """One source per disclosure file name; the newest source wins a duplicate name."""
    by_name: dict[str, DataSource] = {}
    for source in DataSource.objects.filter(
        domain=DataDomain.DOL.value, source_type=SourceType.LCA.value
    ).order_by("id"):
        name = url_filename(source)
        if LCA_FILE_RE.search(name) and not is_worksite_file(name) and not is_appendix_file(name):
            by_name[name.lower()] = source
    return sorted(by_name.values(), key=url_filename)


def load_state() -> set[int]:
    return set(json.loads(STATE_FILE.read_text())) if STATE_FILE.exists() else set()


def save_state(done: set[int]) -> None:
    STATE_FILE.write_text(json.dumps(sorted(done)))


def manage_indexes(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "scripts.salary.manage_salary_indexes", *args, "--force"],
        check=True,
    )


def delete_rows_of(names: set[str]) -> None:
    lowered = {n.lower() for n in names}
    for model in (SalaryRecord, WorksiteRecord):
        deleted, _ = model.objects.annotate(sf=Lower("source_file")).filter(sf__in=lowered).delete()
        logger.info("deleted %s %s rows of %s", deleted, model.__name__, sorted(names))


def reimport(source: DataSource, plugin: H1BSalaryDataSourcePlugin) -> None:
    run = source.runs.order_by("-id").first()
    if run is not None:  # a source never ingested has no rows to clear
        filepath = plugin.download(source, run)  # skips when the file is already on disk
        names = {filepath.name, url_filename(source)}
        if source.local_file_path:
            names.add(Path(source.local_file_path).name)
        delete_rows_of(names)

    orchestrator = PipelineOrchestrator(
        batch_size=10000, adaptive_batch=True, prefilter_existing=False, use_copy=True
    )
    new_run = orchestrator.run(source, resume=False)
    if new_run.status != IngestStatus.COMPLETED:
        raise RuntimeError(f"run {new_run.id} ended {new_run.get_status_display()}")
    source.refresh_from_db()
    Path(source.local_file_path).unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--source-id", type=int, action="append", help="limit to these sources")
    parser.add_argument("--keep-indexes", action="store_true", help="do not drop/recreate indexes")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    log_context(f"Re-import LCA disclosure files under the I-200 routing fix: {sys.argv[1:]}")

    sources = disclosure_sources()
    if args.source_id:
        sources = [s for s in sources if s.id in args.source_id]
    done = load_state()
    todo = [s for s in sources if s.id not in done]
    for s in sources:
        logger.info("%s source %s %s", "done" if s.id in done else "todo", s.id, url_filename(s))
    if args.dry_run:
        return 0

    register_plugins()
    plugin = H1BSalaryDataSourcePlugin(skip_clustering=True)
    PluginRegistry.register(plugin)

    if not args.keep_indexes:
        manage_indexes("--drop", "--overwrite")
    failed: list[str] = []
    try:
        for i, source in enumerate(todo, 1):
            started = time.time()
            logger.info("[%s/%s] source %s %s", i, len(todo), source.id, url_filename(source))
            try:
                reimport(source, plugin)
            except Exception:
                logger.exception("source %s failed", source.id)
                failed.append(url_filename(source))
                continue
            done.add(source.id)
            save_state(done)
            logger.info(
                "[%s/%s] source %s done in %.0fs, maxrss %s MB",
                i, len(todo), source.id, time.time() - started,
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
            )
    finally:
        if not args.keep_indexes:
            manage_indexes("--recreate")
    if failed:
        logger.error("failed: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    sys.exit(main())
