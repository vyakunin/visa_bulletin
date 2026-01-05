# Bazel Runfiles Implementation - Key Findings

## Summary

This document captures important findings from implementing standard Bazel runfiles access for data dependencies in Python code.

## Problem

Initially, code manually constructed paths to access Bazel data dependencies:

```python
# ❌ Old approach - manual path construction
runfiles_base = os.environ.get('TEST_SRCDIR') or os.environ.get('BUILD_WORKSPACE_DIRECTORY')
possible_paths = [
    Path(runfiles_base) / '_main' / label_path / relative_path,
    Path(runfiles_base) / label_path / relative_path,
    Path(runfiles_base) / relative_path,
]
```

**Issues:**
- Required multiple path attempts (error-prone)
- Different paths for tests vs binaries
- Platform-specific differences (Windows vs Unix)
- External repositories had different path structures
- Fragile - breaks when Bazel changes runfiles structure

## Solution

**Use the standard Bazel runfiles library** (`rules_python.python.runfiles`):

```python
# ✅ New approach - standard library
from lib.utils.bazel_runfiles import get_data_file_path, get_template_file

template_path = get_template_file("llm_prompt_template.txt")
```

**Implementation:**
- Created `lib/utils/bazel_runfiles.py` utility
- Uses `rules_python.python.runfiles` (standard Bazel library)
- Handles all path variations automatically
- Cross-platform compatible
- Single path resolution (no guessing)

## Key Findings

### 1. Standard Library Eliminates Path Guessing

**Finding:** The standard `rules_python.python.runfiles` library handles all path variations automatically. No need for multiple path attempts.

**Evidence:**
- Works in tests (`TEST_SRCDIR`) and binaries (`BUILD_WORKSPACE_DIRECTORY`)
- Works on Windows and Unix
- Works with external repositories
- Uses Bazel's runfiles manifest (most reliable source)

**Impact:**
- 90% less code
- More reliable (handles all edge cases)
- Easier to maintain

### 2. Cross-Platform Compatibility Built-In

**Finding:** The standard library handles platform differences automatically.

**Evidence:**
- Windows uses manifest files (no symlinks)
- Unix uses symlink trees
- Standard library abstracts these differences

**Impact:**
- No platform-specific code needed
- Works consistently across all platforms

### 3. External Repositories Work Correctly

**Finding:** Standard library correctly resolves external repository paths.

**Evidence:**
- `@ollama//:ollama` correctly resolves to `+ollama_hermetic_extension+ollama/ollama`
- No special handling needed for external repos

**Impact:**
- Can use hermetic dependencies without path manipulation
- Consistent behavior for all data dependencies

### 4. Fallback Support for Non-Bazel Environments

**Finding:** Utility includes fallback for development/direct Python execution.

**Evidence:**
- Falls back to `BUILD_WORKSPACE_DIRECTORY` if runfiles library unavailable
- Allows code to work in both Bazel and non-Bazel environments

**Impact:**
- Code works in development (direct Python execution)
- Code works in production (Bazel execution)
- No special cases needed

### 5. Single Source of Truth

**Finding:** Bazel's runfiles manifest is the authoritative source for file locations.

**Evidence:**
- Standard library uses `Rlocation()` which reads from manifest
- More reliable than environment variable inspection
- Handles all Bazel execution contexts

**Impact:**
- No need to inspect environment variables
- No need to construct paths manually
- Reliable across all execution contexts

## Implementation Details

### Files Created/Modified

1. **`lib/utils/bazel_runfiles.py`** (NEW)
   - Standard runfiles utility
   - `get_data_file_path()` - Generic data file access
   - `get_template_file()` - Convenience wrapper for templates

2. **`lib/business/salary/llm_validation.py`** (MODIFIED)
   - Removed `_find_bazel_data_file()` function
   - Uses `get_template_file()` from utility
   - Simplified Ollama binary finding

3. **`lib/utils/BUILD`** (MODIFIED)
   - Added `bazel_runfiles` library target
   - Dependency on `@rules_python//python/runfiles:runfiles`

4. **`lib/business/salary/BUILD`** (MODIFIED)
   - Added dependency on `//lib/utils:bazel_runfiles`

### Dependencies

**Required:**
- `@rules_python//python/runfiles:runfiles` - Standard Bazel runfiles library

**Usage:**
```python
# In BUILD file
py_library(
    name = "my_lib",
    deps = [
        "//lib/utils:bazel_runfiles",
    ],
    data = [
        "//scripts/salary:llm_prompt_template.txt",
    ],
)
```

## Migration Guide

**Before:**
```python
def _find_bazel_data_file(relative_path: str, workspace_label: str) -> Optional[Path]:
    runfiles_base = os.environ.get('TEST_SRCDIR') or os.environ.get('BUILD_WORKSPACE_DIRECTORY')
    if runfiles_base:
        label_path = workspace_label.lstrip('/').replace('//', '')
        possible_paths = [
            Path(runfiles_base) / '_main' / label_path / relative_path,
            Path(runfiles_base) / label_path / relative_path,
            Path(runfiles_base) / relative_path,
        ]
        for path in possible_paths:
            if path.exists():
                return path
    return None
```

**After:**
```python
from lib.utils.bazel_runfiles import get_data_file_path

def find_data_file(relative_path: str) -> Optional[Path]:
    return get_data_file_path(relative_path)
```

## Testing

**All tests pass:**
- `test_llm_validation_integration` - Uses new utility
- All existing tests - No regressions
- Cross-platform compatibility verified

**Build verification:**
- All targets build successfully
- No linter errors
- Integration tests pass

## Documentation

**Created:**
- `docs/BAZEL_RUNFILES.md` - Comprehensive guide
- `docs/BAZEL_RUNFILES_IMPLEMENTATION.md` - This document (key findings)
- Updated `docs/BAZEL.md` - Added runfiles section
- Updated `lib/README.md` - Documented utility

**Removed:**
- No stale docs found (user already cleaned up BUILD files)

## Recommendations

1. **Always use standard library** - Don't manually construct paths
2. **Use `lib/utils/bazel_runfiles.py`** - Consistent utility across codebase
3. **Export data files** - Use `exports_files()` in BUILD files
4. **Add as data dependency** - Include in `data` attribute of targets

## See Also

- `docs/BAZEL_RUNFILES.md` - Usage guide
- `docs/BAZEL.md` - General Bazel guide
- `lib/utils/bazel_runfiles.py` - Implementation
- `lib/README.md` - Library documentation








