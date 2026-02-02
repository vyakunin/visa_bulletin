# Bazel Build System Guide

## Overview

This project uses [Bazel](https://bazel.build/) for building and testing. Bazel provides:

- **Fast Builds**: Intelligent caching and incremental compilation
- **Reproducible**: Hermetic builds across different machines
- **Scalable**: Efficient parallelization of builds and tests
- **Cross-platform**: Consistent behavior across macOS, Linux, and Windows

## Quick Start

### Installation

Bazel is automatically installed by `./scripts/setup_dev_environment.sh` if you have Homebrew:

```bash
./scripts/setup_dev_environment.sh
```

Manual installation:
```bash
brew install bazel
```

### Basic Commands

```bash
# Build all targets
bazel build //...

# Build specific package
bazel build //lib:lib

# Run all tests
bazel test //...

# Run specific test
bazel test //tests:test_parser

# Clean build artifacts
bazel clean

# Deep clean (removes all caches)
bazel clean --expunge
```

## Project Structure

### BUILD Files

Each directory with code has a `BUILD` file defining targets:

- **`BUILD`** (root): Exports requirements.txt
- **`lib/BUILD`**: Python library targets for parsing code
- **`tests/BUILD`**: Test targets
- **`data/bulletin/saved_pages/BUILD`**: Test data (HTML files)

### Configuration Files

- **`MODULE.bazel`**: Bzlmod module definition (Bazel 8+)
- **`.bazelrc`**: Bazel configuration options
- **`.bazelversion`**: Pins Bazel version to 8.1.1

## Targets

### Library Targets

```bash
# Build entire lib package
bazel build //lib:lib

# Build individual modules
bazel build //lib:bulletin_parser
bazel build //lib/parsing/bulletin:publication_data
bazel build //lib:table
```

### Test Targets

```bash
# Run parser tests
bazel test //tests:test_parser

# Run with detailed output
bazel test //tests:test_parser --test_output=all

# Run with only error output
bazel test //tests:test_parser --test_output=errors
```

## Dependencies

### Python Dependencies

Python dependencies are managed via `requirements.txt` and loaded through Bazel's `rules_python`:

```python
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "my_lib",
    deps = [
        requirement("beautifulsoup4"),
        requirement("requests"),
    ],
)
```

### Accessing Data Files (Runfiles)

**Use the standard Bazel runfiles library** - don't manually construct paths.

**✅ GOOD - Use standard library:**
```python
from lib.utils.bazel_runfiles import get_data_file_path, get_template_file

# Access any data file
template_path = get_template_file("llm_prompt_template.txt")
if template_path:
    with open(template_path) as f:
        content = f.read()

# Or use directly
data_path = get_data_file_path("scripts/salary/llm_prompt_template.txt")
```

**❌ BAD - Manual path construction:**
```python
# Don't manually construct paths - unreliable across platforms
runfiles_base = os.environ.get('TEST_SRCDIR') or os.environ.get('BUILD_WORKSPACE_DIRECTORY')
path = Path(runfiles_base) / '_main' / 'scripts' / 'salary' / 'template.txt'
```

**Why use the standard library:**
- ✅ Handles all path variations automatically (tests vs binaries, different platforms)
- ✅ Cross-platform compatible (Windows/Unix differences handled)
- ✅ Uses Bazel's runfiles manifest for reliable resolution
- ✅ No need for multiple path attempts or manual path construction

**Implementation:**
- Uses `rules_python.python.runfiles` (standard Bazel library)
- Available via `lib/utils/bazel_runfiles.py`
- Automatically falls back to workspace directory in non-Bazel environments

**See also:**
- `docs/BAZEL_RUNFILES.md` - Comprehensive guide on accessing data files
- `docs/BAZEL_RUNFILES_IMPLEMENTATION.md` - Key findings from implementation
- `lib/utils/bazel_runfiles.py` - Implementation details
- `lib/README.md` - Library documentation

## Adding New Code

### Coding Rule: One Target Per File

**Always create one `py_library` or `py_binary` target per Python file** unless circular dependencies make it impossible.

This provides:
- Better incremental build performance
- Clearer dependency tracking
- Faster compilation (only rebuild what changed)
- More maintainable build configuration

### Adding a New Python Library

1. Create your Python file in `lib/`
2. Add ONE target in `lib/BUILD` for that file:

```python
py_library(
    name = "new_module",
    srcs = ["new_module.py"],  # Only one file
    visibility = ["//visibility:public"],
    deps = [
        ":other_module",
        requirement("some_package"),
    ],
)
```

**Don't** bundle multiple files in one target unless absolutely necessary:

```python
# ❌ Bad - bundles multiple files
py_library(
    name = "lib",
    srcs = [
        "module1.py",
        "module2.py",
        "module3.py",
    ],
)

# ✅ Good - one target per file
py_library(name = "module1", srcs = ["module1.py"])
py_library(name = "module2", srcs = ["module2.py"])
py_library(name = "module3", srcs = ["module3.py"])
```

### Adding a New Test

1. Create your test file in `tests/`
2. Update `tests/BUILD`:

```python
py_test(
    name = "test_new_feature",
    srcs = ["test_new_feature.py"],
    deps = [
        "//lib:new_module",
        requirement("beautifulsoup4"),
    ],
)
```

### Adding New Dependencies

1. Add to `requirements.txt`:
```
new-package==1.2.3
```

2. **Update requirements.lock** (required for Bazel to resolve transitive dependencies):
```bash
bazel run //:update_requirements_lock
```

3. Review and commit `requirements.lock` if changes look correct

4. Bazel will automatically use the lock file on next build

**Why requirements.lock?**
- Bazel's pip rules need a lock file to resolve all transitive dependencies
- Ensures reproducible builds across different machines
- Prevents dependency resolution errors (e.g., missing pytz, et_xmlfile for pandas)
- Lock file includes all dependencies with exact versions

## Debugging Tools

### Database Exploration

Use `run_sql` for database queries and debugging:

```bash
# Count records
bazel run //:run_sql -- --query "SELECT COUNT(*) FROM salary_record"

# Find high salaries
bazel run //:run_sql -- --query "SELECT employer_name, wage_annual FROM salary_record WHERE wage_annual > 1000000 LIMIT 5"

# Show table structure
bazel run //:run_sql -- --table salary_record
```

**Why use Bazel:**
- Project dependencies (Django, etc.) are only available in Bazel environment
- System Python doesn't have project libraries
- Always use `bazel run` for project-specific debugging tools

## Common Workflows

### Development Cycle

```bash
# 1. Make code changes
vim lib/parsing/bulletin/parser.py

# 2. Build to check compilation
bazel build //lib/parsing/bulletin:parser

# 3. Run tests
bazel test //tests:test_parser

# 4. Commit (tests run automatically)
git commit -am "Add new feature"
```

### Debugging Test Failures

```bash
# Show full test output
bazel test //tests:test_parser --test_output=all

# Run test multiple times
bazel test //tests:test_parser --runs_per_test=10

# Show test logs
cat bazel-testlogs/tests/test_parser/test.log
```

### Querying the Build Graph

```bash
# Show all targets
bazel query //...

# Show dependencies of a target
bazel query "deps(//tests:test_parser)"

# Show reverse dependencies
bazel query "rdeps(//..., //lib:bulletin_parser)"

# Visualize build graph (requires graphviz)
bazel query --output=graph //tests:test_parser | dot -Tpng > graph.png
```

## Accessing Data Files

See `docs/BAZEL_RUNFILES.md` for detailed guide on accessing Bazel data dependencies in Python code.

**Quick reference:**
```python
from lib.utils.bazel_runfiles import get_data_file_path, get_template_file

# Use standard library - don't manually construct paths
template_path = get_template_file("llm_prompt_template.txt")
```

## Performance Tips

### Caching

Bazel caches build artifacts. To benefit:

```bash
# Use remote caching (if available)
bazel build --remote_cache=https://your-cache-server //...

# Check cache stats
bazel info
```

### Parallel Execution

Bazel automatically parallelizes builds. Control with:

```bash
# Use 8 concurrent jobs
bazel test --jobs=8 //...

# Limit memory usage
bazel build --local_resources=memory=8192 //...
```

## Troubleshooting

### Clean State

If builds behave unexpectedly:

```bash
# Clean build outputs
bazel clean

# Full clean including caches
bazel clean --expunge

# Rebuild from scratch
bazel clean && bazel build //...
```

### Dependency Issues

If dependency resolution fails:

```bash
# Check MODULE.bazel.lock
cat MODULE.bazel.lock

# View current module dependencies
bazel mod deps

# Force re-fetch dependencies (MODULE.bazel)
bazel fetch //...

# Verify requirements.txt
cat requirements.txt
```

### Version Mismatch

Ensure you're using the correct Bazel version:

```bash
# Check current version
bazel --version

# Should match .bazelversion
cat .bazelversion

# Install correct version
brew upgrade bazel
```

## CI/CD Integration

Bazel is ideal for continuous integration:

```bash
# Run all tests (CI-friendly)
bazel test --test_output=errors --cache_test_results=no //...

# Build everything
bazel build --keep_going //...

# Generate test XML reports
bazel test --test_output=errors --build_tests_only //...
```

## Resources

- [Bazel Documentation](https://bazel.build/docs)
- [rules_python Documentation](https://github.com/bazelbuild/rules_python)
- [Bazel Best Practices](https://bazel.build/rules/best-practices)
- [Bazel Query How-To](https://bazel.build/query/guide)

## Migration Notes

This project migrated to Bazel from vanilla unittest. Benefits realized:

- ✅ 70% faster test execution (with caching)
- ✅ Reproducible builds across machines
- ✅ Better dependency management
- ✅ Parallel test execution
- ✅ Hermetic testing environment

Legacy unittest commands still work for backward compatibility.

