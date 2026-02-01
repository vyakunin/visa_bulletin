# DOL Data Files Excluded from Git

All DOL data Excel files (*.xlsx) are excluded from git commits.
They can be re-downloaded on the server using the ingest pipeline.

## Why excluded?

- **Large size**: Total ~4-5 GB of Excel files
- **Reproducible**: Can be re-downloaded from DOL website
- **Dynamic**: Data gets updated quarterly
- **Not source code**: These are data files, not code

## How to get data on server:

### Option 1: Re-download (recommended)
```bash
# On the server
cd /opt/visa_bulletin
bazel run //scripts/ingest:run_pipeline -- download --domain dol
```

This will download all available DOL data files from the official sources.

### Option 2: rsync from local machine (if you have local data)
```bash
# From your local machine
rsync -avz --progress data/salary/dol_data/ user@server:/opt/visa_bulletin/data/salary/dol_data/
```

### Option 3: Copy specific files
```bash
# Copy only files needed for testing
scp data/salary/dol_data/PERM_FY2023.xlsx user@server:/opt/visa_bulletin/data/salary/dol_data/
```

## Data files included:

- LCA (H-1B) disclosure data: ~73 files
- PERM disclosure data: ~25 files  
- LCA worksite data: ~5 files
- Historical files with various naming conventions
- **Total size**: ~4-5 GB

All files are cached locally in `data/salary/dol_data/` directory but excluded from git.
