#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec python3 -m evidence_suite.run --plan evidence-plan.local.json "$@"
