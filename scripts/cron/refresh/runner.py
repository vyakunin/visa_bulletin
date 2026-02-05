# scripts/cron/refresh/runner.py
"""Runner protocol and implementations: LocalRunner, RemoteRunner, MockRunner."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .checkpoint import CheckpointData, read_checkpoint, write_checkpoint as write_checkpoint_file


@runtime_checkable
class Runner(Protocol):
    """Execution backend: run commands and read/write checkpoint on the target host."""

    def run_bin(self, rel_path: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run pre-built binary or bazel run. rel_path e.g. 'scripts/salary/cluster_job_titles'."""
        ...

    def run_psql(self, db_name: str, sql: str) -> str:
        """Run psql -t -c and return stdout."""
        ...

    def run_sudo_psql(self, sql: str) -> subprocess.CompletedProcess[str]:
        """Run sudo -u postgres psql -c."""
        ...

    def run_migrate(self, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run Django migrate --noinput."""
        ...

    def update_env(self, key: str, value: str) -> None:
        """Update .env key=value on target host."""
        ...

    def detect_active_env(self) -> str:
        """Return 'blue' or 'green' based on nginx config."""
        ...

    def read_checkpoint(self, path: Path) -> CheckpointData | None:
        """Read checkpoint JSON from target host."""
        ...

    def write_checkpoint(self, path: Path, data: CheckpointData) -> None:
        """Write checkpoint JSON on target host (atomic)."""
        ...


class LocalRunner:
    """Run commands on this host via subprocess."""

    def __init__(self, project_root: Path, env_file: Path, env: dict[str, str] | None = None):
        self.project_root = Path(project_root)
        self.env_file = Path(env_file)
        self._env = dict(os.environ)
        if env:
            self._env.update(env)

    def run_bin(self, rel_path: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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

    def run_sudo_psql(self, sql: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sudo", "-u", "postgres", "psql", "-c", sql],
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

    def detect_active_env(self) -> str:
        nginx_conf = self.project_root / "deployment" / "nginx" / "visa-bulletin-locations.conf"
        if not nginx_conf.exists():
            return "blue"
        text = nginx_conf.read_text()
        if "8001" in text:
            return "green"
        return "blue"

    def read_checkpoint(self, path: Path) -> CheckpointData | None:
        return read_checkpoint(Path(path))

    def write_checkpoint(self, path: Path, data: CheckpointData) -> None:
        write_checkpoint_file(Path(path), data)


class MockRunner:
    """Record runner calls for tests. Returns success by default."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._checkpoint: CheckpointData | None = None
        self.run_bin_return: subprocess.CompletedProcess[str] | None = None
        self.run_psql_return: str = "0"
        self.run_sudo_psql_return: subprocess.CompletedProcess[str] | None = None
        self.run_migrate_return: subprocess.CompletedProcess[str] | None = None

    def run_bin(self, rel_path: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        self.calls.append(("run_bin", (rel_path, *args), {"cwd": cwd}))
        if self.run_bin_return is not None:
            return self.run_bin_return
        return subprocess.CompletedProcess(args=[rel_path, *args], returncode=0, stdout="", stderr="")

    def run_psql(self, db_name: str, sql: str) -> str:
        self.calls.append(("run_psql", (db_name, sql), {}))
        return self.run_psql_return

    def run_sudo_psql(self, sql: str) -> subprocess.CompletedProcess[str]:
        self.calls.append(("run_sudo_psql", (sql,), {}))
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

    def detect_active_env(self) -> str:
        self.calls.append(("detect_active_env", (), {}))
        return "blue"

    def read_checkpoint(self, path: Path) -> CheckpointData | None:
        self.calls.append(("read_checkpoint", (str(path),), {}))
        return self._checkpoint

    def write_checkpoint(self, path: Path, data: CheckpointData) -> None:
        self.calls.append(("write_checkpoint", (str(path), data), {}))
        self._checkpoint = data


class RemoteRunner:
    """Run commands on a remote host via SSH. Checkpoint read/write on remote."""

    def __init__(
        self,
        host: str,
        project_root: str | Path = "/opt/visa_bulletin",
        ssh_user: str = "ubuntu",
        ssh_key_path: str | None = None,
        env_file: str | Path = ".env",
    ) -> None:
        self.host = host
        self.project_root = Path(project_root)
        self.ssh_user = ssh_user
        self.ssh_key_path = ssh_key_path
        self.env_file = Path(env_file) if isinstance(env_file, Path) else self.project_root / ".env"

    def _ssh(self, command: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10"]
        if self.ssh_key_path:
            cmd.extend(["-i", self.ssh_key_path])
        cmd.append(f"{self.ssh_user}@{self.host}")
        cmd.append(command)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=stdin,
            timeout=3600,
        )

    def run_bin(self, rel_path: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        root = str(cwd or self.project_root)
        bin_path = f"{root}/bazel-bin/{rel_path}"
        args_s = " ".join(shlex.quote(a) for a in args)
        cmd = f"cd {root} && set -a && [ -f .env ] && source .env && set +a && "
        cmd += f"if [ -x {bin_path} ]; then {bin_path} {args_s}; else bazel run //{rel_path} -- {args_s}; fi"
        result = self._ssh(cmd)
        return result

    def run_psql(self, db_name: str, sql: str) -> str:
        sql_esc = sql.replace("'", "'\"'\"'")
        cmd = f"cd {self.project_root} && set -a && [ -f .env ] && source .env && set +a && psql -h localhost -U ${{DB_USER:-visa_bulletin_user}} -d {db_name} -t -c '{sql_esc}'"
        result = self._ssh(cmd)
        return (result.stdout or "").strip() if result.returncode == 0 else ""

    def run_sudo_psql(self, sql: str) -> subprocess.CompletedProcess[str]:
        cmd = f"cd {self.project_root} && sudo -u postgres psql -c {repr(sql)}"
        return self._ssh(cmd)

    def run_migrate(self, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        root = str(cwd or self.project_root)
        cmd = f"cd {root} && set -a && [ -f .env ] && source .env && set +a && python3 manage.py migrate --noinput"
        return self._ssh(cmd)

    def update_env(self, key: str, value: str) -> None:
        env_path = self.project_root / ".env"
        val_esc = value.replace("'", "'\"'\"'")
        key_esc = key.replace("'", "'\"'\"'")
        cmd = f"sed -i.bak 's/^{key_esc}=.*/{key_esc}={val_esc}/' {env_path} 2>/dev/null || echo '{key_esc}={val_esc}' >> {env_path}"
        self._ssh(cmd)

    def detect_active_env(self) -> str:
        nginx = self.project_root / "deployment" / "nginx" / "visa-bulletin-locations.conf"
        result = self._ssh(f"grep -q 8001 {nginx} && echo green || echo blue")
        return (result.stdout or "blue").strip()

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
