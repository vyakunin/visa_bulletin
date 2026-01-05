# Building Docker Images Locally for Production

## Architecture Compatibility

**Your local machine (likely Apple Silicon/arm64):**
- Can build Docker images, but by default builds for your native architecture (arm64)

**Lightsail production (x86_64/amd64):**
- Requires linux/amd64 Docker images
- Does NOT need Bazel installed (Docker image contains pre-built artifacts)

## Current Setup (Recommended)

**GitHub Actions builds for you:**
- Automatically builds linux/amd64 images on GitHub Actions runners
- No local build needed
- Images pushed to `ghcr.io/vyakunin/visa_bulletin`

**Workflow:**
```bash
# 1. Push code/tag
git tag -a v1.2.3 -m "Release"
git push origin v1.2.3

# 2. GitHub Actions builds linux/amd64 image automatically
# 3. Deploy to Lightsail (pulls pre-built image)
./scripts/deploy-zero-downtime.sh ~/.ssh/lightsail_visa_bulletin 1.2.3
```

## Building Locally for Production (Cross-Platform)

If you need to build locally for Lightsail (amd64) from an Apple Silicon Mac:

### Option 1: Use Docker Buildx (Recommended for Local Testing)

```bash
# Enable buildx (if not already enabled)
docker buildx create --use --name multiarch-builder

# Build for linux/amd64 platform
docker buildx build \
  --platform linux/amd64 \
  --tag ghcr.io/vyakunin/visa_bulletin:local-amd64 \
  --load \
  .

# Test locally (will run via emulation, slower)
docker run -p 8000:8000 ghcr.io/vyakunin/visa_bulletin:local-amd64

# Or push directly to registry
docker buildx build \
  --platform linux/amd64 \
  --tag ghcr.io/vyakunin/visa_bulletin:local-amd64 \
  --push \
  .
```

**Note:** Cross-platform builds are slower (QEMU emulation) but work fine for testing.

### Option 2: Build Native Image for Local Testing

For local development/testing only (won't work on Lightsail):

```bash
# Build for your native architecture (arm64 on Apple Silicon)
docker build -t visa-bulletin:local .

# Run locally
docker run -p 8000:8000 visa-bulletin:local
```

**Warning:** This image won't run on Lightsail (different architecture).

## Why Bazel is in Dockerfile but Not Needed on Lightsail

The Dockerfile uses a **multi-stage build**:

1. **Builder stage** (`bazel-builder`):
   - Installs Bazel
   - Builds all artifacts with Bazel
   - Extracts built Python binaries and code

2. **Production stage** (`python:3.11-slim`):
   - Only contains Python runtime
   - Copies pre-built artifacts from builder stage
   - No Bazel needed

**Result:** Lightsail only needs Docker, not Bazel. All building happens in CI or during `docker build`.

## Architecture Details

**Dockerfile line 18:**
```dockerfile
RUN wget -O /usr/local/bin/bazel https://github.com/bazelbuild/bazelisk/releases/download/v1.19.0/bazelisk-linux-amd64
```

This downloads the amd64 Bazel binary. When building with `--platform linux/amd64`, Docker will:
- Use an amd64 base image
- Download the correct Bazel binary for amd64
- Build artifacts for amd64
- Create an amd64-compatible image

## Recommended Workflow

**For production deployments:**
1. ✅ Use GitHub Actions (automatic, fast, reliable)
2. ✅ No local build needed
3. ✅ Lightsail just pulls pre-built images

**For local testing:**
1. ✅ Use Bazel directly: `bazel run //:runserver`
2. ✅ Or use `docker-compose -f docker-compose.dev.yml` (builds for your architecture)
3. ⚠️ Only use cross-platform build if you need to test the exact production image locally

## Troubleshooting

**Error: "exec format error"**
- You're trying to run an amd64 image on arm64 (or vice versa)
- Solution: Use `--platform linux/amd64` when building, or use native build for local testing

**Error: "Bazel not found"**
- You're trying to run Bazel on Lightsail
- Solution: You don't need Bazel on Lightsail - use pre-built Docker images

**Build is slow**
- Cross-platform builds use QEMU emulation (slower)
- Solution: Use GitHub Actions for production builds, local builds only for testing








