# Contributing Guide

## Development Workflow

### Setting Up Your Environment

1. Run the setup script (installs Bazel if needed):
```bash
./setup.sh
```

2. Verify Bazel is installed:
```bash
bazel --version
```

3. Activate the virtual environment (for running refresh_data.py):
```bash
source ~/visa-bulletin-venv/bin/activate
```

### Running Tests

This project uses **Bazel** for building and testing. Before making changes, ensure all tests pass:

```bash
# Quick test run
bazel test //tests:test_parser

# Detailed output
bazel test //tests:test_parser --test_output=all

# Only show errors
bazel test //tests:test_parser --test_output=errors
```

**Legacy method** (without Bazel):
```bash
python -m unittest discover -s tests -v
```

### Making Changes

1. Create a new branch for your feature/fix:
```bash
git checkout -b feature-name
```

2. Make your changes to the code

3. If you modify dependencies, update `requirements.txt`

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

The `.git/hooks/pre-commit` script runs automatically before each commit and:
- Checks for Bazel installation
- Runs the full test suite via Bazel
- Blocks the commit if any tests fail
- Provides fast execution through Bazel's caching

To bypass the hook (not recommended):
```bash
git commit --no-verify
```

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

