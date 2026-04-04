# scripts/cron/refresh/orchestrate.py
"""Orchestrator: resolve active/inactive, start inactive, run pipeline on inactive,
smoke, (optional) traffic switch + graduation, stop old."""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from . import instance, services, traffic_switch
from .config import RefreshConfig, load_config, update_env_value
from .pipeline import run_pipeline
from .runner import RemoteRunner
from .steps import PipelineContext, step_run_smoke_tests, step_warm_cache

if TYPE_CHECKING:
    from .runner import Runner

logger = logging.getLogger(__name__)

GRADUATION_STEPS = ("warm_cache", "smoke_tests", "traffic_switch")


def _verify_post_graduation(
    remote: Runner,
    remote_root: str,
    active_info: instance.InstanceInfo,
    staging_static_ip_name: str | None,
    skip_staging_ip: bool,
) -> None:
    """
    Non-fatal verification that all post-graduation steps completed correctly.
    Logs errors with manual recovery commands for any failed checks.
    Called after all post-switch steps, before the safety interval.
    """
    issues: list[str] = []

    # 1. Staging IP attached to old prod (active_info = orchestrator host, now staging)
    if not skip_staging_ip and staging_static_ip_name:
        if not traffic_switch.verify_staging_ip_attached(
            staging_static_ip_name, active_info.name
        ):
            issues.append(
                f"Staging IP {staging_static_ip_name!r} not attached to {active_info.name!r}. "
                f"Manual fix: aws lightsail attach-static-ip "
                f"--static-ip-name {staging_static_ip_name} "
                f"--instance-name {active_info.name} --region us-east-1"
            )
    else:
        logger.info("Skipping staging IP check (reassign skipped or IP name unset)")

    # 2. Git branch on new prod should be 'prod'
    try:
        result = remote.run_shell(
            f"cd {remote_root} && git rev-parse --abbrev-ref HEAD",
            timeout_sec=10,
        )
        branch = (result.stdout or "").strip()
        if branch != "prod":
            issues.append(
                f"New prod git branch is {branch!r}, expected 'prod'. "
                f"Manual fix: ssh new_prod 'cd {remote_root} && git fetch origin prod && "
                f"git checkout prod && git reset --hard origin/prod'"
            )
    except Exception as e:
        issues.append(f"Could not check git branch on new prod: {e}")

    # 3. New prod HTTP health
    if not _wait_app_healthy_via_ssh(remote, timeout_sec=30):
        issues.append("New prod HTTP health check failed (curl localhost:8000 not returning 200)")

    # 4. Cron installed on new prod (bulletin refresh should run hourly)
    try:
        cron_result = remote.run_shell("crontab -l 2>/dev/null | grep -c refresh_bulletin || true", timeout_sec=10)
        cron_count = int((cron_result.stdout or "").strip() or "0")
        if cron_count == 0:
            issues.append(
                "Bulletin refresh cron not found on new prod. "
                "Manual fix: ssh new_prod 'cd /opt/visa_bulletin && bash deployment/cron/setup-ingest-cron.sh'"
            )
        else:
            logger.info("Bulletin refresh cron verified (%d entries)", cron_count)
    except Exception as e:
        issues.append(f"Could not check cron on new prod: {e}")

    # 5. Orchestrator binary exists on new prod
    try:
        bin_result = remote.run_shell(
            f"test -x {remote_root}/bazel-bin/scripts/cron/refresh_and_switch_py && echo ok || echo missing",
            timeout_sec=10,
        )
        if (bin_result.stdout or "").strip() != "ok":
            issues.append(
                f"Orchestrator binary missing on new prod at {remote_root}/bazel-bin/scripts/cron/refresh_and_switch_py. "
                f"Manual fix: ssh new_prod 'cd {remote_root} && "
                "bazel build //scripts/cron:refresh_and_switch_py && bazel shutdown'"
            )
        else:
            logger.info("Orchestrator binary present on new prod")
    except Exception as e:
        issues.append(f"Could not check orchestrator binary on new prod: {e}")

    if issues:
        logger.error(
            "POST-GRADUATION VERIFICATION: %d issue(s) found — manual intervention required:\n  - %s",
            len(issues),
            "\n  - ".join(issues),
        )
    else:
        logger.info("Post-graduation verification: all checks passed")


