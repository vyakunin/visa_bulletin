"""Stale profile-slug resolution — find 301 targets for /job-title/ and /employer/.

Re-clustering rewrites cluster slugs, stranding previously indexed profile
URLs (the 2026-06-25 PERM re-cluster left ~2.6k stale-slug 404 hits/day).
Each resolver walks a ladder of indexed exact lookups before the one legacy
substring scan, and caches the outcome — including "no match" — because bots
bypass the page cache (cache_page_skip_bots), so without a negative cache a
crawler storm re-runs the SeqScan fallback on every hit.
"""

import logging

from django.core.cache import cache

from models.job_title import JobTitle, JobTitleCluster
from models.salary import Employer, EmployerCluster

logger = logging.getLogger(__name__)

# Bump to invalidate all cached resolutions (e.g. after a re-cluster run).
_CACHE_VERSION = 1
_CACHE_TTL = 60 * 60 * 24
# Cache sentinel for "resolved to no match" — distinct from a cold cache miss.
_NO_MATCH = "__none__"


def _suffix_stripped_candidates(slug: str) -> list[str]:
    """Progressively drop trailing digit-bearing tokens from a slug.

    Slug churn from re-clustering mostly produces uniqueness counters ("-2")
    and requisition-id tokens ("kbgfjg353961") at the tail; stripping them
    recovers the stable base slug. Longest candidate first.
    """
    tokens = slug.split("-")
    candidates = []
    while len(tokens) > 1 and any(ch.isdigit() for ch in tokens[-1]):
        tokens.pop()
        candidates.append("-".join(tokens))
    return candidates


def _cached_resolution(kind: str, slug: str, resolver) -> str | None:
    cache_key = f"slug_redirect.v{_CACHE_VERSION}.{kind}.{slug}"
    cached = cache.get(cache_key)
    if cached is not None:
        return None if cached == _NO_MATCH else cached
    target = resolver(slug)
    cache.set(cache_key, target if target else _NO_MATCH, _CACHE_TTL)
    return target


def resolve_job_title_slug(slug: str) -> str | None:
    """Return the current canonical /job-title/ slug for a stale slug, or None."""
    return _cached_resolution("jt", slug, _resolve_job_title)


def resolve_employer_slug(slug: str) -> str | None:
    """Return the current canonical /employer/ slug for a stale slug, or None."""
    return _cached_resolution("emp", slug, _resolve_employer)


def _cluster_slug_for_title(title_normalized: str) -> str | None:
    title = (
        JobTitle.objects.filter(title_normalized=title_normalized)
        .select_related("canonical_cluster")
        .first()
    )
    if title and title.canonical_cluster and title.canonical_cluster.slug:
        return title.canonical_cluster.slug
    return None


def _resolve_job_title(slug: str) -> str | None:
    candidates = [slug] + _suffix_stripped_candidates(slug)
    for cand in candidates:
        # The original slug already failed the caller's cluster lookup; the
        # stripped candidates may hit a live cluster slug directly (indexed).
        if cand != slug:
            hit = (
                JobTitleCluster.objects.filter(slug=cand)
                .values_list("slug", flat=True)
                .first()
            )
            if hit:
                return hit
        # Exact indexed matches on title_normalized: as-typed, then run
        # through the clustering normalizer (strips seniority/noise so
        # "sr-software-engineer-ops" can still find its entity).
        as_words = cand.replace("-", " ").lower()
        for probe in (as_words, JobTitle.normalize_title(as_words)):
            if not probe:
                continue
            target = _cluster_slug_for_title(probe)
            if target:
                return target
    # Legacy substring scan (SeqScan) — last resort; the negative cache
    # bounds it to once per slug per TTL.
    title = (
        JobTitle.objects.filter(
            title_normalized__icontains=slug.replace("-", " ").lower()
        )
        .select_related("canonical_cluster")
        .first()
    )
    if title and title.canonical_cluster and title.canonical_cluster.slug:
        return title.canonical_cluster.slug
    return None


def _resolve_employer(slug: str) -> str | None:
    candidates = [slug] + _suffix_stripped_candidates(slug)
    for cand in candidates:
        if cand != slug:
            hit = (
                EmployerCluster.objects.filter(slug=cand)
                .values_list("slug", flat=True)
                .first()
            )
            if hit:
                return hit
        # Exact indexed match on name_normalized, via the same normalizer
        # that produced the column (strips generic words like "inc"/"llc",
        # which is why a raw "adobe inc" probe never matched).
        probe = Employer.normalize_name(cand.replace("-", " "))
        if probe:
            emp = (
                Employer.objects.filter(name_normalized=probe)
                .select_related("canonical_cluster")
                .first()
            )
            if emp and emp.canonical_cluster and emp.canonical_cluster.slug:
                return emp.canonical_cluster.slug
    # Legacy substring scan — iterate a few matches instead of .first(),
    # since the closest substring hit may sit in an unslugged cluster.
    for emp in Employer.objects.filter(
        name_normalized__icontains=slug.replace("-", " ").lower()
    ).select_related("canonical_cluster")[:10]:
        if emp.canonical_cluster and emp.canonical_cluster.slug:
            return emp.canonical_cluster.slug
    return None
