#!/usr/bin/env bash
# Run the same checks as .github/workflows/ci.yml on this machine.
#
# GitHub Actions minutes are limited for private repos, so while the repo is
# private this script is the CI gate. Run it before you merge to main.
#
# Usage: scripts/ci.sh [PYTHON_VERSION ...]   (default: 3.11 3.12 3.13 3.14)
set -euo pipefail

cd "$(dirname "$0")/.."
VERSIONS=("$@")
[ ${#VERSIONS[@]} -eq 0 ] && VERSIONS=(3.11 3.12 3.13 3.14)

# Use a separate environment per version, so the normal .venv is left alone.
unset VIRTUAL_ENV
failed=()

for v in "${VERSIONS[@]}"; do
    echo "==> Python $v: lint and tests"
    export UV_PROJECT_ENVIRONMENT=".ci/venv-$v"
    if uv sync --quiet --all-extras --python "$v" \
        && uv run --python "$v" ruff check src tests scripts \
        && uv run --python "$v" ruff format --check src tests scripts \
        && uv run --python "$v" pytest -q; then
        echo "==> Python $v: passed"
    else
        echo "==> Python $v: FAILED"
        failed+=("$v")
    fi
done
unset UV_PROJECT_ENVIRONMENT

echo "==> Lowest dependency floors (Python 3.11)"
rm -rf .ci/lowest
if uv venv --quiet .ci/lowest --python 3.11 \
    && uv pip install --quiet --python .ci/lowest --resolution lowest-direct -e ".[dev]" \
    && .ci/lowest/bin/pytest -q; then
    echo "==> Floors: passed"
else
    echo "==> Floors: FAILED"
    failed+=("floors")
fi

echo "==> Newest dependency versions (Python 3.14)"
rm -rf .ci/newest
if uv venv --quiet .ci/newest --python 3.14 \
    && uv pip install --quiet --python .ci/newest --resolution highest -e ".[dev]" \
    && .ci/newest/bin/pytest -q; then
    echo "==> Newest: passed"
else
    echo "==> Newest: FAILED"
    failed+=("newest")
fi

echo "==> Build sdist and wheel"
rm -rf .ci/dist .ci/smoke
uv build --quiet --out-dir .ci/dist
echo "==> Smoke test the wheel"
uv venv --quiet .ci/smoke
uv pip install --quiet --python .ci/smoke .ci/dist/*.whl
.ci/smoke/bin/cja-audit-log-monitor --help > /dev/null
echo "==> Wheel installs and runs"

if [ ${#failed[@]} -gt 0 ]; then
    echo "FAILED on Python: ${failed[*]}"
    exit 1
fi
echo "All checks passed."
