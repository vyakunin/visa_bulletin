# PageSpeed Optimizations

This document tracks major performance optimization decisions and their tradeoffs.

## Critical Decision: Bootstrap CSS Loading Strategy

### Background

Bootstrap CSS is the foundation of our layout system. We evaluated two loading strategies:

1. **Async loading** (via `rel="preload" as="style" onload="..."`)
2. **Synchronous loading** (traditional `<link rel="stylesheet">`)

### The CLS Problem

Initial implementation used async loading to optimize FCP (First Contentful Paint). However, Lighthouse trace analysis revealed:

```
Layout Shift Events (Total CLS: 0.216):
1. Shift #1 (0.0402): Navbar/hero area shifted DOWN 34px
2. Shift #2 (0.1755): Chart/projection area shifted UP 51px  ← Main culprit
3. Shift #3 (0.0012): Minor text adjustments

Root Cause: Bootstrap CSS applying AFTER initial paint
```

### Decision: Synchronous Loading

**Rationale:**
- Bootstrap defines critical layout properties (grid, spacing, sizing)
- Async loading means initial render uses only inlined critical CSS
- Even extensive critical CSS inlining couldn't prevent shifts
- The ~50ms render-blocking cost is acceptable for layout stability

### Results

| Metric | Before (Async) | After (Sync) | Change |
|--------|----------------|--------------|--------|
| **CLS** | 0.216 ❌ | 0.001 ✅ | **-99.5%** |
| **Performance** | 90 | 98-99 | **+8-9 pts** |
| **FCP** | 0.7s | 1.8s | +1.1s |
| **LCP** | 0.7s | 1.8s | +1.1s |

### Why Performance IMPROVED Despite Slower Paint?

Counter-intuitively, blocking render actually improved our Performance score because:

1. **CLS is weighted heavily** in Performance score (25% weight)
2. Eliminating 0.216 CLS added ~15 points
3. FCP/LCP delay cost ~7 points
4. **Net gain: +8 points**

### Key Insight

For layout-critical CSS frameworks like Bootstrap:
- **Render-blocking is the right choice**
- User perceives "loading" better than "content jumping around"
- Lighthouse agrees: 0.001 CLS + 1.8s LCP > 0.216 CLS + 0.7s LCP

### Alternative Approaches Considered

**1. Extensive Critical CSS Inlining**
- ❌ Tried: Inlined Bootstrap grid, forms, buttons (~5KB)
- ❌ Result: Still had 0.215 CLS
- ❌ Reason: Can't replicate full Bootstrap behavior

**2. CSS-in-JS / Atomic CSS**
- ❌ Too radical for this project
- ❌ Would require complete rewrite

**3. Server-Side Rendering (SSR)**
- ⚠️ Might help, but adds complexity
- ⚠️ Still need Bootstrap CSS before HTML parse

**4. HTTP/2 Push**
- ⚠️ Deprecated in HTTP/3
- ⚠️ Doesn't solve the fundamental timing issue

### Lesson Learned

**Not all render-blocking is bad.** When CSS is truly critical for layout:
1. Make it synchronous
2. Minimize its size
3. Serve from CDN
4. Accept the 50-100ms cost

The alternative (async + CLS) is worse for both users and metrics.

---

## Other Optimizations

### ✅ Bootstrap Icons - Deferred
- Strategy: `media="print" onload="this.media='all'"`
- Rationale: Icons are non-critical decorations
- Impact: -0.2s LCP

### ✅ Plotly.js - Lazy Loaded
- Strategy: Intersection Observer + dynamic script loading
- Rationale: Chart is below fold, 332KB bundle
- Impact: -1.0s FCP

### ✅ GoatCounter Analytics - Async
- Strategy: `<script async>`
- Rationale: Non-critical for UX
- Impact: No blocking

### ✅ Critical CSS Inlining
- Strategy: Inline minimal Bootstrap CSS (grid, forms, buttons)
- Purpose: Prevent FOUC during Bootstrap load
- Size: ~3KB
- Note: Doesn't eliminate need for sync Bootstrap

---

## Testing Methodology

All metrics verified using **Lighthouse CLI** (local):

```bash
lighthouse http://localhost:8000 \
  --only-categories=performance,accessibility \
  --preset=perf \
  --quiet \
  --chrome-flags="--headless" \
  --emulated-form-factor=mobile
```

**Why local testing?**
- Faster iteration (30s vs 2min)
- Consistent network conditions
- No rate limits
- Trace data available for debugging

**Production verification:**
- PageSpeed Insights: https://pagespeed.web.dev/
- Test after each deployment
- Expect ±5% variance from local results

---

## Future Optimizations (Not Implemented)

### Potential Gains
- [ ] Self-host Bootstrap CSS (~100ms CDN latency)
- [ ] Preload fonts with `crossorigin` attribute
- [ ] Image lazy loading (when images added)
- [ ] Service Worker caching

### Low Priority
- ❌ Inline all Bootstrap CSS (too large, ~25KB)
- ❌ Remove Bootstrap (too much work, small gain)
- ❌ HTTP/2 Server Push (deprecated)

---

Last Updated: December 2, 2025
Lighthouse Version: 11.x
Chrome Version: 120+

