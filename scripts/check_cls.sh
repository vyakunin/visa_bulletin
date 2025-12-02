#!/bin/bash
# Quick CLS check using PageSpeed Insights API
# Usage: ./scripts/check_cls.sh [url]

URL="${1:-https://visa-bulletin.us}"
STRATEGY="${2:-mobile}"  # mobile or desktop

echo "🔍 Analyzing $URL ($STRATEGY)..."
echo ""

# Call PageSpeed Insights API
RESULT=$(curl -s "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=${URL}&strategy=${STRATEGY}&category=performance&category=accessibility")

# Extract key metrics using Python (since jq might not be installed)
python3 - <<EOF
import json
import sys

try:
    data = json.loads('''$RESULT''')
    
    # Extract scores
    perf_score = data['lighthouseResult']['categories']['performance']['score']
    a11y_score = data['lighthouseResult']['categories']['accessibility']['score']
    
    # Extract CLS
    audits = data['lighthouseResult']['audits']
    cls = audits['cumulative-layout-shift']['displayValue']
    cls_score = audits['cumulative-layout-shift']['score']
    
    # Extract FCP, LCP
    fcp = audits['first-contentful-paint']['displayValue']
    lcp = audits['largest-contentful-paint']['displayValue']
    
    # Extract layout shift elements
    cls_details = audits['cumulative-layout-shift'].get('details', {})
    items = cls_details.get('items', [])
    
    # Print results
    print("📊 PageSpeed Insights Results")
    print("=" * 60)
    print(f"🎯 Performance:    {int(perf_score * 100)}/100")
    print(f"♿ Accessibility:   {int(a11y_score * 100)}/100")
    print("")
    print("⚡ Core Web Vitals:")
    print(f"  FCP (First Contentful Paint):  {fcp}")
    print(f"  LCP (Largest Contentful Paint): {lcp}")
    print(f"  CLS (Cumulative Layout Shift):  {cls} {'✅ PASS' if cls_score >= 0.9 else '❌ FAIL'}")
    print("")
    
    if items:
        print("🔴 Layout Shift Elements:")
        for i, item in enumerate(items[:5], 1):  # Top 5 shifts
            node = item.get('node', {}).get('snippet', 'Unknown')
            score = item.get('score', 0)
            print(f"  {i}. Score: {score:.3f} - {node[:80]}")
    
    print("")
    print("=" * 60)
    
except Exception as e:
    print(f"❌ Error: {e}", file=sys.stderr)
    print("Raw response:", file=sys.stderr)
    print('''$RESULT'''[:500], file=sys.stderr)
    sys.exit(1)
EOF

echo ""
echo "💡 To test locally: ./scripts/check_cls.sh http://localhost:8000 mobile"

