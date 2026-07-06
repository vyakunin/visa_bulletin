"""Curated employer rename / legal-successor cross-linking.

Sits on top of the name-based employer clustering: a legal rename (Facebook,
Inc. -> Meta Platforms, Inc.) yields two separate ``EmployerCluster`` rows, and
this layer cross-links their profile pages (with combined lifetime totals)
WITHOUT merging the clusters. Config: ``employer_renames.yaml`` (same dir).
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from lib.business.salary.slug_redirects import resolve_employer_slug
from lib.utils.bazel_runfiles import get_data_file_path
from models.salary import EmployerCluster

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a project dependency
    yaml = None

logger = logging.getLogger(__name__)

_CONFIG_PATH = get_data_file_path("lib/business/salary/employer_renames.yaml")
if _CONFIG_PATH is None:
    # Fallback for non-Bazel environments (direct Python execution / dev).
    _CONFIG_PATH = Path(__file__).parent / "employer_renames.yaml"


@dataclass(frozen=True)
class RenamePair:
    """One curated predecessor -> successor mapping (both are cluster slugs)."""

    predecessor: str
    successor: str
    note: str


@dataclass(frozen=True)
class RenameLink:
    """Resolved cross-link shown on an employer profile page.

    ``other`` is the cluster on the far side of the rename from the page being
    viewed. ``viewing_is_successor`` is True when the current page is the newer
    (post-rename) entity. Combined totals sum the lifetime aggregates of BOTH
    clusters (the clustering pipeline maintains ``total_lca_count`` /
    ``total_perm_count`` per cluster).
    """

    other: EmployerCluster
    note: str
    viewing_is_successor: bool
    combined_lca_count: int
    combined_perm_count: int

    @property
    def combined_total(self) -> int:
        return self.combined_lca_count + self.combined_perm_count


_pairs_cache: list[RenamePair] | None = None


def _load_pairs() -> list[RenamePair]:
    """Parse the curated mapping YAML once (module-cached)."""
    global _pairs_cache
    if _pairs_cache is not None:
        return _pairs_cache
    pairs: list[RenamePair] = []
    if yaml is None or _CONFIG_PATH is None or not Path(_CONFIG_PATH).exists():
        logger.debug("employer_renames config unavailable at %s", _CONFIG_PATH)
        _pairs_cache = pairs
        return pairs
    try:
        with open(_CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
        for entry in config.get("renames") or []:
            predecessor = (entry.get("predecessor") or "").strip()
            successor = (entry.get("successor") or "").strip()
            if not predecessor or not successor:
                continue
            pairs.append(
                RenamePair(
                    predecessor=predecessor,
                    successor=successor,
                    note=(entry.get("note") or "").strip(),
                )
            )
    except Exception as e:  # noqa: BLE001 - config must never break the page
        logger.warning("Failed to load employer_renames config: %s", e)
        pairs = []
    _pairs_cache = pairs
    return pairs


def _resolve_cluster(slug: str) -> EmployerCluster | None:
    """Fetch a cluster by slug, falling back to the slug-redirect ladder."""
    try:
        return EmployerCluster.objects.get(slug=slug)
    except EmployerCluster.DoesNotExist:
        target = resolve_employer_slug(slug)
        if target and target != slug:
            try:
                return EmployerCluster.objects.get(slug=target)
            except EmployerCluster.DoesNotExist:
                return None
        return None


def get_rename_link(cluster: EmployerCluster) -> RenameLink | None:
    """Return the cross-link for ``cluster`` if it is one side of a rename.

    None (the common case) when the cluster is not in the curated mapping or the
    other side no longer resolves to a live cluster.
    """
    slug = cluster.slug
    if not slug:
        return None
    for pair in _load_pairs():
        if slug == pair.predecessor:
            other_slug, viewing_is_successor = pair.successor, False
        elif slug == pair.successor:
            other_slug, viewing_is_successor = pair.predecessor, True
        else:
            continue
        other = _resolve_cluster(other_slug)
        if other is None or other.id == cluster.id:
            return None
        return RenameLink(
            other=other,
            note=pair.note,
            viewing_is_successor=viewing_is_successor,
            combined_lca_count=(cluster.total_lca_count or 0)
            + (other.total_lca_count or 0),
            combined_perm_count=(cluster.total_perm_count or 0)
            + (other.total_perm_count or 0),
        )
    return None
