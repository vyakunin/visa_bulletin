#!/bin/bash
# End-to-end script: Ingest data and then cluster employers
#
# This script:
# 1. Runs the ingest pipeline (with clustering disabled for performance)
# 2. Runs employer clustering on all employers (including newly imported ones)
#
# Usage:
#   bazel run //scripts/ingest:ingest_and_cluster -- --source-id 123
#   bazel run //scripts/ingest:ingest_and_cluster -- --all-pending
#
# Or run directly:
#   ./scripts/ingest/ingest_and_cluster.sh --source-id 123

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT"

echo "=========================================="
echo "Ingest and Cluster Workflow"
echo "=========================================="
echo ""

# Parse arguments
INGEST_ARGS=()
CLUSTER_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --source-id)
            INGEST_ARGS+=("--source-id" "$2")
            shift 2
            ;;
        --all-pending)
            INGEST_ARGS+=("--all-pending")
            shift
            ;;
        --url)
            INGEST_ARGS+=("--url" "$2")
            shift 2
            ;;
        --skip-clustering)
            echo "⚠️  Warning: --skip-clustering flag ignored (clustering always runs after ingest)"
            shift
            ;;
        --cluster-threshold)
            CLUSTER_ARGS+=("--threshold" "$2")
            shift 2
            ;;
        --cluster-dry-run)
            CLUSTER_ARGS+=("--dry-run")
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--source-id ID | --all-pending | --url URL] [--cluster-threshold FLOAT] [--cluster-dry-run]"
            exit 1
            ;;
    esac
done

# Default cluster threshold if not specified
if [[ ! " ${CLUSTER_ARGS[@]} " =~ " --threshold " ]]; then
    CLUSTER_ARGS+=("--threshold" "0.95")
fi

# Step 1: Run ingest pipeline
echo "Step 1: Running ingest pipeline..."
echo "----------------------------------------"
bazel run //scripts/ingest:run_pipeline -- run "${INGEST_ARGS[@]}"

INGEST_EXIT_CODE=$?
if [ $INGEST_EXIT_CODE -ne 0 ]; then
    echo "❌ Ingest pipeline failed (exit code: $INGEST_EXIT_CODE)"
    echo "Skipping clustering step"
    exit $INGEST_EXIT_CODE
fi

echo ""
echo "✅ Ingest pipeline completed successfully"
echo ""

# Step 2: Run employer clustering
echo "Step 2: Running employer clustering..."
echo "----------------------------------------"
echo "This will cluster all employers, including newly imported ones."
echo ""

bazel run //scripts/salary:cluster_existing_employers -- "${CLUSTER_ARGS[@]}"

CLUSTER_EXIT_CODE=$?
if [ $CLUSTER_EXIT_CODE -ne 0 ]; then
    echo "❌ Clustering failed (exit code: $CLUSTER_EXIT_CODE)"
    exit $CLUSTER_EXIT_CODE
fi

echo ""
echo "✅ Clustering completed successfully"
echo ""
echo "=========================================="
echo "Workflow completed successfully!"
echo "=========================================="

