# Bazel Build System Guide

## Overview

This project uses [Bazel](https://bazel.build/) for building and testing. Bazel provides:

- **Fast Builds**: Intelligent caching and incremental compilation
- **Reproducible**: Hermetic builds across different machines
- **Scalable**: Efficient parallelization of builds and tests
- **Cross-platform**: Consistent behavior across macOS, Linux, and Windows

## Quick Start

### Installation

Bazel is automatically installed by `./setup.sh` if you have Homebrew:

```bash
./setup.sh
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
- **`saved_pages/BUILD`**: Test data (HTML files)

### Configuration Files

- **`MODULE.bazel`**: Bzlmod module definition (Bazel 8+)
- **`WORKSPACE`**: Legacy workspace file (for backward compatibility)
- **`.bazelrc`**: Bazel configuration options
- **`.bazelversion`**: Pins Bazel version to 8.1.1

## Targets

### Library Targets

```bash
# Build entire lib package
bazel build //lib:lib

# Build individual modules
bazel build //lib:bulletin_parser
bazel build //lib:publication_data
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

2. Bazel will automatically fetch on next build

## Common Workflows

### Development Cycle

```bash
# 1. Make code changes
vim lib/bulletin_parser.py

# 2. Build to check compilation
bazel build //lib:bulletin_parser

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

# Force re-fetch dependencies
bazel sync --configure

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

