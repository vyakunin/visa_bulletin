# Visa Bulletin Parser

A Python-based web scraper and parser for the U.S. Department of State's Visa Bulletin data. This tool automatically downloads, caches, and extracts structured immigration priority date information from monthly visa bulletins.

## Overview

The Visa Bulletin is a monthly publication by the U.S. Department of State that provides information about immigrant visa availability for family-sponsored and employment-based preference categories. This project automates the process of:

- Fetching historical visa bulletin pages from the official government website
- Parsing and extracting priority date tables
- Converting dates to structured Python date objects
- Caching downloaded pages locally to minimize network requests

## Features

- **Automatic Discovery**: Finds and downloads all available visa bulletin publications
- **Smart Caching**: Saves downloaded HTML pages locally to avoid redundant network requests
- **Table Extraction**: Parses four key tables from each bulletin:
  - Family-Sponsored Final Action Dates
  - Family-Sponsored Dates for Filing
  - Employment-Based Final Action Dates
  - Employment-Based Dates for Filing
- **Date Conversion**: Automatically converts date strings (DDMmmYY format) to Python date objects
- **Pretty Printing**: Includes formatted console table output with box-drawing characters

## Installation

### Prerequisites

- Python 3.11 or higher
- [Bazel](https://bazel.build/) 8.1+ (build system)
- pip (Python package installer)
- Homebrew (macOS) for automatic Bazel installation

### Quick Setup (Recommended)

Run the automated setup script:

```bash
cd /path/to/visa_bulletin
./scripts/setup_dev_environment.sh
```

The setup script will:
- Check for and install Bazel (via Homebrew if available)
- Create a virtual environment at `~/visa-bulletin-venv`
- Install all required Python dependencies
- Create necessary directories
- Provide usage instructions

### Manual Setup

If you prefer to set up manually:

1. Clone or download this repository

2. Create a virtual environment:
```bash
python3 -m venv ~/visa-bulletin-venv
```

3. Activate the virtual environment:
```bash
source ~/visa-bulletin-venv/bin/activate
```

4. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

### DEBUG Mode (Development vs Production)

The application automatically detects whether you're in development or production mode:

**Local Development (Default):**
- ✅ `DEBUG = True` (helpful error pages)
- ✅ Development SECRET_KEY (unsafe for production)
- ✅ Verbose logging

**Production Mode (Auto-enabled):**
- ✅ `DEBUG = False` (safe error pages)
- ✅ Custom SECRET_KEY required
- ✅ Production-ready settings

**How it works:**
The app checks if `DJANGO_SECRET_KEY` environment variable is set:
- If using default key → **Development mode** (DEBUG=True)
- If custom key is set → **Production mode** (DEBUG=False)

**Check current mode:**
```bash
python scripts/check_debug_mode.py
```

**Enable production mode:**
```bash
# Generate a secure key
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# Set it as environment variable (in systemd service or shell)
export DJANGO_SECRET_KEY='your-generated-key-here'
```

⚠️ **Important:** Never commit production SECRET_KEY to git! It's automatically safe in development but must be set via environment variable in production.

## Usage

### Web Dashboard (Recommended)

The easiest way to explore visa bulletin data is through the interactive web dashboard:

1. **First-time setup (run migrations):**
```bash
# Note: Server can be running - PostgreSQL supports concurrent migrations
bazel run //:migrate
```

2. **Start the web server:**
```bash
bazel run //:runserver
```

**Note:** With PostgreSQL, you can run migrations while the server is running. The database supports concurrent schema changes, so there's no need to stop the server before running migrations.

**Note:** The server runs with `--noreload` flag (no auto-reload on file changes). This prevents crashes in Bazel's sandboxed environment. To see code changes:
- Stop the server (`Ctrl+C`)
- Restart with `bazel run //:runserver` (Bazel rebuilds automatically - cached, takes <1s)

**Bazel Performance:** The first run analyzes dependencies (~2s), subsequent runs use cache (<1s). The cache persists across sessions in `~/.cache/bazel/`.

3. **Open your browser:**
Navigate to `http://localhost:8000/`

3. **Explore the data:**
   - Select your visa category (Family-Sponsored or Employment-Based)
   - Choose your country of chargeability
   - Pick your visa class (F1, F2A, EB2, etc.)
   - Select action type (Final Action or Filing)
   - Enter your priority date to see processing estimates

The dashboard features:
- 📊 Interactive Plotly charts showing historical priority date progress
- 🔮 Simple projection estimates based on recent trends
- 🔗 Deep-linkable URLs for sharing specific filter combinations
- 📱 Responsive Bootstrap 5 design

### Fetching New Data

To download and import the latest visa bulletins:

```bash
# Fetch bulletins and save to database (unified ingest pipeline)
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --domain visa_bulletin
```

This will:
1. Discover new bulletins on travel.state.gov
2. Download any new bulletins (skips already processed sources)
3. Parse tables and extract priority dates
4. Save to database with duplicate detection
4. Save structured data to the PostgreSQL database

### Running Tests

The project uses **Bazel** as the primary test runner:

```bash
# Run all tests (recommended)
bazel test //tests:test_parser //tests:test_extractor //tests:test_integration

# Run a specific test suite
bazel test //tests:test_extractor

# Run tests with detailed output
bazel test //tests:test_extractor --test_output=all

# Show only errors
bazel test //tests:test_parser //tests:test_extractor //tests:test_integration --test_output=errors
```

**Why Bazel?**
- ✅ Hermetic builds (reproducible across machines)
- ✅ Intelligent caching (faster repeated runs)
- ✅ Automatic pre-commit hook integration
- ✅ Single source of truth for dependencies

**Alternative: pytest (for debugging only)**

You can run tests directly with pytest for better debugging output:

```bash
source ~/visa-bulletin-venv/bin/activate
pytest tests/test_extractor.py -v -k test_specific_function
```

Use pytest when you need:
- 🐛 Better error messages for debugging
- 🔍 Test filtering with `-k` flag
- 💻 Quick iteration without rebuilding

Tests verify:
- Table extraction from multiple bulletin formats
- Date conversion (DDMmmYY format to Python date objects)
- Proper handling of "C" (Current) and "U" (Unauthorized) statuses
- Whitespace normalization
- Data integrity across 3 randomly selected bulletins
- Database integration and time-series data extraction

**Note:** Tests automatically run before every git commit via Bazel-based pre-commit hook.

The ingest framework will:
1. Discover new visa bulletin sources from the main index page
2. Extract links to individual monthly bulletins
3. Download bulletins (skipping already cached pages in `data/bulletin/saved_pages/`)
4. Parse tables from each bulletin
5. Save structured data to the database
6. Validate data quality and completeness

### Cached Data

Downloaded HTML pages are stored in the `data/bulletin/saved_pages/` directory. The ingest framework automatically checks this directory before making network requests, making subsequent runs much faster.

To force a fresh download, delete the `data/bulletin/saved_pages/` directory or specific HTML files within it, then re-run the ingest pipeline.

## Quick Start

```bash
# 1. Setup environment
./scripts/setup_dev_environment.sh

# 2. Fetch data and populate database (unified ingest pipeline)
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --all-domains

# 3. Run web dashboard
bazel run //:runserver

# 4. Open browser
open http://localhost:8000
```

## Data Ingestion (IMPORTANT: Use Ingest Framework)

**⚠️ All users should use the unified ingest framework for data operations.**

The project uses a unified ingest pipeline (`lib/ingest/`) for all data operations. This framework provides:
- **Automatic discovery** of new data sources
- **Resume support** (can resume interrupted operations)
- **Progress tracking** and logging
- **Validation** after ingestion
- **Versioning** for data rollbacks
- **Rejection tracking** for data quality analysis
- **Consistent behavior** across all data sources (bulletin, salary, etc.)

**Rejection Tracking:**
Each ingest run tracks why records are rejected during processing. This helps identify:
- Data quality issues (missing employer, job title, salary data)
- Format mismatches (wrong column mappings, unexpected data formats)
- Filtering decisions (whitelist, worksite records, etc.)

Query rejection stats after ingestion:
```python
from models.ingest.ingest_run import IngestRun

# Get rejection statistics for a run
run = IngestRun.objects.get(id=504)
for stat in run.rejection_stats.all().order_by('-count'):
    print(f"{stat.get_reason_display()}: {stat.count:,} records")
    print(f"  Sample case numbers: {stat.sample_case_numbers}")
```

See `docs/ingest/README.md` for complete rejection tracking documentation.

### For Regular Updates

**Always use the ingest framework for scheduled updates and cron jobs:**

```bash
# Discover and ingest all domains (bulletin + salary)
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --all-domains

# Ingest only bulletin data
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --domain visa_bulletin

# Ingest only salary data
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --domain dol
```

**Important: After ingesting salary data, run employer clustering:**

```bash
# Option 1: Use combined script (recommended - runs ingest + clustering)
bazel run //scripts/ingest:ingest_and_cluster -- --source-id 123

# Option 2: Run separately
bazel run //scripts/ingest:run_pipeline -- run --source-id 123
bazel run //scripts/salary:cluster_existing_employers
```

**Why clustering is separate:**
- Clustering is disabled during ingest for performance (10-100x faster)
- Clustering must be run after ingest to cluster newly imported employers
- Clustering can take 30+ minutes for large datasets, so it's run separately

### For One-Off Scripts

**When creating one-off scripts or debugging tools, use the ingest framework whenever possible:**

✅ **GOOD** - Use ingest framework utilities:
```python
from lib.ingest.orchestrator import PipelineOrchestrator
from lib.ingest.registry import PluginRegistry
from models.ingest.data_source import DataSource

# Use framework for one-off imports
plugin = PluginRegistry.get_plugin(DataDomain.VISA_BULLETIN, SourceType.BULLETIN)
orchestrator = PipelineOrchestrator()
run = orchestrator.run(source)
```

❌ **BAD** - Direct database access or custom download logic:
```python
# Don't create custom download/import logic
# Use ingest framework instead
```

**Why use the framework:**
- Consistent error handling and logging
- Automatic validation and data quality checks
- Resume support if script fails mid-way
- Progress tracking and ETA calculations
- Works with all data sources (bulletin, salary, worksite)

**Legacy scripts:**
Old standalone scripts may still exist in `scripts/bulletin/` and `scripts/salary/` directories. These are deprecated - migrate to using the ingest framework when possible.

## Deployment

### Local vs Production Architecture

**Local Development:**
- ✅ Bazel for building, testing, and running
- ✅ `bazel run //:runserver` for development
- ✅ Hermetic builds with caching

**Production (AWS Lightsail 2GB):**
- ✅ Docker + Gunicorn
- ✅ PostgreSQL with blue-green deployment
- ✅ Pre-built Bazel binaries (reduced memory)
- ✅ Nginx reverse proxy with SSL

### New Instance Setup

```bash
# Clone and run automated setup
git clone https://github.com/vyakunin/visa_bulletin.git /opt/visa_bulletin
cd /opt/visa_bulletin
./scripts/setup_new_instance.sh
```

The setup script configures:
- Swap (2GB, swappiness=60)
- Docker and PostgreSQL
- Memory limits for Bazel and PostgreSQL
- Monitoring tools (sysstat, atop)

### Zero-Downtime Deployment

```bash
./scripts/deploy-zero-downtime.sh ~/.ssh/lightsail_visa_bulletin v1.2.3
```

**Full deployment guide:** See [deployment/README.md](deployment/README.md) and [docs/deployment/NEW_INSTANCE_SETUP.md](docs/deployment/NEW_INSTANCE_SETUP.md)

## Project Structure

```
visa_bulletin/
├── .git/
│   └── hooks/
│       └── pre-commit           # Git hook (Bazel-based)
├── lib/
│   ├── BUILD                    # Bazel build file for lib
│   ├── __init__.py              # Package initializer
│   ├── bulletin_parser.py       # HTML parsing logic
│   ├── publication_data.py      # Data class for publications
│   └── table.py                 # Data class for tables
├── tests/
│   ├── BUILD                    # Bazel build file for tests
│   ├── __init__.py              # Tests package initializer
│   └── test_parser.py           # Unit tests for parser functions
├── data/
│   ├── bulletin/
│   │   └── saved_pages/         # Cached HTML bulletins (used by ingest framework)
│   └── salary/
│       └── dol_data/            # Salary data files (PERM, LCA, worksite)
│   └── BUILD                    # Bazel build file for test data
├── BUILD                        # Root Bazel build file
├── MODULE.bazel                 # Bazel module definition (Bzlmod)
├── .bazelrc                     # Bazel configuration
├── .bazelversion                # Pin Bazel version
├── scripts/
│   ├── ingest/
│   │   └── run_pipeline.py      # Unified ingest pipeline (replaces old import scripts)
│   └── salary/
│       ├── validate_data.py      # Data validation
│       └── ...                   # Other utility scripts
├── scripts/
│   └── setup_dev_environment.sh    # Automated setup script
├── requirements.txt             # Python dependencies
├── .gitignore                   # Git ignore rules
├── CONTRIBUTING.md              # Development guide
└── README.md                    # This file

~/visa-bulletin-venv/            # Virtual environment (external)
```

## How It Works

### 1. Publication Discovery (`parse_publication_links`)
- Fetches the main visa bulletin page
- Extracts all links matching the pattern `/visa-bulletin-for-{Month}-{Year}.html`
- Sorts publications by date (newest first)

### 2. Data Fetching (`fetch_publication_data`)
- Iterates through discovered publication URLs
- Checks local cache before downloading
- Extracts publication date from URL filename
- Creates `PublicationData` objects containing URL, HTML content, and date

### 3. Table Extraction (`extract_tables`)
- Uses BeautifulSoup to parse HTML
- Locates tables by finding preceding `<u>` (underline) tags containing table titles
- Filters for only the four supported table types
- Extracts headers and data rows

### 4. Date Parsing
- Converts date strings in format `DDMmmYY` (e.g., "15JAN25") to Python date objects
- Preserves non-date values (like "C" for "Current") as strings

## Build System

This project uses **[Bazel](https://bazel.build/)** as its build system for:
- Fast, reproducible builds
- Hermetic dependency management
- Parallel test execution
- Cross-platform consistency

### Building with Bazel

```bash
# Build the lib package
bazel build //lib:lib

# Build all targets
bazel build //...

# Clean build artifacts
bazel clean
```

## Testing

The project includes a comprehensive test suite (`test_parser.py`) developed using Test-Driven Development (TDD). Tests are run against 3 randomly selected bulletins to ensure parsing works correctly across different time periods and HTML structures.

All tests are managed by Bazel for consistent, reproducible execution.

### Test Coverage

- **normalize()**: Whitespace handling and text normalization
- **extract_tables()**: Complete table extraction from HTML
- **extract_table()**: Individual table parsing logic
- **Date conversion**: Validates DDMmmYY format conversion to Python date objects
- **Data preservation**: Ensures special values ('C', 'U') remain as strings
- **Data integrity**: Validates specific known values from real bulletins

### Test Files

The test suite validates against these bulletins:
- `visa-bulletin-for-february-2017.html`
- `visa-bulletin-for-march-2023.html`
- `visa-bulletin-for-october-2021.html`

All 9 test cases pass successfully across all three files.

### Git Pre-Commit Hook

The repository includes an automated Bazel-based pre-commit hook that runs all tests before allowing commits. This ensures:
- No broken code is committed
- All tests pass before code is saved to version control
- Code quality standards are maintained
- Fast test execution with Bazel's caching

The hook will automatically block commits if tests fail. **Do not bypass:** never use `git commit --no-verify`; fix the failures and commit again.

## Data Extracted

The parser extracts four main table types from each visa bulletin:

### 1. Family-Sponsored Categories
- **Final Action Dates**: When visas can actually be issued
- **Dates for Filing**: When applications can be filed

Both tables include preference categories:
- F1: Unmarried Sons and Daughters of U.S. Citizens
- F2A: Spouses and Children of Permanent Residents
- F2B: Unmarried Sons and Daughters (21+) of Permanent Residents
- F3: Married Sons and Daughters of U.S. Citizens
- F4: Brothers and Sisters of Adult U.S. Citizens

### 2. Employment-Based Categories
- **Final Action Dates**: When adjustment of status can be approved
- **Dates for Filing**: When I-485 applications can be filed

Both tables include preference categories:
- EB-1: Priority Workers
- EB-2: Professionals with Advanced Degrees or Exceptional Ability
- EB-3: Skilled Workers, Professionals, and Other Workers
- EB-4: Special Immigrants
- EB-5: Immigrant Investors

Each category may have separate dates for different countries (India, China, Mexico, Philippines, etc.).

## Dependencies

- **beautifulsoup4** (4.13.3): HTML parsing and navigation
- **requests** (2.32.3): HTTP library for fetching web pages
- **soupsieve** (2.6): CSS selector library for BeautifulSoup

All dependencies are managed through the virtual environment and specified in `requirements.txt`.

**For Bazel builds**, a `requirements.lock` file is required to resolve transitive dependencies. To update it:

```bash
bazel run //:update_requirements_lock
```

This generates `requirements.lock` with all transitive dependencies locked, which Bazel's pip rules need to resolve packages like pandas (which depends on pytz, numpy, etc.).

**When to update requirements.lock:**
- After adding new packages to `requirements.txt`
- When dependency resolution errors occur (e.g., "no such package pytz")
- Before committing dependency changes

## Data Classes

### `PublicationData`
Represents a single visa bulletin publication.

**Attributes:**
- `url` (str): Relative URL to the bulletin page
- `content` (str): HTML content of the page
- `publication_date` (datetime): Parsed publication date

### `Table`
Represents an extracted table from a bulletin.

**Attributes:**
- `title` (str): Table identifier (e.g., "employment_based_final_action")
- `headers` (tuple): Column headers
- `rows` (list[tuple]): Data rows with date objects or strings

## Code Quality Notes

### Known Issues

1. **No error handling**: The script doesn't handle network failures gracefully beyond basic `raise_for_status()` calls

3. **Deprecated scripts**: Old `scripts/bulletin/refresh_data.py` and `refresh_incremental.py` have been replaced by the unified ingest pipeline (`scripts/ingest/run_pipeline.py`)

### Potential Improvements

- Add database storage (SQLite integration started but not completed)
- Implement comprehensive error handling and logging
- Add command-line arguments for configuration
- Export data to CSV/JSON formats
- ~~Add unit tests~~ ✅ **Done!** (test_parser.py covers core functionality)
- Create data visualization capabilities
- ~~Fix the incomplete main() function logic~~ ✅ **Done!** (now displays parsed tables)
- Add CI/CD pipeline for automated testing

## Example Output

When run, the script prints information about each bulletin:

```
/content/travel/en/legal/visa-law0/visa-bulletin/2025/visa-bulletin-for-march-2025.html
2025-03-01 00:00:00
4
```

Where:
- Line 1: Bulletin URL
- Line 2: Publication date
- Line 3: Number of tables extracted

## Git Workflow

The repository is initialized with git and includes automated quality checks.

### Initial Setup (Already Done)

```bash
git init  # Already initialized
```

### Making Commits

When you commit changes, tests run automatically:

```bash
git add .
git commit -m "Your commit message"
```

Output example:
```
Running tests before commit...
test_normalize_whitespace ... ok
test_extract_tables_returns_list ... ok
[... all tests ...]
----------------------------------------------------------------------
Ran 9 tests in 0.334s

OK

✓ All tests passed! Proceeding with commit...
```

If tests fail, the commit is blocked and you'll see which tests failed.

### Bypassing Tests (Not Recommended)

Do not use `--no-verify`. Fix lint or test failures and commit normally.

## Legal Notice

This project scrapes publicly available data from the U.S. Department of State website. Please ensure your use complies with the website's terms of service and applicable laws. The data is provided by the U.S. government and is in the public domain.

## Source

Data is fetched from: https://travel.state.gov/content/travel/en/legal/visa-law0/visa-bulletin.html

## License

This project is provided as-is for educational and informational purposes.

## Contributing

This appears to be a personal project. If you find bugs or have suggestions:
1. Complete the main() function logic
2. Add proper error handling
3. Consider adding tests

---

*Last updated: November 2025*
*Bulletins cached: 125 files spanning from 2003 to 2025*