def _wait_app_healthy_via_ssh(
    runner: Runner,
    timeout_sec: int = 300,
    poll_interval_sec: int = 10,
) -> bool:
    """Check app health by SSHing into the host and curling localhost:8000.

    More reliable than external HTTP: avoids nginx server_name mismatches,
    HTTP→HTTPS redirects, and security group restrictions on port 8000.
    """
    import time

    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        result = runner.run_shell(
            "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8000/",
            timeout_sec=15,
        )
        code = (result.stdout or "").strip()
        if code == "200":
            logger.info("App healthy (HTTP 200 on localhost:8000)")
            return True
        logger.debug("Health check: HTTP %s", code or "(no response)")
        time.sleep(poll_interval_sec)
    return False


def _rebuild_orchestrator_binary(runner: Runner, project_root: Path) -> None:
    """Rebuild the orchestrator binary (launcher + runfiles tree) on new prod.

    Bazel py_binary uses runfiles symlinks to workspace sources, so the executed
    code depends on the git checkout at runtime — this just ensures the launcher
    exists for the next cycle.  On 2GB Lightsail instances Bazel holds ~400-500 MB;
    the immediate shutdown frees that before the safety interval.
    Non-fatal: logs a warning with the manual fix command on failure.
    """
    build_cmd = (
        f"cd {shlex.quote(str(project_root))} && "
        "bazel build //scripts/cron:refresh_and_switch_py && "
        "bazel shutdown"
    )
    result = runner.run_shell(build_cmd, timeout_sec=300)
    if result.returncode != 0:
        logger.warning(
            "Orchestrator binary rebuild failed (non-fatal): %s. "
            "Run manually: cd /opt/visa_bulletin && "
            "bazel build //scripts/cron:refresh_and_switch_py && bazel shutdown",
            ((result.stderr or "") + (result.stdout or ""))[:300],
        )
    else:
        logger.info("Orchestrator binary rebuilt on new prod (ready for next cycle)")


def _write_prod_safe_override(runner: Runner, project_root: Path, host_ip: str) -> None:
    """Replace the staging docker-compose.override.yml (which has ../:/app volume mount)
    with a prod-safe version that keeps operational settings but drops the volume mount.

    Without this, git pull on prod would bleed into gunicorn workers when they
    recycle via --max-requests, because the volume mount exposes host files to the container.
    """
    override_path = project_root / "deployment" / "docker-compose.override.yml"
    allowed_hosts = (
        f"{host_ip},localhost,127.0.0.1,visa-bulletin.us,www.visa-bulletin.us"
    )
    override_content = (
        "version: '3.8'\n"
        "services:\n"
        "  web:\n"
        "    mem_limit: 512m\n"
        "    memswap_limit: 768m\n"
        "    environment:\n"
        "      - WEB_CONCURRENCY=1\n"
        f"      - ALLOWED_HOSTS={allowed_hosts}\n"
    )
    runner.run_shell(
        f"cat > {shlex.quote(str(override_path))} << 'OVERRIDE_EOF'\n{override_content}OVERRIDE_EOF",
        timeout_sec=10,
    )
    logger.info("Wrote prod-safe override (no volume mount) at %s", override_path)

    compose_file = project_root / "deployment" / "docker-compose.yml"
    compose_args = (
        f"-f {shlex.quote(str(compose_file))} -f {shlex.quote(str(override_path))}"
    )
    # docker-compose 1.29.2 bug: recreate hits KeyError 'ContainerConfig' if the existing
    # container's image lacks that field (e.g. multi-stage builds or some base images).
    # Workaround: force-remove exited/zombie containers before `up -d` so docker-compose
    # creates fresh containers rather than trying to recreate from old metadata.
    cleanup_cmd = (
        "export DOCKER_HOST=unix:///var/run/docker.sock && "
        "docker ps -a --filter status=exited --format '{{.Names}}' | "
        "grep visa_bulletin_web | xargs -r docker rm -f"
    )
    runner.run_shell(cleanup_cmd, timeout_sec=15)
    restart_cmd = (
        f"export DOCKER_HOST=unix:///var/run/docker.sock && "
        f"cd {shlex.quote(str(project_root))} && "
        f"docker-compose {compose_args} up -d"
    )
    result = runner.run_shell(restart_cmd, timeout_sec=120)
    if result.returncode != 0:
        logger.warning(
            "Container restart after override cleanup failed (rc=%s): %s",
            result.returncode,
            result.stderr,
        )
    else:
        logger.info(
            "Restarted web container with prod-safe override (using Docker image code)"
        )


