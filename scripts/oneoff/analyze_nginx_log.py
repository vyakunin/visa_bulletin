#!/usr/bin/env python3
"""Parse nginx main_timed log and output traffic stats. One-off for prod analysis."""
import re
import sys
from collections import Counter
from urllib.parse import urlparse

# nginx: $remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"
# (request_time optional if main_timed format is used)
LOG_RE = re.compile(
    r'^(\S+) \S+ \S+ \[[^\]]+\] "(\w+) ([^ "]*) [^"]*" (\d+) (\d+) "([^"]*)" "([^"]*)"'
)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/prod_access.log"
    by_ip = Counter()
    by_url = Counter()
    by_referer = Counter()
    by_ua = Counter()
    slow = []  # (request_time, line_snippet)
    status = Counter()
    bots = Counter()

    bot_patterns = [
        "bot", "crawler", "spider", "scanner", "curl", "wget", "python-requests",
        "GPTBot", "Googlebot", "Bingbot", "SemrushBot", "MJ12bot", "AhrefsBot",
        "UptimeRobot", "PROPFIND", "HeadlessChrome", "PetalBot", "Bytespider",
        "Amazonbot", "facebookexternalhit", "Applebot", "DuckDuckBot",
    ]

    with open(path) as f:
        for line in f:
            m = LOG_RE.match(line.strip())
            if not m:
                continue
            ip, method, url, status_code, bytes_sent, referer, ua = m.groups()
            status_code = int(status_code)
            req_time = 0.0  # not in log format on prod

            by_ip[ip] += 1
            # Normalize URL: strip query for grouping
            path_only = urlparse(url).path or url
            if path_only == "/" or path_only.startswith("/?"):
                path_only = "/"
            by_url[path_only] += 1
            ref = referer.strip() or "-"
            if ref != "-":
                ref_domain = urlparse(ref).netloc or ref[:50]
                by_referer[ref_domain] += 1
            else:
                by_referer["(direct)"] += 1
            by_ua[ua[:80]] += 1
            status[status_code] += 1

            if req_time > 1.0:
                slow.append((req_time, method, path_only[:60], ip))

            ua_lower = ua.lower()
            for bp in bot_patterns:
                if bp.lower() in ua_lower or bp in ua:
                    bots[bp] += 1
                    break
            else:
                if any(x in ua_lower for x in ["bot", "crawler", "spider", "scanner"]):
                    bots["(other bot)"] += 1

    total = sum(by_ip.values())
    print("=== TRAFFIC SUMMARY ===")
    print(f"Total requests: {total}")
    print()

    print("=== TOP 20 IPs (request count) ===")
    for ip, c in by_ip.most_common(20):
        pct = 100 * c / total
        print(f"  {c:5d} ({pct:5.1f}%)  {ip}")
    print()

    print("=== TOP 25 URL paths ===")
    for path, c in by_url.most_common(25):
        pct = 100 * c / total
        print(f"  {c:5d} ({pct:5.1f}%)  {path}")
    print()

    print("=== TOP 15 referrers (domain) ===")
    for ref, c in by_referer.most_common(15):
        pct = 100 * c / total
        print(f"  {c:5d} ({pct:5.1f}%)  {ref}")
    print()

    print("=== BOT / CRAWLER counts (by pattern) ===")
    for name, c in bots.most_common(20):
        pct = 100 * c / total
        print(f"  {c:5d} ({pct:5.1f}%)  {name}")
    print()

    print("=== STATUS codes ===")
    for code, c in sorted(status.items(), key=lambda x: -x[1]):
        pct = 100 * c / total
        print(f"  {c:5d} ({pct:5.1f}%)  {code}")
    print()

    print("=== SLOW requests (>1s request_time) ===")
    slow.sort(key=lambda x: -x[0])
    for req_time, method, path, ip in slow[:25]:
        print(f"  {req_time:.2f}s  {method} {path}  [{ip}]")
    if not slow:
        print("  (none)")
    print()

    # Unthrottled: IPs with very high request count in this window
    print("=== HIGH REQUEST COUNT IPs (possible unthrottled bots) ===")
    threshold = max(50, total // 20)
    for ip, c in by_ip.most_common(30):
        if c >= threshold:
            print(f"  {c:5d} req  {ip}")
    print(f"  (threshold: {threshold} req)")


if __name__ == "__main__":
    main()
