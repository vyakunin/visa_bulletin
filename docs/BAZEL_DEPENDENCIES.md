# Bazel External Dependencies

## Ollama Dependency

### Hermetic Implementation

The project uses a hermetic implementation (`tools/ollama_hermetic.bzl`) that:
- ✅ **Downloads specific version** from GitHub releases (v0.5.5)
- ✅ **Cached by Bazel** in `~/.cache/bazel/repos`
- ✅ **Reproducible** with SHA-256 checksums
- ✅ **No system modifications** (fully hermetic)

**How it works:**
1. Downloads Ollama binary on first build
2. Caches in Bazel's external repository cache
3. Platform detection for OS/arch-specific downloads
4. SHA-256 verification for integrity

**Configuration in MODULE.bazel:**
```python
ollama = use_extension("//tools:ollama_hermetic.bzl", "ollama_hermetic_extension")
use_repo(ollama, "ollama")
```

**Benefits:**
- ✅ Hermetic (same version everywhere)
- ✅ Cached (Bazel caches downloads in `~/.cache/bazel/repos`)
- ✅ Reproducible (pinned version with SHA-256)
- ✅ No system modifications
- ✅ Works offline after first download

**Limitations:**
- Models still need to be pulled separately (not yet hermetically managed)
- Requires manual version updates (change version + checksum in `ollama_hermetic.bzl`)

See `docs/OLLAMA_DEPENDENCY_OPTIONS.md` for detailed documentation.
