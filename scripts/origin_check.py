#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Fetch visa-bulletin.us routes from the ORIGIN, bypassing Cloudflare.

WHY THIS EXISTS — verifying what the app actually served means reaching nginx
inside the prod container, not the public URL: the edge answers from its own
cache and challenges automated clients, so a public fetch tells you about
Cloudflare and not about the deploy. The origin has no TLS vhost of its own, so
every such fetch is `ssh homeserver` -> `docker exec vb_nginx` -> `wget` with an
explicit `Host:` header, and that command was hand-assembled ~35 times in the
week to 2026-08-23 alone (skill-extractor scan, flow #2).

Hand-assembly is where it goes wrong: the historical form nests
`ssh "... docker exec c sh -c \"wget --header=\\\"Host: ...\\\" ...\""`, three
levels of quoting deep, and a path holding `?` or `&` silently loses its query
string. This builds one remote argv and quotes it once — `docker exec` takes
argv directly, so no inner `sh -c` exists to escape through, and `wget -S`
writes its status line to stderr, which ssh hands back without a `2>&1`.

Usage
  origin_check.py status /  /salaries/ /predictions/september-2026/
  origin_check.py status --expect 404 '/salaries/?q=ZZZNONEXISTENT999'
  origin_check.py status --env staging /employers/
  origin_check.py status --ua googlebot /h1b-salary/software-engineer/
  origin_check.py body /job-title/software-engineer/ | grep -c 'Country of birth'
  origin_check.py status --local /          # already ON homeserver
  origin_check.py status --print-command /  # show the argv, run nothing

Prereqs: ssh access to the `homeserver` alias (`--host` to override) and the
`vb_nginx` / `vb_stg_nginx` containers running there. No credentials, no deps.

Exit: 0 every path matched `--expect` · 1 a status mismatch (or an unreadable
status) · 2 transport failure (ssh/docker/wget could not run at all).
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import time

# Origin environments: the container that terminates HTTP, and the vhost name it
# routes on. The Host header is the whole point — nginx has no default server for
# these, so a request without it does not reach the app.
ENVS = {
    "prod": {"container": "vb_nginx", "host_header": "visa-bulletin.us"},
    "staging": {"container": "vb_stg_nginx", "host_header": "staging.visa-bulletin.us"},
}

# Googlebot is worth a name: several surfaces (h1b-salary) serve and cache
# differently by UA, so "works in a browser" is not evidence about the crawler.
USER_AGENTS = {
    "googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
}

DEFAULT_SSH_HOST = "homeserver"
_STATUS_RE = re.compile(r"HTTP/[\d.]+\s+(\d{3})")


def normalize_path(path: str) -> str:
    """A path is origin-relative and absolute; accept a bare or full-URL form."""
    path = path.strip()
    for prefix in ("https://", "http://"):
        if path.startswith(prefix):
            rest = path[len(prefix):]
            path = rest[rest.index("/"):] if "/" in rest else "/"
            break
    return path if path.startswith("/") else "/" + path


def remote_argv(path: str, *, env: str = "prod", body: bool = False,
                user_agent: str | None = None, timeout: int = 30) -> list[str]:
    """The argv to run ON the origin host: `docker exec <c> wget ...`.

    One list, no nested shell. `-S` puts the status line on stderr (kept even for
    a body fetch, so the caller can report a non-200 instead of an empty page).
    """
    cfg = ENVS[env]
    argv = ["docker", "exec", cfg["container"], "wget", "-q", "-S",
            f"--timeout={timeout}", "--tries=1",
            f"--header=Host: {cfg['host_header']}"]
    if user_agent:
        argv.append(f"--user-agent={USER_AGENTS.get(user_agent, user_agent)}")
    argv += ["-O", "-" if body else "/dev/null",
             f"http://127.0.0.1:80{normalize_path(path)}"]
    return argv


def local_argv(path: str, *, ssh_host: str | None = DEFAULT_SSH_HOST, **kw) -> list[str]:
    """The argv to run HERE. Without `ssh_host` the remote argv runs directly.

    The remote command is quoted exactly once: ssh concatenates its arguments and
    the login shell re-splits them, so a `Host:` header (a space) or a query
    string (`?`, `&`) needs quoting — and needs it only here.
    """
    argv = remote_argv(path, **kw)
    if not ssh_host:
        return argv
    return ["ssh", "-o", "BatchMode=yes", ssh_host,
            " ".join(shlex.quote(a) for a in argv)]


def parse_status(stderr: str) -> int | None:
    """Last HTTP status wget reported (the last one, so a redirect chain ends right)."""
    found = _STATUS_RE.findall(stderr)
    return int(found[-1]) if found else None


def fetch(path: str, *, ssh_host: str | None, timeout: int, **kw):
    """Run one fetch; return (status|None, body, elapsed_ms, transport_ok)."""
    argv = local_argv(path, ssh_host=ssh_host, timeout=timeout, **kw)
    start = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout + 20, errors="replace")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, "", int((time.monotonic() - start) * 1000), f"{exc}"
    elapsed = int((time.monotonic() - start) * 1000)
    status = parse_status(proc.stderr)
    if status is None:
        # No status line at all: ssh, docker or wget never got as far as a response.
        return None, proc.stdout, elapsed, (proc.stderr.strip() or "no HTTP status in output")
    return status, proc.stdout, elapsed, None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("verb", choices=("status", "body"))
    p.add_argument("paths", nargs="+")
    p.add_argument("--env", choices=sorted(ENVS), default="prod")
    p.add_argument("--expect", type=int, default=200, help="status every path must return (status verb)")
    p.add_argument("--ua", help="'googlebot', or a full User-Agent string")
    p.add_argument("--host", default=DEFAULT_SSH_HOST, help=f"ssh alias (default {DEFAULT_SSH_HOST})")
    p.add_argument("--local", action="store_true", help="already on the origin host; skip ssh")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--print-command", action="store_true", help="print the argv and exit")
    args = p.parse_args(argv)

    ssh_host = None if args.local else args.host
    common = dict(env=args.env, user_agent=args.ua, ssh_host=ssh_host, timeout=args.timeout)

    if args.print_command:
        for path in args.paths:
            print(shlex.join(local_argv(path, body=(args.verb == "body"), **common)))
        return 0

    if args.verb == "body":
        if len(args.paths) != 1:
            p.error("body takes exactly one path (it writes the page to stdout)")
        status, body, _, transport = fetch(args.paths[0], body=True, **common)
        if transport:
            print(f"ERROR: {transport}", file=sys.stderr)
            return 2
        sys.stdout.write(body)
        if status != args.expect:
            print(f"WARNING: {normalize_path(args.paths[0])} returned {status}, "
                  f"expected {args.expect}", file=sys.stderr)
            return 1
        return 0

    worst = 0
    for path in args.paths:
        status, _, elapsed, transport = fetch(path, body=False, **common)
        shown = normalize_path(path)
        if transport:
            print(f"{shown:<52} ERR   {transport.splitlines()[-1][:70]}")
            worst = max(worst, 2)
            continue
        ok = status == args.expect
        print(f"{shown:<52} {status}  {elapsed:>6}ms  {'ok' if ok else f'EXPECTED {args.expect}'}")
        if not ok:
            worst = max(worst, 1)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
