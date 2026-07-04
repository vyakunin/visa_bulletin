"""Token-overlap similar-title ranking for job-title profile pages.

Replaces the old first-word `icontains` heuristic, which produced first-word
noise ("Senior Vice President, Legal & Compliance" recommended Senior Software
Engineer / Senior Programmer Analyst — every big "Senior *" cluster).

Approach: candidates are the INDEXABLE clusters only (`total_filings >=
INDEXABLE_MIN_FILINGS`, ~1.3k rows — small enough to score in memory), ranked
by shared CONTENT tokens (title tokens minus seniority/level qualifiers;
numeric / requisition junk never matches a real candidate so it dilutes
nothing). Recommending only indexable clusters means every suggestion is a
substantial page — the point on thin pages is to hand the visitor a relevant
place to go.

`find_broader_role` is the thin-page rescue: the best indexable cluster whose
content tokens are a subset of the page's own ("Software Engineer" is a
broader role of "Software Engineer Kbgfjg353961") — rendered as a prominent
CTA so a searcher landing on a 1-3-filing page has an obvious next step.
"""

import re
from dataclasses import dataclass

from django.core.cache import cache

from lib.business.salary.job_title_stats import INDEXABLE_MIN_FILINGS

# Seniority / level / grade qualifiers that carry no occupational meaning:
# sharing only these must never make two titles "similar".
_GENERIC_TOKENS = frozenset(
    {
        "senior", "sr", "jr", "junior", "lead", "principal", "staff",
        "associate", "assistant", "chief", "head", "intern", "trainee",
        "level", "grade", "i", "ii", "iii", "iv", "v", "vi",
        "a", "an", "the", "of", "and", "or", "for", "in",
    }
)

_UNIVERSE_CACHE_KEY = "job_title_similar_universe.v1"
_UNIVERSE_CACHE_TTL = 60 * 60 * 24


@dataclass(frozen=True)
class SimilarTitle:
    slug: str
    canonical_title: str
    total_filings: int


def content_tokens(title: str) -> frozenset[str]:
    """Alphabetic tokens of a title minus seniority/level qualifiers.

    Letters-only tokenization drops numeric requisition junk outright; a
    leftover fragment like "kbgfjg" matches no real candidate, so it can only
    lower scores, never raise them.
    """
    if not title:
        return frozenset()
    return frozenset(
        t for t in re.findall(r"[a-z]+", title.lower()) if t not in _GENERIC_TOKENS
    )


def _indexable_universe() -> list[SimilarTitle]:
    """All indexable clusters as lightweight rows, cached for a day."""
    cached = cache.get(_UNIVERSE_CACHE_KEY)
    if cached is not None:
        return cached
    from models.job_title import JobTitleCluster

    universe = [
        SimilarTitle(row["slug"], row["canonical_title"], row["total_filings"] or 0)
        for row in JobTitleCluster.objects.filter(
            slug__isnull=False, total_filings__gte=INDEXABLE_MIN_FILINGS
        )
        .exclude(canonical_title="")
        .values("slug", "canonical_title", "total_filings")
    ]
    cache.set(_UNIVERSE_CACHE_KEY, universe, _UNIVERSE_CACHE_TTL)
    return universe


def rank_similar(
    canonical_title: str, own_slug: str | None, limit: int = 5
) -> list[SimilarTitle]:
    """Indexable clusters sharing the most content tokens, biggest first."""
    own = content_tokens(canonical_title)
    if not own:
        return []
    scored = []
    for cand in _indexable_universe():
        if cand.slug == own_slug:
            continue
        shared = len(own & content_tokens(cand.canonical_title))
        if shared:
            scored.append((shared, cand.total_filings, cand))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [cand for _, _, cand in scored[:limit]]


def find_broader_role(
    canonical_title: str, own_slug: str | None
) -> SimilarTitle | None:
    """Best indexable cluster that is a strict generalization of this title.

    A candidate qualifies when its content tokens are a non-empty STRICT
    subset of the page's own — "Software Engineer" for "Software Engineer
    Kbgfjg353961", "Trader" for "Dairy Derivatives Trader". Strict, so a
    qualifier-decorated sibling ("Senior Software Engineer", identical
    content tokens) never poses as broader. Prefers the most-specific match
    (max shared tokens), then the biggest cluster.
    """
    own = content_tokens(canonical_title)
    if not own:
        return None
    best: tuple[int, int, SimilarTitle] | None = None
    for cand in _indexable_universe():
        if cand.slug == own_slug:
            continue
        cand_tokens = content_tokens(cand.canonical_title)
        if cand_tokens and cand_tokens < own:
            key = (len(cand_tokens), cand.total_filings, cand)
            if best is None or key[:2] > best[:2]:
                best = key
    return best[2] if best else None


def salaries_search_token(canonical_title: str) -> str:
    """The most distinctive single content token, for a /salaries/?q= link.

    Single-token because the salaries search is a substring match — a
    multi-word q only hits contiguous occurrences. Longest token is the
    cheap proxy for most-distinctive.
    """
    tokens = content_tokens(canonical_title)
    return max(tokens, key=len) if tokens else ""
