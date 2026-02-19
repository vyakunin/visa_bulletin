# scripts/cron/refresh/runner.py
"""Runner protocol and implementations: LocalRunner, RemoteRunner, MockRunner."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .checkpoint import CheckpointData, read_checkpoint, write_checkpoint as write_checkpoint_file

logger = logging.getLogger(__name__)


@runtime_checkable
class Runner(Protocol):
    """Execution backend: run commands and read/write checkpoint on the target host."""

    def run_bin(self, rel_path: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run pre-built binary or bazel run. rel_path e.g. 'scripts/salary/cluster_job_titles'."""
        ...

    def read_stage_log_tail(self, n: int = 200) -> str:
        """Read last n lines of stage log (e.g. REFRESH_STAGE_LOG_PATH). Empty if not available."""
        ...

    def run_psql(self, db_name: str, sql: str) -> str:
        """Run psql -t -c and return stdout."""
        ...

    def run_sudo_psql(self, sql: str, db: str | None = None) -> subprocess.CompletedProcess[str]:
        """Run sudo -u postgres psql [-d db] -c sql."""
        ...

    def run_migrate(self, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run Django migrate --noinput."""
        ...

    def update_env(self, key: str, value: str) -> None:
        """Update .env key=value on target host."""
        ...

    def read_checkpoint(self, path: Path) -> CheckpointData | None:
        """Read checkpoint JSON from target host."""
        ...

    def write_checkpoint(self, path: Path, data: CheckpointData) -> None:
        """Write checkpoint JSON on target host (atomic)."""
        ...

    def run_shell(self, command: str, timeout_sec: int | None = None) -> subprocess.CompletedProcess[str]:
        """Run a shell command on the target host (SSH for remote, bash -c for local)."""
        ...


class LocalRunner:
    """Run commands on this host via subprocess."""

    def __init__(self, project_root: Path, env_file: Path, env: dict[str, str] | None = None):
        self.project_root = Path(project_root)
        self.env_file = Path(env_file)
        self._env = dict(os.environ)
        if env:
            self._env.update(env)

    def run_bin(
        self,
        rel_path: str,
        *args: str,
        cwd: Path | None = None,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        cwd = cwd or self.project_root
        bazel_bin = self.project_root / "bazel-bin"
        bin_path = bazel_bin / rel_path
        if bin_path.exists() and os.access(bin_path, os.X_OK):
            return subprocess.run(
                [str(bin_path), *args],
                cwd=str(cwd),
                env=self._env,
                capture_output=True,
                text=True,
                check=False,
            )
        # Fallback: bazel run
        target = f"//{rel_path}"
        return subprocess.run(
            ["bazel", "run", target, "--", *args],
            cwd=str(self.project_root),
            env=self._env,
            capture_output=True,
            text=True,
            check=False,
        )

    def read_stage_log_tail(self, n: int = 200) -> str:
        """Read last n lines of stage log from local file if REFRESH_STAGE_LOG_PATH set."""
        path = os.environ.get("REFRESH_STAGE_LOG_PATH")
        if not path or not Path(path).exists():
            return ""
        try:
            lines = Path(path).read_text().splitlines()
            return "\n".join(lines[-n:]) if len(lines) > n else "\n".join(lines)
        except OSError:
            return ""

    def run_psql(self, db_name: str, sql: str) -> str:
        env = dict(self._env)
        if env.get("DB_PASSWORD"):
            env["PGPASSWORD"] = env["DB_PASSWORD"]
        db_host = env.get("DB_HOST", "localhost")
        db_user = env.get("DB_USER", "visa_bulletin_user")
        db_port = env.get("DB_PORT", "5432")
        result = subprocess.run(
            ["psql", "-h", db_host, "-U", db_user, "-d", db_name, "-t", "-c", sql, "-p", db_port],
            env=env,
            capture_output=True,
            text=True,
            cwd=str(self.project_root),
        )
        return (result.stdout or "").strip() if result.returncode == 0 else ""

    def run_sudo_psql(self, sql: str, db: str | None = None) -> subprocess.CompletedProcess[str]:
        cmd = ["sudo", "-u", "postgres", "psql"]
        if db:
            cmd.extend(["-d", db])
        cmd.extend(["-c", sql])
        return subprocess.run(
            cmd,
            cwd=str(self.project_root),
            env=self._env,
            capture_output=True,
            text=True,
            check=False,
        )

    def run_migrate(self, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        cwd = cwd or self.project_root
        return subprocess.run(
            ["python3", "manage.py", "migrate", "--noinput"],
            cwd=str(cwd),
            env=self._env,
            capture_output=True,
            text=True,
            check=False,
        )

    def update_env(self, key: str, value: str) -> None:
        from .config import update_env_value
        update_env_value(self.env_file, key, value)
        self._env[key] = value

    def read_checkpoint(self, path: Path) -> CheckpointData | None:
        return read_checkpoint(Path(path))

    def write_checkpoint(self, path: Path, data: CheckpointData) -> None:
        write_checkpoint_file(Path(path), data)

    def run_shell(self, command: str, timeout_sec: int | None = None) -> subprocess.CompletedProcess[str]:
        kwargs: dict[str, Any] = {
            "cwd": str(self.project_root),
            "env": self._env,
            "capture_output": True,
            "text": True,
            "check": False,
        }
        if timeout_sec is not None:
            kwargs["timeout"] = timeout_sec
        return subprocess.run(["bash", "-c", command], **kwargs)


class MockRunner:
    """Record runner calls for tests. Returns success by default.

    Supports per-binary failure simulation via ``run_bin_side_effects``:
    a dict mapping ``rel_path`` to a ``CompletedProcess`` (or callable
    ``(rel_path, *args) -> CompletedProcess``).  When a matching entry
    exists the per-path value takes precedence over the blanket
    ``run_bin_return``.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._checkpoint: CheckpointData | None = None
        self.run_bin_return: subprocess.CompletedProcess[str] | None = None
        self.run_bin_side_effects: dict[str, subprocess.CompletedProcess[str] | Any] = {}
        self.run_psql_return: str = "0"
        self.run_psql_side_effects: dict[str, str | Any] = {}
        self.run_sudo_psql_return: subprocess.CompletedProcess[str] | None = None
        self.run_migrate_return: subprocess.CompletedProcess[str] | None = None

    def run_bin(
        self,
        rel_path: str,
        *args: str,
        cwd: Path | None = None,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(("run_bin", (rel_path, *args), {"cwd": cwd, **kwargs}))
        if rel_path in self.run_bin_side_effects:
            effect = self.run_bin_side_effects[rel_path]
            if callable(effect):
                return effect(rel_path, *args)
            return effect
        if self.run_bin_return is not None:
            return self.run_bin_return
        return subprocess.CompletedProcess(args=[rel_path, *args], returncode=0, stdout="", stderr="")

    def read_stage_log_tail(self, n: int = 200) -> str:
        self.calls.append(("read_stage_log_tail", (n,), {}))
        return ""

    def run_psql(self, db_name: str, sql: str) -> str:
        self.calls.append(("run_psql", (db_name, sql), {}))
        for pattern, value in self.run_psql_side_effects.items():
            if pattern in sql:
                if callable(value):
                    return value(db_name, sql)
                return value
        return self.run_psql_return

    def run_sudo_psql(self, sql: str, db: str | None = None) -> subprocess.CompletedProcess[str]:
        self.calls.append(("run_sudo_psql", (sql,), {"db": db}))
        if self.run_sudo_psql_return is not None:
            return self.run_sudo_psql_return
        return subprocess.CompletedProcess(args=["psql"], returncode=0, stdout="", stderr="")

    def run_migrate(self, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        self.calls.append(("run_migrate", (), {"cwd": cwd}))
        if self.run_migrate_return is not None:
            return self.run_migrate_return
        return subprocess.CompletedProcess(args=["migrate"], returncode=0, stdout="", stderr="")

    def update_env(self, key: str, value: str) -> None:
        self.calls.append(("update_env", (key, value), {}))

    def read_checkpoint(self, path: Path) -> CheckpointData | None:
        self.calls.append(("read_checkpoint", (str(path),), {}))
        return self._checkpoint

    def write_checkpoint(self, path: Path, data: CheckpointData) -> None:
        self.calls.append(("write_checkpoint", (str(path), data), {}))
        self._checkpoint = data

    def run_shell(self, command: str, timeout_sec: int | None = None) -> subprocess.CompletedProcess[str]:
        self.calls.append(("run_shell", (command,), {"timeout_sec": timeout_sec}))
        stdout = ""
        if "curl" in command and "http_code" in command:
            if "job-title-autocomplete" in command:
                stdout = '[{"title":"Software Engineer","slug":"software-engineer","total_filings":1000}]\n200'
            elif "company-autocomplete" in command:
                stdout = '[{"name":"Google LLC","slug":"google-llc","total_filings":500}]\n200'
            elif "job-titles" in command:
                stdout = '<a href="/job-title/software-engineer/">Software Engineer</a>' * 15 + "\n200"
            elif "employers" in command:
                stdout = '<a href="/employer/google-llc/">Google LLC</a>' * 15 + "\n200"
            else:
                stdout = "OK\n200"
        return subprocess.CompletedProcess(args=["run_shell"], returncode=0, stdout=stdout, stderr="")


class RemoteRunner:
    """Run commands on a remote host via SSH. Checkpoint read/write on remote."""

    def __init__(
        self,
        host: str,
        project_root: str | Path = "/opt/visa_bulletin",
        ssh_user: str = "ubuntu",
        ssh_key_path: str | None = None,
        env_file: str | Path = ".env",
        ssh_timeout_sec: int | None = None,
    ) -> None:
        self.host = host
        self.project_root = Path(project_root)
        self.ssh_user = ssh_user
        self.ssh_key_path = ssh_key_path
        self.env_file = Path(env_file) if isinstance(env_file, Path) else self.project_root / ".env"
        if ssh_timeout_sec is not None:
            self.ssh_timeout = ssh_timeout_sec
        else:
            self.ssh_timeout = int(os.environ.get("REFRESH_SSH_TIMEOUT", "14400"))

    def _ssh(
        self,
        command: str,
        stdin: str | None = None,
        timeout_sec: int | None = None,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        timeout = timeout_sec if timeout_sec is not None else self.ssh_timeout
        cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=10"]
        if self.ssh_key_path:
            cmd.extend(["-i", self.ssh_key_path])
        cmd.append(f"{self.ssh_user}@{self.host}")
        cmd.append(command)
        kwargs: dict[str, Any] = {
            "text": True,
            "input": stdin,
            "timeout": timeout,
        }
        if capture_output:
            kwargs["capture_output"] = True
        else:
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
        result = subprocess.run(cmd, **kwargs)
        return result

    def run_bin(
        self,
        rel_path: str,
        *args: str,
        cwd: Path | None = None,
        timeout_sec: int | None = None,
        env_override: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        root = str(cwd or self.project_root)
        bin_path = f"{root}/bazel-bin/{rel_path}"
        args_s = " ".join(shlex.quote(a) for a in args)
        stage_log = os.environ.get("REFRESH_STAGE_LOG_PATH", "/tmp/refresh_stage.log")
        inner = f"cd {root} && set -a && [ -f .env ] && source .env && set +a && "
        # Optional env overrides (e.g. REDIS_URL= so warm_cache uses LocMem on host)
        if env_override:
            for k, v in env_override.items():
                inner += f"export {shlex.quote(k)}={shlex.quote(v)} && "
        # Bazel target: scripts/salary/manage_salary_indexes -> //scripts/salary:manage_salary_indexes
        if "/" in rel_path:
            pkg, _, target = rel_path.rpartition("/")
            bazel_target = f"//{pkg}:{target}"
        else:
            bazel_target = f"//{rel_path}"
        run_cmd = f"if [ -x {bin_path} ]; then {bin_path} {args_s}; else bazel run {bazel_target} -- {args_s}; fi"
        # Wrap with remote-side timeout so the process self-terminates before the SSH
        # session times out.  Without this, SSH timeout kills the local client but the
        # remote process keeps running as a zombie (no TTY = no SIGHUP on disconnect).
        if timeout_sec is not None:
            remote_timeout = max(timeout_sec - 120, int(timeout_sec * 0.95))
            run_cmd = f"timeout --signal=TERM --kill-after=60 {remote_timeout} bash -c {shlex.quote(run_cmd)}"
        inner += f"{run_cmd} 2>&1 | tee {stage_log}; exit ${{PIPESTATUS[0]:-0}}"
        cmd = f"bash -c {shlex.quote(inner)}"
        result = self._ssh(cmd, timeout_sec=timeout_sec, capture_output=False)
        return subprocess.CompletedProcess(
            args=[rel_path, *args],
            returncode=result.returncode,
            stdout="",
            stderr="",
        )

    def read_stage_log_tail(self, n: int = 200) -> str:
        """Read last n lines of stage log on remote host (no capture, so tail from file)."""
        stage_log = os.environ.get("REFRESH_STAGE_LOG_PATH", "/tmp/refresh_stage.log")
        result = self._ssh(f"tail -n {n} {shlex.quote(stage_log)} 2>/dev/null || true")
        return (result.stdout or "").strip() if result.returncode == 0 else ""

    def run_psql(self, db_name: str, sql: str) -> str:
        sql_esc = sql.replace("'", "'\"'\"'")
        # PGPASSWORD is what psql uses; .env typically has DB_PASSWORD
        cmd = f"cd {self.project_root} && set -a && [ -f .env ] && source .env && set +a && PGPASSWORD=$DB_PASSWORD psql -h localhost -U ${{DB_USER:-visa_bulletin_user}} -d {db_name} -t -c '{sql_esc}'"
        result = self._ssh(cmd)
        if result.returncode != 0:
            logger.warning(
                "run_psql failed (rc=%s) db=%s: stderr=%r stdout=%r",
                result.returncode,
                db_name,
                (result.stderr or "").strip()[:500],
                (result.stdout or "").strip()[:200],
            )
        return (result.stdout or "").strip() if result.returncode == 0 else ""

    def run_sudo_psql(self, sql: str, db: str | None = None) -> subprocess.CompletedProcess[str]:
        db_arg = f" -d {db}" if db else ""
        cmd = f"cd {self.project_root} && sudo -u postgres psql{db_arg} -c {repr(sql)}"
        return self._ssh(cmd)

    def run_migrate(self, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        root = str(cwd or self.project_root)
        cmd = (
            f"cd {root} && set -a && [ -f .env ] && source .env && set +a && "
            f"DB_HOST=localhost ./bazel-bin/migrate migrate --noinput"
        )
        return self._ssh(cmd)

    def update_env(self, key: str, value: str) -> None:
        env_path = self.project_root / ".env"
        val_esc = value.replace("'", "'\"'\"'")
        key_esc = key.replace("'", "'\"'\"'")
        cmd = f"sed -i.bak 's/^{key_esc}=.*/{key_esc}={val_esc}/' {env_path} 2>/dev/null || echo '{key_esc}={val_esc}' >> {env_path}"
        self._ssh(cmd)

    def run_shell(self, command: str, timeout_sec: int | None = None) -> subprocess.CompletedProcess[str]:
        """Run a shell command on the remote host via SSH."""
        return self._ssh(command, timeout_sec=timeout_sec)

    def read_checkpoint(self, path: Path) -> CheckpointData | None:
        result = self._ssh(f"cat {path}")
        if result.returncode != 0 or not result.stdout:
            return None
        try:
            data = json.loads(result.stdout)
            return CheckpointData.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def write_checkpoint(self, path: Path, data: CheckpointData) -> None:
        content = json.dumps(data.to_dict(), indent=2)
        tmp = str(path) + ".tmp"
        cmd = f"cat > {tmp} && mv {tmp} {path}"
        self._ssh(cmd, stdin=content)
