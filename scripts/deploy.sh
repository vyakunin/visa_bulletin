#!/bin/bash
# Deploy a branch to an instance. Code-only, no data refresh.
# Usage: ./scripts/deploy.sh <instance-alias> [branch]
#   instance-alias: prod_2Gb_vm or staging_2Gb_vm
#   branch: defaults to matching environment (prod_2Gb_vm -> prod, staging_2Gb_vm -> staging)

set -e

INSTANCE="${1:?Usage: deploy.sh <instance-alias> [branch]}"

if [ -z "$2" ]; then
  case "$INSTANCE" in
    *prod*) BRANCH="prod" ;;
    *staging*) BRANCH="staging" ;;
    *) echo "Cannot auto-detect branch for $INSTANCE. Provide branch as second arg."; exit 1 ;;
  esac
else
  BRANCH="$2"
fi

echo "Deploying branch '$BRANCH' to $INSTANCE..."
ssh "$INSTANCE" "cd /opt/visa_bulletin && git fetch origin $BRANCH && git checkout $BRANCH && git reset --hard origin/$BRANCH"

echo "Restarting web container..."
ssh "$INSTANCE" "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml restart web"

echo "Verifying..."
ssh "$INSTANCE" "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml ps"
echo "Done."
