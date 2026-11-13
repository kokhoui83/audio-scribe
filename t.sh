#!/bin/sh
# Run lint + tests in Docker (PostgreSQL included). Extra args go to pytest:
#   ./t.sh                 everything
#   ./t.sh tests/unit -x   a subset
set -e
cd "$(dirname "$0")"
if [ $# -eq 0 ]; then
  exec docker compose -f compose.test.yaml run --rm test
fi
exec docker compose -f compose.test.yaml run --rm test pytest "$@"
