# Disaster Recovery Runbook

> "Homeserver is dead, what do I do?" Read this top-to-bottom **before** there's an emergency. The actual scripts assume you've at least skimmed it.

## Strategy: cold-DR from snapshot

We don't keep a Lightsail instance running ($10/mo bundle billing) or stopped (Lightsail bills stopped instances at full bundle rate too). Instead:

- **Steady state:** zero Lightsail instances, zero static IPs, **one Lightsail snapshot** (`vb-prod-snapshot-2026-05-09`, ~$1/mo for 20–60 GB).
- **DR fires:** `failover.sh` creates a new instance from the snapshot, allocates a fresh static IP, restores the latest GDrive DB backup, flips DNS. ~10–15 min.
- **DR resolves:** `failback.sh` flips DNS back, **deletes** the DR instance and **releases** the static IP. We stop paying immediately. Snapshot stays.

**Tradeoff vs warm-stopped instances:** ~10× cheaper per month, ~3× slower to recover (10 min vs 30 s). For a hobby site, that's the right ratio.

## Pre-emergency checklist (do this **once**, before anything goes wrong)

- [ ] You have AWS CLI on this Mac with the `visa-bulletin-deploy` profile (`AWS_PROFILE=visa-bulletin-deploy aws lightsail get-snapshots --region us-east-1` should list the snapshot)
- [ ] `~/.ssh/lightsail_visa_bulletin` is your SSH key for Lightsail
- [ ] `~/tokens/cloudflare_api_token` has `Cloudflare One Connector: cloudflared (Edit)` + `Zone DNS (Edit)` scopes
- [ ] `rclone` is installed on Mac AND `gdrive:` remote is configured (`rclone about gdrive:` works)
- [ ] All scripts in this folder are `chmod +x`

Run preflight any time to verify everything's wired:
```bash
cd /Users/vyakunin/cursor_projects/visa_bulletin/deployment/dr
./preflight.sh
```

## The failure scenarios

### Scenario A: homeserver down for >5 min, no quick fix

```bash
./failover.sh
```

This:
1. Creates a new instance `vb-dr` from snapshot `vb-prod-snapshot-2026-05-09` (~3-5 min)
2. Allocates static IP `vb-dr-ip` and attaches it
3. Waits for SSH + Docker stack
4. Auto-restores latest GDrive backup into the new Postgres
5. Asks you to confirm before flipping CF DNS
6. Flips DNS → real users now hit the DR instance

**Time-to-recover:** ~10-15 min total.

**Data freshness:** at most ~24 h old (the latest GDrive daily backup, taken 1 AM UTC). Hourly bulletin updates between the last backup and "now" are not on the DR instance.

### Scenario B: traffic spike but homeserver is fine

Don't failover. Either:
- Tighten rate limits in `/opt/stack/visa_bulletin/nginx/rate-limit.conf` and `docker exec vb_nginx nginx -s reload`
- Or have CF block bad IPs at the edge (CF dashboard → Security → WAF)

### Scenario C: needed to fail over, homeserver is now recovered

```bash
./failback.sh
```

This:
1. Pre-flight: confirms homeserver tunnel is healthy via `--resolve` trick
2. Asks to flip DNS back to homeserver tunnel
3. Verifies homeserver is serving public traffic
4. **Deletes** the DR instance + releases the static IP (so billing stops immediately)
5. Snapshot stays — you can run failover.sh again any time

If homeserver lost data while the failure was happening (e.g. SSD died, restored from a backup that's now stale), be aware that the DR instance was running for a while and updated **its** DB via cron. To capture that data on homeserver post-failback:

```bash
# After failback, manually sync from DR instance back to homeserver
# (or before failback, dump from DR)
```

(In practice: visa_bulletin tracker tolerates 24h data gaps, so this is rarely needed.)

## Quick reference: DNS state flag

| State | Apex / www records | Used during |
|---|---|---|
| **Normal** | CNAME `<tunnel-id>.cfargotunnel.com` (proxied) | Default. Traffic → CF → tunnel → homeserver |
| **DR active** | A `<DR-instance-IP>` (proxied) | After `failover.sh`. Traffic → CF → DR Lightsail directly |

Check current state:
```bash
ZONE_ID="$(cat ~/tokens/cloudflare_zone_id_visa_bulletin)"
curl -s -H "Authorization: Bearer $(cat ~/tokens/cloudflare_api_token)" \
  "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/dns_records?name=visa-bulletin.us" \
  | python3 -m json.tool | grep -E '"type"|"content"'
```

## Snapshot freshness

The snapshot captures the OS, Docker, code, and a baseline DB. The DB inside the snapshot is from cutover (2026-05-08 ~22:00 UTC) — outdated. We always overwrite with the latest GDrive backup during failover.

**Periodic snapshot refresh:** every ~6 months, or when major changes happen on the homeserver stack (e.g. nginx config overhaul), take a fresh snapshot:

```bash
# 1. Spin up a new instance from current snapshot
./failover.sh   # decline the DNS prompt at the end
# 2. Update its config to match current homeserver state if needed
# 3. Take a new snapshot
aws lightsail create-instance-snapshot --instance-name vb-dr --instance-snapshot-name vb-prod-snapshot-YYYY-MM-DD
# 4. Wait for snapshot to be 'available'
# 5. Run ./failback.sh to delete the instance
# 6. Delete the OLD snapshot
aws lightsail delete-instance-snapshot --instance-snapshot-name vb-prod-snapshot-OLD
# 7. Update LIGHTSAIL_SNAPSHOT_NAME in _lib.sh to the new one
```

## Cost ledger

Steady state (no DR active):
- 1 snapshot, ~20 GB stored (Lightsail compresses): ~$1/month
- 0 instances, 0 static IPs

While DR is active (after failover, before failback):
- DR instance (small_3_0 bundle): $10/month, prorated hourly (~$0.014/hour)
- 1 static IP (attached to running instance): free
- Same 1 snapshot: $1/month

So a 24-hour failover costs about **$0.40 of bundle time** + the $1/mo snapshot. Cheap.

## Things this DOES NOT cover (gaps to fix when calmer)

- **No alerting.** You'll only know homeserver is down when someone tells you or you check yourself. Add UptimeRobot before relying on this runbook.
- **No automated DR test schedule.** This runbook should be drilled quarterly: actually run failover, confirm site works on Lightsail, run failback, confirm site works on homeserver. ~15 min round-trip.
- **Off-box config backup.** `/opt/stack/visa_bulletin/{docker-compose.yml, nginx/, scripts/, .env}` lives only on homeserver SSD. If SSD dies before the snapshot is refreshed, the snapshot will boot up with whatever config was current at snapshot time. Suggest committing the non-secret bits to a private git repo.
