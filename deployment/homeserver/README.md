# Homeserver deployment

Production stack for **visa-bulletin.us** running on the Dell Wyse 5070 home lab.
TLS terminates at Cloudflare's edge; ingress comes in via a Cloudflare Tunnel
(`cloudflared` container) → `nginx` → `gunicorn`.

This directory is the authoritative source of truth for everything except secrets.
On a fresh box (or after a gdrive disaster-recovery restore), you can rebuild
the stack by copying these files into `/opt/stack/visa_bulletin/` and filling
in `.env`.

## ⚠️ Keep this in sync with the live box — it is NOT git-managed there

`/opt/stack/visa_bulletin/` is a plain directory, NOT a git checkout. Config
(`docker-compose.yml`, `nginx/*.conf`) is hand-edited on the box. **Every time
you edit config on the box, copy it back here in the same change and commit** —
otherwise this "source of truth" silently goes stale and a dead box cannot be
rebuilt. Re-sync with:

```bash
ssh homeserver "cat /opt/stack/visa_bulletin/docker-compose.yml"    > deployment/homeserver/docker-compose.yml
ssh homeserver "cat /opt/stack/visa_bulletin/nginx/rate-limit.conf" > deployment/homeserver/nginx/rate-limit.conf
ssh homeserver "cat /opt/stack/visa_bulletin/nginx/visa_bulletin.conf" > deployment/homeserver/nginx/visa_bulletin.conf
```

**Applying an nginx config edit:** the conf files are single-file `:ro` bind
mounts, so an `nginx -s reload` keeps serving the OLD inode after a rename-based
edit — you MUST `docker restart vb_nginx` (validate first with a throwaway
container on the `visa_bulletin_vb` network so the `web` upstream resolves).
**Applying a gunicorn/compose edit:** `docker compose up -d web` (recreates the
container, ~15s 502 window). Capture a pre/post baseline per
`.claude/rules/deployment.md`.

**Capacity / anti-saturation tuning (2026-06-04):** gunicorn runs
`--workers 3 --threads 4` (12 concurrent; was 2 threads) and `location /` carries
`limit_conn perip_conn 5` (per-IP concurrent-connection cap). This fixed the 504
cascade where bot/scraper bursts on uncached `/salaries` filter-combos starved
the 6-thread pool and timed out cheap pages. `real_ip` (CF-Connecting-IP) is set,
so the per-IP cap keys on the true client, not the Cloudflare edge.

## Files

| Path | Maps to on homeserver | Purpose |
|---|---|---|
| `docker-compose.yml` | `/opt/stack/visa_bulletin/docker-compose.yml` | 5-service stack: postgres, redis, web, nginx, cloudflared |
| `nginx/visa_bulletin.conf` | `/opt/stack/visa_bulletin/nginx/visa_bulletin.conf` | Server block, CF real-IP, gzip, security headers |
| `nginx/rate-limit.conf` | `/opt/stack/visa_bulletin/nginx/rate-limit.conf` | Log format, 26 bot UAs, per-/16 + total + general zones |
| `scripts/backup_to_gdrive.sh` | `/opt/stack/visa_bulletin/scripts/backup_to_gdrive.sh` | Daily `pg_dump` → rclone → Drive, 7d/4w/3m retention |
| `crontab.sample` | (install via `crontab -e`) | Hourly bulletin refresh + daily DB backup |
| `.env.example` | (copy to `/opt/stack/visa_bulletin/.env`, then `chmod 600`) | Secret skeleton |

## Rehydrate from scratch

1. Provision a fresh Ubuntu 24.04 host with Docker + docker-compose-v2 + rclone
   (see `~/.cursor/shared_rules/homeserver.mdc` for the base-image details).
2. `mkdir -p /opt/stack/visa_bulletin/{nginx,scripts,logs/cron,postgres-data,staticfiles,saved_pages}`
3. Copy the files from this directory into `/opt/stack/visa_bulletin/` preserving
   subdirectory structure.
4. Copy `.env.example` to `/opt/stack/visa_bulletin/.env`, fill in `DB_PASSWORD`,
   `DJANGO_SECRET_KEY`, `CF_TUNNEL_TOKEN`. `chmod 600 .env`.
5. Restore the latest Postgres dump from Drive:
   `rclone copy gdrive:visa_bulletin_backups/daily/<latest>.sql.gz /tmp/`
   then `docker-compose up -d postgres`,
   `zcat /tmp/<latest>.sql.gz | docker exec -i vb_postgres psql -U $DB_USER $DB_NAME`.
6. `docker-compose up -d` to bring up the rest.
7. Verify: `curl -sI https://visa-bulletin.us | head -1` should be `HTTP/2 200`.
8. Install cron: `crontab -e` and paste the contents of `crontab.sample` (or
   `(crontab -l; cat crontab.sample) | crontab -`).

## Differences from the Lightsail stack (`deployment/docker-compose.yml`)

- **Ingress:** Cloudflare Tunnel container instead of public-IP + Let's Encrypt.
- **Postgres:** runs inside the compose stack here, whereas Lightsail used a
  host-network Postgres (`host.docker.internal`).
- **Static files:** baked into the image *and* collected at boot
  (`collectstatic --noinput` is part of the web container's `command`) so nginx
  can serve them from a shared volume.
- **Rate limits:** ~2–4× more generous than Lightsail (homeserver has 4 cores +
  8 GB RAM vs Lightsail 2 GB) — see comments in `nginx/rate-limit.conf`.

## Things still NOT in this directory (intentional)

- `/opt/stack/visa_bulletin/.env` — secrets, never commit.
- `rclone.conf` (`~/.config/rclone/rclone.conf`) — has the OAuth token for the
  `gdrive` remote. Re-authorize on restore with `rclone config reconnect gdrive:`.
- `~/.ssh/authorized_keys` — host-level access, owned by the user not the stack.
- The Cloudflare Tunnel itself — managed in the Cloudflare Zero Trust dashboard,
  not in compose. The `CF_TUNNEL_TOKEN` in `.env` is enough to re-attach the
  container to the existing tunnel; reconfigure ingress rules via the dashboard
  or `cloudflared tunnel route dns`.
