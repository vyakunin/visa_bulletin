# Contributing Guide

## Development Workflow

### Setting Up Your Environment

1. Run the setup script (installs Bazel if needed):
```bash
./scripts/setup_dev_environment.sh
```

2. Verify Bazel is installed:
```bash
bazel --version
```

2b. Install the git hooks (git does not clone `.git/hooks`, so a fresh clone has none):
```bash
./scripts/install_git_hooks.sh
```

3. Activate the virtual environment (for running scripts):
```bash
source ~/visa-bulletin-venv/bin/activate
```

**Note:** Old `refresh_data.py` scripts have been replaced by the unified ingest pipeline. 

**IMPORTANT: Always use the ingest framework for data operations:**

```bash
# Discover and ingest all domains (bulletin + salary)
bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --all-domains

# For one-off scripts, use ingest framework utilities (see README.md)
```

**Why use the ingest framework:**
- Automatic discovery, validation, and error handling
- Resume support for interrupted operations
- Consistent logging and progress tracking
- Works across all data sources (bulletin, salary, worksite)
- **Avoid creating custom download/import scripts** - use framework utilities instead

### Running Tests

Tests use **PostgreSQL** (no SQLite). Have PostgreSQL running. When `DB_NAME` is unset, tests use `postgres` and Django creates `test_postgres`; never set `DB_NAME` to a production database. See `tests/README.md` for details.

This project uses **Bazel** for building and testing. Before making changes, ensure all tests pass:

```bash
# Run all tests
bazel test //tests/...

# Quick test run (single target)
bazel test //tests:test_parser

# Detailed output
bazel test //tests:test_parser --test_output=all

# Only show errors
bazel test //tests:test_parser --test_output=errors
```

### Making Changes

1. Create a new branch for your feature/fix:
```bash
git checkout -b feature-name
```

2. Make your changes to the code

3. If you modify dependencies:
   - Update `requirements.txt` with the new package
   - Run `bazel run //:update_requirements_lock` to regenerate `requirements.lock`
   - Commit both files

4. If you add new Python files, update the appropriate `BUILD` file:
   - `lib/BUILD` for library code
   - `tests/BUILD` for test code

5. Build your changes:
```bash
bazel build //lib:lib
```

6. Write tests for new functionality in `tests/`

7. Run tests to verify everything works:
```bash
bazel test //tests:test_parser
```

8. Commit your changes (tests will run automatically via Bazel):
```bash
git add .
git commit -m "Description of changes"
```

The Bazel-based pre-commit hook will automatically:
- Run all tests with Bazel
- Prevent commit if tests fail
- Show which tests failed and why
- Leverage Bazel's caching for fast execution

### Pre-Commit Hook

The gate is tracked at **`tools/hooks/pre-commit`** — edit it there, not in `.git/`.
Install it into your clone with:

```bash
./scripts/install_git_hooks.sh          # symlink, so it cannot drift
./scripts/install_git_hooks.sh --check  # verify it is installed and current
```

It symlinks rather than copies, so the hook you run is always the one on your
branch. It installs into `$GIT_COMMON_DIR/hooks` (shared by every linked
worktree) and deliberately does **not** set `core.hooksPath`: a repo-local
setting there would shadow a machine-global hooks directory and silently
disable whatever else it runs.

Before each commit the hook:
- Runs ruff on staged `*.py`
- Runs `tools/bazel_dep_check.py` when any `*.py` / `BUILD` / `*.bzl` is staged
  (fast, and before the slow test pass)
- Runs the full test suite via Bazel
- Blocks the commit if any of them fails

It fails **closed**: a non-zero Bazel exit it cannot positively attribute to a
known shape (test failures, timeouts, `NO STATUS`, shutdown segfaults, an
analysis error) stops the commit rather than being reported as a pass. Its
classification and file selection are pinned by `//tests:test_pre_commit_hook`.

Because `.git/hooks` is not version-controlled, a clone that skips the installer
has no local gate. The dep check does not depend on it either way: the `Test`
workflow runs `python3 tools/bazel_dep_check.py` as its own step, so an
undeclared first-party import fails CI regardless.

**Do not bypass the hook.** Never use `git commit --no-verify`. If the hook fails, fix the issues (ruff or tests) then commit again.

### Working with Bazel

#### BUILD Files

Each directory with Python code has a `BUILD` file that defines:
- `py_library`: Reusable Python code
- `py_test`: Test targets
- `filegroup`: Data files

**Rule: One Target Per File** - Always create one `py_library` target per Python file for better granularity and incremental builds.

Example `BUILD` file:
```python
load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

# ✅ Good - one target per file
py_library(
    name = "my_module",
    srcs = ["my_module.py"],  # Only ONE file
    visibility = ["//visibility:public"],
    deps = [
        requirement("beautifulsoup4"),
    ],
)

# ❌ Bad - bundling multiple files
py_library(
    name = "lib",
    srcs = [
        "module1.py",
        "module2.py",
        "module3.py",
    ],
)
```

#### Common Bazel Commands

```bash
# Build everything
bazel build //...

# Test everything
bazel test //...

# Clean build artifacts
bazel clean

# Query dependencies
bazel query "deps(//tests:test_parser)"

# Build specific target
bazel build //lib:bulletin_parser
```

### Testing Guidelines

- All new features should include tests
- Tests should be placed in the `tests/` directory
- Test files should start with `test_`
- Use descriptive test method names
- Include docstrings explaining what each test validates

### Code Quality

- Follow PEP 8 style guidelines
- Add comments for complex logic
- Update README.md for user-facing changes
- Update CONTRIBUTING.md for developer-facing changes

## Test Structure

```
tests/
├── __init__.py          # Package initializer
└── test_parser.py       # Parser functionality tests
```

### Adding New Tests

1. Create a new test file in `tests/` (e.g., `test_feature.py`)
2. Import unittest and the code you're testing
3. Create a test class inheriting from `unittest.TestCase`
4. Write test methods starting with `test_`
5. Run tests to verify they pass

Example:
```python
import unittest
from lib.your_module import your_function

class TestYourFeature(unittest.TestCase):
    def test_something(self):
        """Test that something works correctly"""
        result = your_function()
        self.assertEqual(result, expected_value)
```

## Questions?

If you encounter issues or have questions, please check:
1. README.md for general usage
2. This CONTRIBUTING.md for development guidelines
3. Existing tests for examples

