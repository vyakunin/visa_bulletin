#!/usr/bin/env python3
"""
Update requirements.lock from requirements.txt using pip-compile.
Hermetic: Uses system Python with pip-tools (build-time dependency).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    # Get workspace directory (Bazel sets BUILD_WORKSPACE_DIRECTORY)
    workspace_dir = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', Path(__file__).parent.parent))
    requirements_txt = workspace_dir / 'requirements.txt'
    requirements_lock = workspace_dir / 'requirements.lock'

    if not requirements_txt.exists():
        print(f"ERROR: {requirements_txt} not found", file=sys.stderr)
        return 1

    # Use system Python (not Bazel's Python) for pip-tools
    # Find system Python - use the one that can run pip
    system_python = shutil.which('python3') or '/usr/bin/python3'

    # Verify this Python can run pip
    pip_check = subprocess.run(
        [system_python, '-m', 'pip', '--version'],
        capture_output=True,
        text=True
    )
    if pip_check.returncode != 0:
        print(f"ERROR: {system_python} cannot run pip", file=sys.stderr)
        return 1

    # Try to find pip-compile script first (preferred method)
    pip_compile_script = None
    user_bin = Path.home() / 'Library/Python/3.9/bin'
    if (user_bin / 'pip-compile').exists():
        pip_compile_script = str(user_bin / 'pip-compile')
    elif shutil.which('pip-compile'):
        pip_compile_script = shutil.which('pip-compile')

    # Check if pip-tools is available in system Python (only if script not found)
    if not pip_compile_script:
        check_result = subprocess.run(
            [system_python, '-c', 'import pip_tools'],
            capture_output=True,
            text=True
        )
    else:
        check_result = subprocess.CompletedProcess([], 0, '', '')  # Script exists, skip check

    if check_result.returncode != 0:
        # Install pip-tools if not available
        print("Installing pip-tools...", file=sys.stderr)
        install_result = subprocess.run(
            [system_python, '-m', 'pip', 'install', '--user', 'pip-tools'],
            capture_output=True,
            text=True
        )
        if install_result.returncode != 0:
            print("ERROR: Failed to install pip-tools. Install manually with:", file=sys.stderr)
            print("  python3 -m pip install --user pip-tools", file=sys.stderr)
            if install_result.stderr:
                print(install_result.stderr, file=sys.stderr)
            return 1

    # Get pip-tools installation location
    show_result = subprocess.run(
        [system_python, '-m', 'pip', 'show', 'pip-tools'],
        capture_output=True,
        text=True
    )

    # Extract location from pip show output
    pip_tools_location = None
    if show_result.returncode == 0:
        for line in show_result.stdout.split('\n'):
            if line.startswith('Location:'):
                pip_tools_location = line.split(':', 1)[1].strip()
                break

    # Get user site-packages directory
    user_site_result = subprocess.run(
        [system_python, '-m', 'site', '--user-site'],
        capture_output=True,
        text=True
    )
    user_site = user_site_result.stdout.strip() if user_site_result.returncode == 0 else None

    print(f"Generating {requirements_lock.name} from {requirements_txt.name}...")

    if pip_compile_script:
        # Use pip-compile script directly
        cmd = [
            pip_compile_script,
            '--output-file', str(requirements_lock),
            str(requirements_txt)
        ]
        env = os.environ.copy()
    else:
        # Use system Python to run pip-compile with user site-packages in PYTHONPATH
        cmd = [
            system_python,
            '-m', 'pip_tools.cli',
            'compile',
            '--output-file', str(requirements_lock),
            str(requirements_txt)
        ]

        env = os.environ.copy()
        pythonpath_parts = []
        if pip_tools_location and os.path.exists(pip_tools_location):
            pythonpath_parts.append(pip_tools_location)
        if user_site and os.path.exists(user_site):
            pythonpath_parts.append(user_site)
        if pythonpath_parts:
            existing_pythonpath = env.get('PYTHONPATH', '')
            env['PYTHONPATH'] = ':'.join(pythonpath_parts + ([existing_pythonpath] if existing_pythonpath else []))

    print(f"Using: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=workspace_dir, env=env)

    if result.returncode == 0:
        print(f"✓ Successfully generated {requirements_lock.name}")
        print("")
        print("Next steps:")
        print("  1. Review requirements.lock")
        print("  2. Commit if changes look correct")
        print("  3. Bazel will use the lock file automatically")
        return 0
    else:
        print(f"ERROR: pip-compile failed with exit code {result.returncode}", file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
