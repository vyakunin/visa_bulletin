# Known Issues

## DOL URL Discovery Issue (Low Priority)

**Status:** Does not block current operations, but may affect future data refreshes

**Problem:**
The `discover_sources()` method in `dol_lca.py` and `dol_perm.py` creates URLs with an incorrect path structure:
- **Incorrect:** `https://www.dol.gov/agencies/eta/foreign-labor/performance/sites/dolgov/files/...`
- **Correct:** `https://www.dol.gov/sites/dolgov/files/...`

**Impact:**
- Newly discovered URLs return 404 errors
- **However:** All historical data (FY 2008-2025) was ingested using the correct old URLs
- Content hashing prevents re-ingesting duplicate files even if URLs change
- Completeness check passes for all already-ingested sources

**Root Cause:**
Likely an issue with how `urljoin()` is handling relative paths from the DOL performance page. The base URL (`https://www.dol.gov/agencies/eta/foreign-labor/performance`) may be incorrect or the href extraction is capturing extra path components.

**Workaround:**
- Existing data is complete and accessible
- For new fiscal year data, URLs can be manually registered until discovery is fixed

**Fix Required:**
1. Debug `discover_sources()` in `lib/ingest/plugins/dol_lca.py`
2. Verify correct base URL for DOL scraping
3. Test with actual HTML to ensure correct URL construction
4. Add integration test for URL discovery

**Priority:** Low - does not affect existing data or current functionality
