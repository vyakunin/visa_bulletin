"""Shared schema.org JSON-LD helpers for SEO-rich pages.

Centralizes <script>-safe embedding and the site's standard ``Dataset``
payload so the salary and employer landing pages emit identical, valid
structured data. Google can surface a Dataset rich result for the
"h1b salary database" / "perm database" class of queries that dominate
these pages' impressions, so the bare landings carry a dataset describing
the whole corpus (not just filter-scoped pages).
"""

import json
from datetime import date as _date

# Public-domain U.S. government works (DOL disclosure data).
_GOV_LICENSE = "https://www.usa.gov/government-works"


def embed_jsonld(payload: dict) -> str:
    """Serialize a JSON-LD payload safely for embedding in a <script> tag.

    Escapes the characters that can break out of a <script> context
    (<, >, &, and the U+2028/U+2029 line terminators) per the OWASP
    JSON-in-HTML guidance — without this, an employer name containing a
    literal '</script>' would terminate the surrounding tag.
    """
    raw = json.dumps(payload, ensure_ascii=False)
    return (
        raw.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def build_dataset_jsonld(
    *,
    name: str,
    description: str,
    url: str,
    keywords: str,
    temporal_coverage: str | None = None,
) -> str:
    """Standard site Dataset payload (DOL source, free, government-works license).

    Returns a <script>-safe JSON-LD string. Used for the corpus-level
    datasets on the /salaries/ and /employers/ landings.
    """
    payload = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": name,
        "description": description,
        "url": url,
        "keywords": keywords,
        "creator": {
            "@type": "Organization",
            "name": "U.S. Department of Labor",
            "url": "https://www.dol.gov",
        },
        "publisher": {
            "@type": "Organization",
            "name": "U.S. Immigration Data",
            "url": "https://visa-bulletin.us",
        },
        "isAccessibleForFree": True,
        "license": _GOV_LICENSE,
        "dateModified": _date.today().isoformat(),
    }
    if temporal_coverage:
        payload["temporalCoverage"] = temporal_coverage
    return embed_jsonld(payload)
