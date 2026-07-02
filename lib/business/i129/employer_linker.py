"""Link I-129 petitions to LCA employer clusters by normalized employer name.

The I-129 petition rows carry only a raw ``employer_name`` string (USCIS spelling,
e.g. ``Infosys Limited``) — there is no employer FK, and ``worksite_record`` has no
employer field at all. To scope the actual-pay comparison to an ``/employer/<slug>/``
page we must map each petition's ``employer_name`` to an ``EmployerCluster``.

A NAIVE exact match yields ~0 rows: the LCA-side spelling differs from the USCIS
spelling (``INFOSYS TECHNOLOGIES LIMITED`` vs ``Infosys Limited``). The fix is to
match on the SAME normalized form the LCA employers were clustered under
(``Employer.normalize_name`` → both collapse to ``infosy``). We build an index of
``name_normalized → best cluster`` from ``salary_employer`` (the cluster with the
most LCA volume wins ties), then assign each distinct I-129 ``employer_name`` to its
matching cluster and backfill ``i129_petition.employer_cluster_id`` in one bulk
``UPDATE ... FROM`` (a temp mapping table).

Precision comes from full-string normalized equality — two different companies almost
never share an identical full normalized name — and the pay comparison suppresses
cells with < ``MIN_COMPARISON_N`` matched petitions anyway, so a stray mislink washes
out. This is a heavyweight backfill (373k rows): run it OFF-PROD on staging and
graduate the data per branching.md, same as the initial i129 load.
"""

import logging
from dataclasses import dataclass

from django.db import connection, transaction
from django.db.models import Count

from models.i129 import I129Petition
from models.salary import Employer
from models.uscis_employer import UscisEmployerApproval

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkStats:
    """Outcome of a linker run (or dry run)."""

    distinct_names: int  # distinct non-blank employer_name values in i129_petition
    matched_names: int  # of those, how many resolved to a cluster
    matched_rows: int  # petition rows that got a cluster (sum over matched names)
    total_rows: int  # total non-blank-name petition rows considered

    @property
    def name_match_pct(self) -> float:
        if not self.distinct_names:
            return 0.0
        return round(100.0 * self.matched_names / self.distinct_names, 1)

    @property
    def row_match_pct(self) -> float:
        if not self.total_rows:
            return 0.0
        return round(100.0 * self.matched_rows / self.total_rows, 1)


def build_normalized_cluster_index() -> dict[str, int]:
    """Map each LCA ``name_normalized`` to its highest-LCA-volume cluster id.

    One normalized name can belong to several ``Employer`` rows (different
    city/state) pointing at different clusters; we pick the cluster whose employers
    carry the most ``total_lca_count`` for that normalized name, so a name resolves
    to the company that actually files the H-1Bs rather than a tiny namesake.
    """
    # (name_normalized, cluster_id) -> summed lca volume
    volume: dict[tuple[str, int], int] = {}
    rows = Employer.objects.filter(canonical_cluster__isnull=False).values_list(
        "name_normalized", "canonical_cluster_id", "total_lca_count"
    )
    for name_norm, cluster_id, lca in rows.iterator(chunk_size=10000):
        if not name_norm:
            continue
        key = (name_norm, cluster_id)
        volume[key] = volume.get(key, 0) + (lca or 0)

    best: dict[str, tuple[int, int]] = {}  # name_norm -> (cluster_id, volume)
    for (name_norm, cluster_id), vol in volume.items():
        cur = best.get(name_norm)
        # Highest volume wins; deterministic tiebreak on lower cluster_id.
        if cur is None or vol > cur[1] or (vol == cur[1] and cluster_id < cur[0]):
            best[name_norm] = (cluster_id, vol)
    return {name_norm: cid for name_norm, (cid, _vol) in best.items()}


def resolve_clusters_for_names(names: list[str]) -> dict[str, int]:
    """Return ``{raw_employer_name: cluster_id}`` for names that match a cluster.

    Unmatched names are simply absent from the returned dict.
    """
    index = build_normalized_cluster_index()
    resolved: dict[str, int] = {}
    for raw in names:
        norm = Employer.normalize_name(raw)
        if not norm:
            continue
        cluster_id = index.get(norm)
        if cluster_id is not None:
            resolved[raw] = cluster_id
    return resolved


