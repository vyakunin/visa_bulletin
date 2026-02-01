#!/usr/bin/env bash
# Run the full test suite on the staging VM.
# Uses .env on the VM for DB credentials. DB user must have CREATEDB (or use postgres for tests).
# Tests create and use test_postgres; they never touch the real app DB.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SSH_ALIAS="${1:-staging_2Gb_vm}"

echo "Running tests on $SSH_ALIAS (cd /opt/visa_bulletin, source .env, bazel test //tests/...)"
ssh "$SSH_ALIAS" "cd /opt/visa_bulletin && set -a && source .env && set +a && bazel test //tests/... --test_output=errors"
