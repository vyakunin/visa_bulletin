# Accessing Bazel Data Dependencies in Python

## Overview

When Python code needs to access data files (templates, configs, binaries) that are declared as `data` dependencies in BUILD files, use the **standard Bazel runfiles library** instead of manually constructing paths.

## Standard Solution

**Use `lib/utils/bazel_runfiles.py`:**

```python
from lib.utils.bazel_runfiles import get_data_file_path, get_template_file

# Access template files
template_path = get_template_file("llm_prompt_template.txt")
if template_path:
    with open(template_path) as f:
        content = f.read()

# Access any data file
data_path = get_data_file_path("scripts/salary/llm_prompt_template.txt")
```

## Why Not Manual Path Construction?

**❌ BAD - Manual path construction:**
```python
# Unreliable - different paths for tests vs binaries, different platforms
runfiles_base = os.environ.get('TEST_SRCDIR') or os.environ.get('BUILD_WORKSPACE_DIRECTORY')
possible_paths = [
    Path(runfiles_base) / '_main' / label_path / relative_path,
    Path(runfiles_base) / label_path / relative_path,
    Path(runfiles_base) / relative_path,
]
# Still might not work on Windows or in different execution contexts
```

**Problems with manual approach:**
- ❌ Different paths for tests (`TEST_SRCDIR`) vs binaries (`BUILD_WORKSPACE_DIRECTORY`)
- ❌ Different paths on Windows vs Unix
- ❌ External repositories have different path structures
- ❌ Requires multiple path attempts (error-prone)
- ❌ Breaks when Bazel changes runfiles structure

**✅ GOOD - Standard library:**
```python
from lib.utils.bazel_runfiles import get_data_file_path

# Standard library handles all variations automatically
path = get_data_file_path("scripts/salary/llm_prompt_template.txt")
```

**Benefits:**
- ✅ Handles all path variations automatically
- ✅ Cross-platform compatible
- ✅ Works in tests, binaries, and external repos
- ✅ Uses Bazel's runfiles manifest (most reliable)
- ✅ Single path resolution (no guessing)

## Implementation Details

**Under the hood:**
- Uses `rules_python.python.runfiles` (standard Bazel library)
- Calls `runfiles.Create().Rlocation()` for path resolution
- Handles workspace name prefix automatically
- Falls back to workspace directory in non-Bazel environments

**Dependencies:**
```python
# In BUILD file
py_library(
    name = "my_lib",
    deps = [
        "//lib/utils:bazel_runfiles",  # Standard runfiles utilities
    ],
    data = [
        "//scripts/salary:llm_prompt_template.txt",  # Data dependency
    ],
)
```

**Export data files:**
```python
# In scripts/salary/BUILD
exports_files(["llm_prompt_template.txt"])  # Make available as Bazel resource
```

## Examples

### Example 1: Template File

```python
from lib.utils.bazel_runfiles import get_template_file

def load_template():
    template_path = get_template_file("llm_prompt_template.txt")
    if not template_path:
        raise FileNotFoundError("Template not found in Bazel runfiles")
    with open(template_path) as f:
        return f.read()
```

### Example 2: External Repository Binary

```python
from rules_python.python.runfiles import runfiles

def find_ollama_binary():
    r = runfiles.Create()
    # External repos: @ollama//:ollama becomes +ollama_hermetic_extension+ollama/ollama
    path = r.Rlocation("+ollama_hermetic_extension+ollama/ollama")
    if path and Path(path).exists():
        return path
    return None
```

### Example 3: Config File

```python
from lib.utils.bazel_runfiles import get_data_file_path

def load_config():
    config_path = get_data_file_path("config/settings.yaml")
    if not config_path:
        # Fallback to default
        return default_config
    with open(config_path) as f:
        return yaml.safe_load(f)
```

## Key Findings

**From implementation experience:**

1. **Standard library eliminates path guessing** - No need for multiple path attempts when using `rules_python.python.runfiles`

2. **Cross-platform compatibility** - Standard library handles Windows/Unix differences automatically

3. **External repositories work correctly** - Standard library resolves external repo paths (e.g., `@ollama//:ollama`)

4. **Fallback support** - `lib/utils/bazel_runfiles.py` includes fallback for non-Bazel environments (development, direct Python execution)

5. **Single source of truth** - Bazel's runfiles manifest is the authoritative source for file locations

## Migration from Manual Paths

**Before (manual paths):**
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

**After (standard library):**
```python
from lib.utils.bazel_runfiles import get_data_file_path

def find_data_file(relative_path: str) -> Optional[Path]:
    return get_data_file_path(relative_path)
```

**Benefits:**
- ✅ 90% less code
- ✅ More reliable (handles all edge cases)
- ✅ Easier to maintain
- ✅ Works across all platforms and execution contexts

## See Also

- `lib/utils/bazel_runfiles.py` - Implementation
- `lib/README.md` - Library documentation
- `docs/BAZEL.md` - General Bazel guide
- [Bazel runfiles documentation](https://bazel.build/reference/test-encyclopedia#runfiles)








