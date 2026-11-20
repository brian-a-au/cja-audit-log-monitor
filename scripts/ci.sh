#!/usr/bin/env bash
# Run the checks from .github/workflows/ci.yml on this machine.
#
# Usage:
#   scripts/ci.sh --quick                 ruff and the tests with coverage on Python 3.11
#   scripts/ci.sh [PYTHON_VERSION ...]    every CI stage (default: 3.11 3.12 3.13 3.14)
#
# GitHub runs every stage on each pull request, so --quick is enough before you push.
# The full run starts all stages at the same time. Each stage has its own environment,
# temp folder, coverage file and log under .ci/, so the stages do not share files.
set -Eeuo pipefail  # -E: the ERR trap also fires inside functions

cd "$(dirname "$0")/.."
unset VIRTUAL_ENV

QUICK=0
VERSIONS=()
for arg in "$@"; do
    case "$arg" in
        --quick) QUICK=1 ;;
        -*) echo "unknown option: $arg" >&2; exit 2 ;;
        *) VERSIONS+=("$arg") ;;
    esac
done
[ ${#VERSIONS[@]} -eq 0 ] && VERSIONS=(3.11 3.12 3.13 3.14)

LOGS=.ci/logs
mkdir -p "$LOGS"

# Options for every pytest run: a private temp folder and no shared cache.
pytest_opts() {
    echo "-q -p no:cacheprovider --basetemp=.ci/tmp-$1"
}

lint_and_test() {  # one Python version, in .ci/venv-VERSION
    local v=$1
    export UV_PROJECT_ENVIRONMENT=".ci/venv-$v"
    export COVERAGE_FILE=".ci/coverage-$v"
    uv sync --quiet --all-extras --python "$v"
    uv run --python "$v" ruff check src tests scripts
    uv run --python "$v" ruff format --check src tests scripts
    # shellcheck disable=SC2046
    uv run --python "$v" pytest $(pytest_opts "$v") --cov
}

floors() {  # the lowest direct dependency versions pyproject.toml allows
    rm -rf .ci/lowest
    uv venv --quiet .ci/lowest --python 3.11
    uv pip install --quiet --python .ci/lowest --resolution lowest-direct -e ".[dev]"
    # shellcheck disable=SC2046
    .ci/lowest/bin/pytest $(pytest_opts lowest)
}

newest() {  # the newest dependency versions
    rm -rf .ci/newest
    uv venv --quiet .ci/newest --python 3.14
    uv pip install --quiet --python .ci/newest --resolution highest -e ".[dev]"
    # shellcheck disable=SC2046
    .ci/newest/bin/pytest $(pytest_opts newest)
}

build() {  # sdist and wheel, then install the wheel and run it
    rm -rf .ci/dist .ci/smoke
    uv build --quiet --out-dir .ci/dist
    uv venv --quiet .ci/smoke
    uv pip install --quiet --python .ci/smoke .ci/dist/*.whl
    .ci/smoke/bin/cja-audit-log-monitor --help > /dev/null
}

if [ "$QUICK" -eq 1 ]; then
    echo "==> Quick check: lint and tests with coverage on Python 3.11"
    # Called on its own, not in an `if`: there set -e would not stop at a failed step.
    trap 'echo "FAILED"' ERR
    lint_and_test 3.11
    echo "All checks passed."
    exit 0
fi

# Start every stage in the background, each writing to its own log.
names=()
pids=()
start() {
    local name=$1
    shift
    ( set -e; "$@" ) > "$LOGS/$name.log" 2>&1 &
    names+=("$name")
    pids+=($!)
    echo "==> started $name (log: $LOGS/$name.log)"
}

failed=()

# The build goes first, on its own (about 15 seconds). The sdist build walks the project
# folder, and the other stages create and delete whole environments under .ci/ while they
# run, which made the build fail now and then when it ran beside them.
echo "==> build: sdist, wheel and a test install of the wheel"
# Started as a job and then waited for: inside an `if`, set -e would not stop at a failed step.
( set -e; build ) > "$LOGS/build.log" 2>&1 &
if wait $!; then
    echo "==> build: passed"
else
    echo "==> build: FAILED"
    failed+=(build)
fi

for v in "${VERSIONS[@]}"; do
    start "python-$v" lint_and_test "$v"
done
start floors floors
start newest newest

for i in "${!pids[@]}"; do
    if wait "${pids[$i]}"; then
        echo "==> ${names[$i]}: passed"
    else
        echo "==> ${names[$i]}: FAILED"
        failed+=("${names[$i]}")
    fi
done

if [ ${#failed[@]} -gt 0 ]; then
    for name in "${failed[@]}"; do
        echo
        echo "---- last lines of $LOGS/$name.log ----"
        tail -n 25 "$LOGS/$name.log"
    done
    echo
    echo "FAILED: ${failed[*]}"
    exit 1
fi
echo "All checks passed."
