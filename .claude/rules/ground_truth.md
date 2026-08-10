# Ground Truth for Site State

When answering any question about *what's currently live* on visa-bulletin.us — content, blog posts, predictions, employer data, salary records, response codes, redirects — **use prod as the source of truth in this order**:

1. **Live site (HTTP)** — `curl -sSL https://visa-bulletin.us/<path>` for anything user-visible: HTML, JSON-LD, sitemap, robots.txt, response codes, redirect chains. This is the fastest, lowest-risk check and matches what real users see.
2. **Prod Postgres on the production server** — `ssh homeserver "docker exec vb_postgres psql -U visa_bulletin_user visa_bulletin -c '<query>'"` for state not exposed via HTTP (auto-gen flags, ingest run history, raw row counts, FK relationships). **Use read-only queries** (`SELECT`). Be mindful: prod serves real traffic on a small, resource-constrained box — avoid full-table scans on large tables (`salary_record`, `lca_case`, `dol_case`); add `LIMIT` and indexed `WHERE` clauses. (`homeserver` is the SSH alias for prod; concrete host/key are in the private ops repo.)
3. **Prod cron / app logs** — `ssh homeserver "tail -N /opt/stack/visa_bulletin/logs/cron/*.log"` or `docker logs vb_web` for "did this actually run and what happened" questions.
4. **Staging (`vb_stg_*` containers)** — only when comparing a code change between staging and prod; **not authoritative** for prod state.

## Local DB is a development vehicle — treat as outdated

`/Users/vyakunin/cursor_projects/visa_bulletin/visa_bulletin.db` (and any local Postgres on the Mac) is for code/test/migration work. **Do not treat local-DB state as evidence about the live site.** It can be days, weeks, or months behind prod, and its blog posts / bulletins / employer rows may not match what users see. If a question is about live behavior, switch to source 1–3 above before answering.

## Reporting evidence

When making a claim about live state (e.g. "we have N blog posts", "X URL is broken", "auto-publish didn't fire"), cite at least one of the prod sources by name in the response, with the timestamp of the check. Bare assertions like "we have 3 posts" without a source are not acceptable — they have caused at least one false-alarm investigation already.

## Caveats

- `vb_postgres` and `vb_stg_postgres` are different DBs. Always specify which one a result came from.
- Cloudflare caches some pages; if the curl result looks stale, add `-H "Cache-Control: no-cache"` or hit the origin via `--resolve visa-bulletin.us:443:<homeserver-lan-ip>` from the LAN.
- **`curl` to `/employer/*` and `/job-title/*` gets Cloudflare's challenge page, not the site — and the challenge page carries `<meta name="robots" content="noindex,nofollow">`.** The managed-challenge rule on the profile surfaces answers **403** with `<title>Just a moment...</title>` to curl regardless of `-A`, because it fingerprints the TLS handshake, not the User-Agent. So a curl-based scrape of those paths measures the challenge, not the page: sampling sitemap URLs this way reports the whole profile long tail as noindexed, which is false. Verified bots (Googlebot, bingbot) are exempt and reach origin normally — 22.3k `/job-title/` + 21.2k `/employer/` hits in a 24h nginx window — so this is scraper mitigation working, not a regression. **Always check the status code and `<title>` before believing any parsed field**; a 403 titled "Just a moment..." means you read Cloudflare. To read the real HTML, go to the origin and bypass the edge entirely:
  ```bash
  ssh homeserver 'docker exec vb_nginx sh -c \
    "wget -qO- --header=\"Host: visa-bulletin.us\" http://127.0.0.1:80/employer/<slug>/"'
  ```
  (`vb_web` ships no curl/wget — run it from `vb_nginx`, per `deployment.md`.)
- Don't `EXPLAIN ANALYZE` heavy queries on prod without telling the user first.
