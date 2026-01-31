#!/bin/bash
# Run tests for SemiRouter
#
# Usage:
#   ./run_tests.sh          # Run fast tests in parallel
#   ./run_tests.sh fast     # Run fast tests in parallel
#   ./run_tests.sh slow     # Run slow tests in parallel (~35s)
#   ./run_tests.sh all      # Run all tests in parallel (~35s)
#
# Requires: pip install pytest-xdist

set -e

MODE="${1:-fast}"

case "$MODE" in
    fast)
        echo "Running fast tests (parallel)..."
        python -m pytest tests/test_routing.py -m "not slow" -n auto -v
        ;;
    slow)
        echo "Running slow tests (parallel)..."
        python -m pytest tests/test_routing.py -m "slow" -n auto -v
        ;;
    all)
        echo "Running all tests (parallel)..."
        python -m pytest tests/test_routing.py -n auto -v
        ;;
    *)
        echo "Usage: $0 [fast|slow|all]"
        echo "  fast - Run fast unit tests only (default)"
        echo "  slow - Run slow integration tests in parallel"
        echo "  all  - Run all tests in parallel"
        exit 1
        ;;
esac
