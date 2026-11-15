#!/bin/sh
# Run lint + tests in Docker (PostgreSQL included). Extra args go to pytest:
#   ./t.sh                 everything
#   ./t.sh tests/unit -x   a subset
# The PostgreSQL container is a dependency of the test run, so `run --rm`
# leaves it behind; it is stopped and removed when this script ends.
cd "$(dirname "$0")" || exit 1
compose="docker compose -f compose.test.yaml"
trap '$compose down --remove-orphans >/dev/null 2>&1' EXIT INT TERM
if [ $# -eq 0 ]; then
  $compose run --rm test
else
  $compose run --rm test pytest "$@"
fi
