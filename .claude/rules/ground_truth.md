# Ground Truth for Site State

When answering any question about *what's currently live* on visa-bulletin.us — content, blog posts, predictions, employer data, salary records, response codes, redirects — **use prod as the source of truth in this order**:

1. **Live site (HTTP)** — `curl -sSL https://visa-bulletin.us/<path>` for anything user-visible: HTML, JSON-LD, sitemap, robots.txt, response codes, redirect chains. This is the fastest, lowest-risk check and matches what real users see.
2. **Prod Postgres on the homeserver** — `ssh homeserver.local "docker exec vb_postgres psql -U visa_bulletin_user visa_bulletin -c '<query>'"` for state not exposed via HTTP (auto-gen flags, ingest run history, raw row counts, FK relationships). **Use read-only queries** (`SELECT`). Be mindful: prod serves real traffic on a 4-core / 8 GB box — avoid full-table scans on large tables (`salary_record`, `lca_case`, `dol_case`); add `LIMIT` and indexed `WHERE` clauses.
3. **Prod cron / app logs** — `ssh homeserver.local "tail -N /opt/stack/visa_bulletin/logs/cron/*.log"` or `docker logs vb_web` for "did this actually run and what happened" questions.
4. **Staging (`vb_stg_*` containers)** — only when comparing a code change between staging and prod; **not authoritative** for prod state.

## Local DB is a development vehicle — treat as outdated

`/Users/vyakunin/cursor_projects/visa_bulletin/visa_bulletin.db` (and any local Postgres on the Mac) is for code/test/migration work. **Do not treat local-DB state as evidence about the live site.** It can be days, weeks, or months behind prod, and its blog posts / bulletins / employer rows may not match what users see. If a question is about live behavior, switch to source 1–3 above before answering.

## Reporting evidence

When making a claim about live state (e.g. "we have N blog posts", "X URL is broken", "auto-publish didn't fire"), cite at least one of the prod sources by name in the response, with the timestamp of the check. Bare assertions like "we have 3 posts" without a source are not acceptable — they have caused at least one false-alarm investigation already.

## Caveats

- `vb_postgres` and `vb_stg_postgres` are different DBs. Always specify which one a result came from.
- Cloudflare caches some pages; if the curl result looks stale, add `-H "Cache-Control: no-cache"` or hit the origin via `--resolve visa-bulletin.us:443:<homeserver-lan-ip>` from the LAN.
- Don't `EXPLAIN ANALYZE` heavy queries on prod without telling the user first.