def _smoke_test_public_url(
    domain: str = "visa-bulletin.us",
    timeout_sec: int = 120,
    poll_interval_sec: int = 10,
) -> bool:
    """Smoke test public URL after IP swap to verify the new prod serves traffic.

    Runs locally on the orchestrator machine (not via SSH) — the domain should
    resolve to the new prod after the static IP swap.
    """
    import time

    logger.info("Smoke-testing public URL: https://%s/", domain)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                    "--max-time", "10", f"https://{domain}/",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            code = (result.stdout or "").strip()
            if code == "200":
                logger.info("Public URL smoke: https://%s/ returned 200", domain)
                return True
            logger.info("Public URL smoke: HTTP %s (retrying...)", code)
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.info("Public URL smoke: %s (retrying...)", e)
        time.sleep(poll_interval_sec)
    logger.warning(
        "Public URL smoke FAILED: https://%s/ did not return 200 within %ds",
        domain,
        timeout_sec,
    )
    return False


def _update_local_env_swap_roles(
    env_file: Path,
    active_info: instance.InstanceInfo,
    inactive_info: instance.InstanceInfo,
) -> None:
    """Update .env on the orchestrator machine (now staging after IP swap) to swap roles."""
    # After the IP swap: inactive_info.name now holds the prod static IP (active_info.ip),
    # and active_info.name will receive the staging static IP (inactive_info.ip).
    update_env_value(env_file, "REFRESH_ACTIVE_INSTANCE_NAME", inactive_info.name)
    update_env_value(env_file, "REFRESH_ACTIVE_INSTANCE_IP", active_info.ip)
    update_env_value(env_file, "REFRESH_INACTIVE_INSTANCE_NAME", active_info.name)
    update_env_value(env_file, "REFRESH_INACTIVE_INSTANCE_IP", inactive_info.ip)
    update_env_value(env_file, "REFRESH_MY_INSTANCE_NAME", active_info.name)
    # Swap private IPs so next cycle SSHes to the right instance.
    # active_info was the orchestrator (now staging) → its private IP becomes INACTIVE.
    # inactive_info was the pipeline host (now prod) → its private IP becomes ACTIVE.
    active_private = os.environ.get("REFRESH_ACTIVE_PRIVATE_IP", "").strip()
    inactive_private = os.environ.get("REFRESH_INACTIVE_PRIVATE_IP", "").strip()
    if active_private:
        update_env_value(env_file, "REFRESH_INACTIVE_PRIVATE_IP", active_private)
    if inactive_private:
        update_env_value(env_file, "REFRESH_ACTIVE_PRIVATE_IP", inactive_private)
    logger.info(
        "Updated local .env (orchestrator/staging): active=%s, inactive=%s, my=%s",
        inactive_info.name,
        active_info.name,
        active_info.name,
    )


def _update_git_branch_on_new_prod(
    runner: Runner,
    project_root: Path,
    source_branch: str = "staging",
    target_branch: str = "prod",
) -> bool:
    """Push prod=staging to origin and switch new prod's checkout to prod branch.

    Requires a deploy key at ~/.ssh/github_deploy_key on the instance.
    If push fails, logs an error and keeps the instance on source_branch
    (which has the correct code) rather than checking out stale origin/prod.
    """
    push_result = runner.run_shell(
        f"cd {project_root} && "
        f"git push origin {shlex.quote(source_branch)}:{shlex.quote(target_branch)} --force",
        timeout_sec=60,
    )
    push_ok = push_result.returncode == 0
    if not push_ok:
        logger.error(
            "git push %s:%s failed — deploy key may not be configured. "
            "Keeping instance on %s branch (correct code). "
            "Manual fix: cd /opt/visa_bulletin && git push origin %s:%s --force",
            source_branch,
            target_branch,
            source_branch,
            source_branch,
            target_branch,
        )
        # Stay on source_branch — it has the right code and avoids fetching stale origin/prod.
        return False

    logger.info("Pushed %s branch to match %s on origin", target_branch, source_branch)

    checkout_result = runner.run_shell(
        f"cd {project_root} && "
        f"git fetch origin {shlex.quote(target_branch)} && "
        f"git checkout -B {shlex.quote(target_branch)} origin/{shlex.quote(target_branch)}",
        timeout_sec=60,
    )
    if checkout_result.returncode != 0:
        logger.warning(
            "git checkout %s on new prod failed: %s",
            target_branch,
            ((checkout_result.stderr or "") + (checkout_result.stdout or ""))[:500],
        )
        return False
    logger.info("New prod switched to %s branch (no reload)", target_branch)
    return True