def _apply_mapping(name_to_cluster: dict[str, int], table: str) -> int:
    """Bulk-assign ``employer_cluster_id`` on ``table`` via a temp mapping table.

    ``table`` is a trusted internal constant (never user input). Returns rows updated.
    """
    if not name_to_cluster:
        return 0
    items = list(name_to_cluster.items())
    tmp = "_emp_cluster_map"
    with connection.cursor() as cursor:
        # Disable the app's 45s statement_timeout for this intentional bulk write
        # (the UPDATE...FROM over ~373k rows exceeds it). SET LOCAL scopes it to the
        # surrounding transaction.atomic() only. Without this the backfill rolls back.
        cursor.execute("SET LOCAL statement_timeout = 0;")
        cursor.execute(
            f"CREATE TEMP TABLE {tmp} "
            "(employer_name varchar(255) PRIMARY KEY, cluster_id bigint) "
            "ON COMMIT DROP;"
        )
        # Chunked multi-row INSERT (avoid a single 60k-value statement).
        for start in range(0, len(items), 2000):
            chunk = items[start : start + 2000]
            values_sql = ",".join(["(%s, %s)"] * len(chunk))
            params: list = []
            for name, cid in chunk:
                params.extend((name, cid))
            cursor.execute(
                f"INSERT INTO {tmp} (employer_name, cluster_id) VALUES {values_sql} "
                "ON CONFLICT (employer_name) DO NOTHING;",
                params,
            )
        cursor.execute(
            f"UPDATE {table} t SET employer_cluster_id = m.cluster_id "
            f"FROM {tmp} m "
            "WHERE t.employer_name = m.employer_name "
            "AND t.employer_cluster_id IS DISTINCT FROM m.cluster_id;"
        )
        return cursor.rowcount


def _link_by_employer_name(model, table: str, *, dry_run: bool) -> LinkStats:
    """Resolve each distinct ``employer_name`` on ``model`` to a cluster + backfill the FK.

    Shared by the I-129 petition and USCIS Data Hub linkers — both carry a raw
    ``employer_name`` and an ``employer_cluster`` FK, matched the same normalized way.
    """
    name_counts = dict(
        model.objects.exclude(employer_name="")
        .values("employer_name")
        .annotate(n=Count("id"))
        .values_list("employer_name", "n")
    )
    distinct_names = len(name_counts)
    total_rows = sum(name_counts.values())

    resolved = resolve_clusters_for_names(list(name_counts.keys()))
    matched_names = len(resolved)
    matched_rows = sum(name_counts[name] for name in resolved)

    stats = LinkStats(
        distinct_names=distinct_names,
        matched_names=matched_names,
        matched_rows=matched_rows,
        total_rows=total_rows,
    )
    logger.info(
        "%s employer linker%s: %d/%d names matched (%.1f%%), %d/%d rows (%.1f%%)",
        table,
        " [dry-run]" if dry_run else "",
        matched_names,
        distinct_names,
        stats.name_match_pct,
        matched_rows,
        total_rows,
        stats.row_match_pct,
    )
    if not dry_run:
        with transaction.atomic():
            updated = _apply_mapping(resolved, table)
        logger.info("%s employer linker: %d rows updated", table, updated)
    return stats


def link_i129_employers(*, dry_run: bool = False) -> LinkStats:
    """Resolve every distinct I-129 ``employer_name`` to a cluster and backfill the FK.

    Heavyweight write on the full petition table — run off-prod on staging and
    graduate the data (branching.md). ``dry_run`` computes and reports the match
    rates without writing.
    """
    return _link_by_employer_name(I129Petition, "i129_petition", dry_run=dry_run)


def link_uscis_employers(*, dry_run: bool = False) -> LinkStats:
    """Resolve every distinct USCIS Data Hub ``employer_name`` to a cluster + backfill.

    Same normalized-name match as the I-129 linker (the Data Hub carries no LCA join
    key either). Run after each Data Hub ingest; off-prod + graduate like the I-129
    backfill.
    """
    return _link_by_employer_name(
        UscisEmployerApproval, "uscis_employer_approval", dry_run=dry_run
    )
