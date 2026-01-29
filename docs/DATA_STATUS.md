# Data Status and Coverage

**Last Updated:** 2026-01-29

## Current Data Coverage (Instance: 44.209.204.255)

### Summary Statistics
- **Total Records:** 1,543,123
- **Fiscal Years:** 2008-2025 (18 years)
- **Unique Employers:** 267,530
- **Unique Job Titles:** 164,373
- **Data Sources:** 44 files ingested
- **Completed Ingest Runs:** 34

### Data Breakdown by Program
| Program | Records | Percentage | Coverage |
|---------|---------|------------|----------|
| **H-1B (LCA)** | 103,292 | 6.7% | FY 2009, 2011-2013, 2020-2025 |
| **PERM** | 1,439,831 | 93.3% | FY 2008, 2010-2024 |

**Note:** `visa_program=4` in the database represents PERM (Permanent Labor Certification).

### Year-by-Year Coverage
| FY | Total Records | H-1B | PERM | Notes |
|----|---------------|------|------|-------|
| 2008 | 61,540 | 0 | 61,540 | PERM only |
| 2009 | 1,457 | 1,457 | 0 | H-1B only |
| 2010 | 80,444 | 0 | 80,444 | PERM only |
| 2011 | 78,971 | 6,372 | 72,599 | Mixed |
| 2012 | 70,801 | 7,598 | 63,203 | Mixed |
| 2013 | 52,343 | 8,666 | 43,677 | Mixed |
| 2014 | 70,469 | 0 | 70,469 | PERM only |
| 2015 | 88,986 | 0 | 88,986 | PERM only |
| 2016 | 125,164 | 0 | 125,164 | PERM only |
| 2017 | 96,997 | 0 | 96,997 | PERM only |
| 2018 | 119,447 | 0 | 119,447 | PERM only |
| 2019 | 102,507 | 0 | 102,507 | PERM only |
| 2020 | 106,469 | 12,615 | 93,854 | Mixed |
| 2021 | 121,289 | 13,142 | 108,147 | Mixed |
| 2022 | 118,996 | 14,582 | 104,414 | Mixed |
| 2023 | 129,754 | 13,614 | 116,140 | Mixed |
| 2024 | 103,329 | 11,086 | 92,243 | Mixed |
| 2025 | 14,160 | 14,160 | 0 | H-1B only (partial year) |

## Data Completeness

### What We Have
✅ All available data from DOL website (FY 2008-2025)
✅ Comprehensive PERM data (1.44M records)
✅ Recent H-1B LCA data (2020-2025)
✅ Historical H-1B LCA data (2009, 2011-2013)
✅ Content hashing to prevent duplicates

### Missing Data (Not Available from DOL)
❌ FY 2007 - No data files available on DOL website
❌ H-1B LCA FY 2014-2019 - Limited or no disclosure data

### Known Issues
⚠️ **URL Discovery Bug:** `discover_sources()` creates URLs with incorrect path prefix
- Impact: Low - existing data is complete, affects only future auto-discovery
- Workaround: Manual URL registration or fix discovery logic
- See: `docs/KNOWN_ISSUES.md`

## Data Quality

### Processing Statistics
- **Ingest Status:** All 34 runs completed successfully
- **Rejection Tracking:** Enabled (tracks why records are rejected)
- **Clustering:** Employer and job title clustering completed
- **Indexes:** Optimized for search and clustering operations

### Data Sources
- **LCA Files:** 18 files (H-1B quarterly/annual disclosure)
- **PERM Files:** 16 files (Permanent labor certification)
- **Worksite Files:** 10 files (Supplementary location data)

## Automated Refresh Capability

### Current Status
✅ **Content hashing implemented** - Detects duplicate files even if URLs change
✅ **Completeness checking working** - Compares by URL and content hash
✅ **Cron infrastructure ready** - Scripts pre-built and tested
✅ **Blue-green database support** - Safe refresh without downtime

### Future Refreshes
When new quarterly/annual data is released:
1. Discovery may find incorrect URLs (due to known bug)
2. Content hash prevents re-ingesting old files with new URLs
3. Manual URL registration available if needed
4. Automated cron jobs will handle new data once URLs are correct

## Comparison with Production

### Production Instance (visa-bulletin.us)
- **Role:** Public-facing web server
- **Components:** Docker + Gunicorn + Nginx + SSL
- **Database:** Reads from same PostgreSQL instance
- **Traffic:** Public HTTP/HTTPS access

### Ingestion Instance (44.209.204.255)
- **Role:** Data processing and database management
- **Components:** PostgreSQL + Bazel scripts + Cron jobs
- **Database:** Blue-green setup (visa_bulletin_blue, visa_bulletin_green)
- **No web server:** Data processing only

## Next Steps

1. ✅ Content hashing implemented
2. ✅ Data parity verified (1.5M records, FY 2008-2025)
3. ✅ Production deployment documented
4. ⚠️ Fix URL discovery bug (optional - not blocking)
5. ⚠️ Test automated refresh on next quarterly release