def _update_local_git_to_prod_branch(project_root: Path, target_branch: str = "prod") -> bool:
    """Switch the orchestrator (staging instance) checkout to prod branch.

    Run after _update_git_branch_on_new_prod so origin/prod is updated; then this host
    (old prod, now staging) fetches and checks out prod. Ensures git branch consistency:
    prod branch = what prod runs; staging instance has prod checked out before stop.
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "fetch",
                "origin",
                target_branch,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(
                "git fetch origin %s on staging instance failed: %s",
                target_branch,
                (result.stderr or "")[:300],
            )
            return False
        result = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "checkout",
                "-B",
                target_branch,
                f"origin/{target_branch}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                "git checkout %s on staging instance failed: %s",
                target_branch,
                (result.stderr or "")[:300],
            )
            return False
        logger.info(
            "Staging instance switched to %s branch (consistent with prod before stop)",
            target_branch,
        )
        return True
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Update local git to prod branch failed: %s", e)
        return False


def _make_remote_config(remote_root: Path, db_name: str) -> RefreshConfig:
    """Create a RefreshConfig for the remote host (used when calling pipeline step functions outside the pipeline)."""
    remote_config = load_config(None)
    remote_config.project_root = remote_root
    remote_config.env_file = remote_root / ".env"
    remote_config.backup_dir = remote_root / "backups"
    remote_config.db_name = db_name
    return remote_config


def run_orchestrate(
    config: RefreshConfig,
    safety_interval_sec: int = 1800,
    no_traffic_switch: bool = False,
    resume: bool = False,
    from_step: str | None = None,
    domain: str | None = None,
) -> int:
    """
    Full cycle: resolve active/inactive -> start inactive -> wait healthy
    -> run pipeline with RemoteRunner(inactive) -> smoke -> (optional) traffic switch
    -> graduation steps -> safety interval -> stop old.

    --from-step warm_cache|smoke_tests|traffic_switch: skip pipeline, start from
    the specified graduation step (assumes pipeline already completed on inactive).
    --no-traffic-switch: skip traffic switch and all post-switch steps.
    Returns 0 on success.
    """
    active_info, inactive_info = instance.resolve_active_inactive_from_env()
    if not active_info or not inactive_info:
        logger.error(
            "Orchestrator requires REFRESH_ACTIVE_* and REFRESH_INACTIVE_* env vars"
        )
        return 1

    my_id = (
        os.environ.get("REFRESH_MY_INSTANCE_NAME", "").strip()
        or os.environ.get("REFRESH_MY_INSTANCE_IP", "").strip()
    )
    if my_id and not instance.is_this_host_active(my_id, active_info):
        logger.info("This host is inactive; no-op (orchestrator should run on active)")
        return 0

    # Lock file guard: prevent concurrent orchestrator runs on the same host.
    # A double-triggered graduation can swap IPs twice and stop both instances.
    lock_path = Path(config.project_root) / ".orchestrator.lock"
    if lock_path.exists():
        try:
            lock_pid = int(lock_path.read_text().strip())
            # Check if the process is still running
            os.kill(lock_pid, 0)
            logger.error(
                "Another orchestrator is running (PID %d, lock file %s). "
                "Aborting to prevent double-graduation. "
                "If the other process is dead, delete %s manually.",
                lock_pid,
                lock_path,
                lock_path,
            )
            return 1
        except (ValueError, ProcessLookupError, OSError):
            logger.warning("Stale lock file %s (PID gone); removing", lock_path)
            lock_path.unlink(missing_ok=True)

    lock_path.write_text(str(os.getpid()))
    try:
        return _run_orchestrate_locked(
            config, active_info, inactive_info,
            safety_interval_sec=safety_interval_sec,
            no_traffic_switch=no_traffic_switch,
            resume=resume,
            from_step=from_step,
            domain=domain,
        )
    finally:
        lock_path.unlink(missing_ok=True)


def _run_orchestrate_locked(
    config: RefreshConfig,
    active_info: instance.InstanceInfo,
    inactive_info: instance.InstanceInfo,
    safety_interval_sec: int = 1800,
    no_traffic_switch: bool = False,
    resume: bool = False,
    from_step: str | None = None,
    domain: str | None = None,
) -> int:
    """Core orchestration logic, called while holding the lock file."""

    # Validate .env against actual AWS state to catch corrupted .env from partial runs.
    # Logs errors with recovery instructions on mismatch but does not abort (non-fatal)
    # so a misconfigured AWS CLI doesn't block the orchestrator.
    instance.validate_env_against_aws(active_info, inactive_info)

    logger.info(
        "Active: %s (%s), Inactive: %s (%s)",
        active_info.name,
        active_info.ip,
        inactive_info.name,
        inactive_info.ip,
    )

    project_root = os.environ.get("REFRESH_REMOTE_PROJECT_ROOT", "/opt/visa_bulletin")
    ssh_user = os.environ.get("REFRESH_SSH_USER", "ubuntu")
    ssh_key = os.environ.get("REFRESH_SSH_KEY_PATH", "")
    ssh_timeout_raw = os.environ.get("REFRESH_SSH_TIMEOUT", "14400").strip()
    ssh_timeout_sec = int(ssh_timeout_raw) if ssh_timeout_raw.isdigit() else 14400
    # Prefer private IP for inter-instance SSH: Lightsail instances cannot reach each
    # other via public static IPs. Set REFRESH_INACTIVE_PRIVATE_IP in .env to the
    # inactive instance's private IP (visible in Lightsail console → Networking → Private IP).
    # Private IPs survive stop/start and rotate with the instance, not the static IP.
    inactive_ssh_host = (
        os.environ.get("REFRESH_INACTIVE_PRIVATE_IP", "").strip() or inactive_info.ip
    )
    if inactive_ssh_host != inactive_info.ip:
        logger.info(
            "Using private IP %s for SSH to inactive instance (public IP: %s)",
            inactive_ssh_host,
            inactive_info.ip,
        )
    remote = RemoteRunner(
        host=inactive_ssh_host,
        project_root=project_root,
        ssh_user=ssh_user,
        ssh_key_path=ssh_key if ssh_key else None,
        ssh_timeout_sec=ssh_timeout_sec,
    )
    remote_root = Path(project_root)
    db_name = os.environ.get("REFRESH_REMOTE_DB_NAME", "visa_bulletin")

    # --from-step: skip pipeline, jump to a graduation step
    skip_to_graduation = from_step in GRADUATION_STEPS
    if skip_to_graduation:
        logger.info(
            "--from-step %s: skipping pipeline; ensuring SSH, services, then graduation",
            from_step,
        )
        if not services.wait_ssh_and_db_ready(remote, db_name, timeout_sec=120):
            logger.error(
                "Instance %s (%s): SSH or DB not ready",
                inactive_info.name,
                inactive_info.ip,
            )
            return 1

        logger.info("Starting services on inactive host for graduation")
        services.start_remote_services(remote, remote_root)
        if not _wait_app_healthy_via_ssh(remote, timeout_sec=300):
            logger.warning(
                "Instance %s (%s) HTTP not healthy (non-fatal)",
                inactive_info.name,
                inactive_info.ip,
            )

        remote_config = _make_remote_config(remote_root, db_name)
        ctx = PipelineContext(db_name=db_name)

        if from_step == "warm_cache":
            logger.info("Running cache warming on inactive host")
            step_warm_cache(remote_config, remote, ctx)

        if from_step in ("warm_cache", "smoke_tests"):
            logger.info("Running smoke tests on inactive host")
            step_run_smoke_tests(remote_config, remote, ctx)
    else:
        # Normal flow: start inactive instance, run full pipeline
        state = instance.get_instance_state(inactive_info.name)
        if state != "running":
            logger.info("Starting inactive instance %s", inactive_info.name)
            if not instance.start_instance(inactive_info.name):
                logger.error("Failed to start %s", inactive_info.name)
                return 1
            if not instance.wait_instance_running(
                inactive_info.name, timeout_sec=600
            ):
                logger.error(
                    "Instance %s did not reach running state", inactive_info.name
                )
                return 1
        else:
            logger.info("Inactive instance %s already running", inactive_info.name)

        if not services.wait_ssh_and_db_ready(remote, db_name, timeout_sec=600):
            logger.error(
                "Instance %s (%s): SSH or DB not ready",
                inactive_info.name,
                inactive_info.ip,
            )
            return 1
        logger.info("Inactive instance SSH and DB ready at %s", inactive_info.ip)

        logger.info("Stopping Redis, Gunicorn, Bazel on inactive host to free memory")
        services.stop_remote_services(remote, remote_root)
        services.ensure_postgres_connections_clean(remote, db_name)

        logger.info("Running pipeline on inactive host %s", inactive_info.ip)
        remote_config = _make_remote_config(remote_root, db_name)
        run_pipeline(remote_config, remote, resume=resume, domain=domain)
        logger.info("Pipeline complete on inactive; warm_cache + smoke ran in pipeline")

        logger.info("Starting Redis and Gunicorn on inactive host for traffic switch")
        services.start_remote_services(remote, remote_root)
        if not _wait_app_healthy_via_ssh(remote, timeout_sec=300):
            logger.warning(
                "Instance %s (%s) HTTP not healthy after start_services (non-fatal)",
                inactive_info.name,
                inactive_info.ip,
            )

    # === GATE: no-traffic-switch exits here (nothing irreversible happened) ===
    if no_traffic_switch:
        logger.info(
            "--no-traffic-switch: skipping traffic switch, cron setup, safety interval, stop old"
        )
        return 0

    # === TRAFFIC SWITCH (irreversible — all steps after this are non-fatal) ===
    static_ip_name = os.environ.get("REFRESH_STATIC_IP_NAME", "")
    if not static_ip_name:
        logger.error("REFRESH_STATIC_IP_NAME not set; cannot switch traffic")
        return 1
    if not traffic_switch.switch_traffic_static_ip(static_ip_name, inactive_info.name):
        logger.error("Static IP switch failed")
        return 1

    # === POST-SWITCH: all non-fatal (IP swap already happened) ===

    # HTTPS on new prod (certbot) so public URL works with valid cert
    setup_https = os.environ.get(
        "REFRESH_SKIP_HTTPS_SETUP", ""
    ).strip().lower() not in ("1", "true", "yes")
    if setup_https:
        logger.info("Setting up HTTPS on new prod (certbot --nginx)")
        if not services.setup_https_on_remote(remote, timeout_sec=120):
            logger.warning(
                "HTTPS setup failed (non-fatal); run certbot manually on new prod"
            )
    else:
        logger.info("REFRESH_SKIP_HTTPS_SETUP: skipping HTTPS setup on new prod")

    # Public URL smoke test (verify site works end-to-end via domain)
    site_domain = os.environ.get("REFRESH_DOMAIN", "visa-bulletin.us").strip()
    if site_domain:
        if not _smoke_test_public_url(site_domain):
            logger.warning(
                "Public URL smoke test failed (non-fatal); verify manually at https://%s/",
                site_domain,
            )
    else:
        logger.info("REFRESH_DOMAIN empty: skipping public URL smoke test")

    # Update .env on new prod (swap active/inactive roles)
    logger.info(
        "Updating new prod .env (swap REFRESH_ACTIVE_* / REFRESH_INACTIVE_* / REFRESH_MY_INSTANCE_NAME)"
    )
    # After the IP swap: inactive_info.name now holds the prod static IP (active_info.ip),
    # and active_info.name will receive the staging static IP (inactive_info.ip).
    remote.update_env("REFRESH_ACTIVE_INSTANCE_NAME", inactive_info.name)
    remote.update_env("REFRESH_ACTIVE_INSTANCE_IP", active_info.ip)
    remote.update_env("REFRESH_INACTIVE_INSTANCE_NAME", active_info.name)
    remote.update_env("REFRESH_INACTIVE_INSTANCE_IP", inactive_info.ip)
    remote.update_env("REFRESH_MY_INSTANCE_NAME", inactive_info.name)
    # Swap private IPs on new prod: inactive (pipeline host, now prod) has ACTIVE private IP;
    # active (orchestrator host, now staging) has INACTIVE private IP.
    active_private = os.environ.get("REFRESH_ACTIVE_PRIVATE_IP", "").strip()
    inactive_private = os.environ.get("REFRESH_INACTIVE_PRIVATE_IP", "").strip()
    if inactive_private:
        remote.update_env("REFRESH_ACTIVE_PRIVATE_IP", inactive_private)
    if active_private:
        remote.update_env("REFRESH_INACTIVE_PRIVATE_IP", active_private)

    # Update .env on orchestrator machine (old active, now staging after IP swap)
    logger.info("Updating local .env (orchestrator, now staging) to swap roles")
    try:
        _update_local_env_swap_roles(config.env_file, active_info, inactive_info)
    except OSError as e:
        logger.warning("Local .env update failed (non-fatal): %s", e)

    # Staging IP reassignment (so old prod has a stable IP for the next cycle)
    reassign_staging_ip = os.environ.get(
        "REFRESH_SKIP_STAGING_IP_REASSIGN", ""
    ).strip().lower() not in ("1", "true", "yes")
    if reassign_staging_ip:
        staging_static_ip = os.environ.get("REFRESH_STAGING_STATIC_IP_NAME", "").strip()
        if not staging_static_ip:
            logger.error(
                "REFRESH_STAGING_STATIC_IP_NAME not set; cannot reattach staging IP to old prod. "
                "Set it in .env on the instance that runs the orchestrator (current prod). "
                "Get the staging static IP name from: aws lightsail get-static-ips --region us-east-1"
            )
        else:
            logger.info(
                "Re-assigning staging static IP %s to old prod %s",
                staging_static_ip,
                active_info.name,
            )
            if not traffic_switch.attach_staging_static_ip_to_old_prod(
                staging_static_ip, active_info.name
            ):
                logger.error(
                    "Staging IP reassign failed. Old prod (staging) is unreachable until you run: "
                    "aws lightsail attach-static-ip --static-ip-name %s --instance-name %s --region us-east-1",
                    staging_static_ip,
                    active_info.name,
                )
    else:
        logger.info("REFRESH_SKIP_STAGING_IP_REASSIGN: skipping staging IP reassign")

    # Prod-safe override: drop volume mount so prod uses baked-in Docker image code
    logger.info(
        "Replacing docker-compose.override.yml on new prod with prod-safe version (no volume mount)"
    )
    _write_prod_safe_override(remote, remote_root, inactive_info.ip)
    if not _wait_app_healthy_via_ssh(remote, timeout_sec=120):
        logger.warning("New prod not healthy after override cleanup (non-fatal)")

    # Set up hourly bulletin refresh cron on new prod
    logger.info("Setting up bulletin refresh cron job on new prod")
    if not services.setup_bulletin_cron_on_remote(remote, remote_root):
        logger.warning("Bulletin cron setup failed (non-fatal); run manually on new prod")

    # Git branch update: push prod=staging, switch new prod checkout to prod, then switch staging instance to prod
    skip_git = os.environ.get(
        "REFRESH_SKIP_GIT_UPDATE", ""
    ).strip().lower() in ("1", "true", "yes")
    if not skip_git:
        logger.info(
            "Updating git branches: push prod=staging, switch new prod to prod branch"
        )
        _update_git_branch_on_new_prod(remote, remote_root)
        logger.info("Switching staging instance (this host) to prod branch before stop")
        _update_local_git_to_prod_branch(config.project_root)
    else:
        logger.info("REFRESH_SKIP_GIT_UPDATE: skipping git branch update")

    # Rebuild orchestrator binary on new prod so next cycle has a working launcher.
    # Bazel py_binary uses runfiles symlinks, so the actual executed code depends on
    # the git checkout at runtime — the rebuild just ensures the launcher/tree exist.
    logger.info("Rebuilding orchestrator binary on new prod")
    _rebuild_orchestrator_binary(remote, remote_root)

    # Post-graduation verification: check all housekeeping steps landed correctly
    _verify_post_graduation(
        remote,
        remote_root,
        active_info,
        staging_static_ip_name=os.environ.get("REFRESH_STAGING_STATIC_IP_NAME", "").strip() or None,
        skip_staging_ip=not reassign_staging_ip,
    )

    import time

    logger.info("Safety interval: %s sec", safety_interval_sec)
    time.sleep(safety_interval_sec)

    # Stop old instance (the orchestrator's machine, now staging)
    logger.info("Stopping old instance %s (this host, now staging)", active_info.name)
    if not instance.stop_instance(active_info.name):
        logger.warning("Failed to stop %s (non-fatal)", active_info.name)

    logger.info("Graduation complete")
    return 0
