# scripts/oneoff/attach_staging_ip_to_old_prod.py
"""One-off: attach the staging static IP to the old prod instance (e.g. after a rotation
where the staging IP reassign step was skipped or failed).

Use when staging is unreachable because the staging static IP was never re-attached
to the old prod (now staging) instance.

Usage:
  bazel run //scripts/oneoff:attach_staging_ip_to_old_prod -- VisaBulletin2GB
  # Or with custom static IP name:
  REFRESH_STAGING_STATIC_IP_NAME=YourStaging-ip bazel run //scripts/oneoff:attach_staging_ip_to_old_prod -- VisaBulletin2GB
  # Or: bazel run //scripts/oneoff:attach_staging_ip_to_old_prod -- --static-ip-name YourStaging-ip VisaBulletin2GB

Requires: AWS CLI configured (profile or env) with lightsail:AttachStaticIp, lightsail:DetachStaticIp.
"""

from __future__ import annotations

import argparse
import os
import sys

from scripts.cron.refresh.traffic_switch import attach_staging_static_ip_to_old_prod


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Attach staging static IP to old prod (staging) instance."
    )
    parser.add_argument(
        "instance_name",
        help="Lightsail instance name to attach to (e.g. VisaBulletin2GB, the old prod).",
    )
    parser.add_argument(
        "--static-ip-name",
        default=None,
        help="Staging static IP name (default: REFRESH_STAGING_STATIC_IP_NAME from env). Required if env not set.",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region (default: REFRESH_AWS_REGION or AWS_DEFAULT_REGION or us-east-1).",
    )
    args = parser.parse_args()

    static_ip_name = (args.static_ip_name or "").strip() or os.environ.get(
        "REFRESH_STAGING_STATIC_IP_NAME", ""
    ).strip()
    if not static_ip_name:
        parser.error(
            "Staging static IP name is required. Set REFRESH_STAGING_STATIC_IP_NAME in .env or pass --static-ip-name. "
            "Get the name from: aws lightsail get-static-ips --region us-east-1"
        )

    ok = attach_staging_static_ip_to_old_prod(
        static_ip_name,
        args.instance_name,
        region=args.region or None,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
