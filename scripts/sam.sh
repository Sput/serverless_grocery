#!/usr/bin/env bash
# Local tools wrapper. Remote SAM actions require an explicit opt-in.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
case "${1:-}" in
  build|--version|--help|help) ;;
  validate)
    if [[ " $* " != *" --lint "* ]]; then
      echo 'Use: bash scripts/sam.sh validate --lint (local validation)' >&2
      exit 2
    fi
    ;;
  *)
    if [[ "${GROCERY_ALLOW_AWS:-}" != YES ]]; then
      echo 'Remote SAM actions are blocked. Obtain deployment approval first.' >&2
      exit 2
    fi
    ;;
esac
export PATH="$PWD/.tools/lambda-venv/bin:$PATH"
export PYTHONPATH="$PWD/.tools/sam-cli"
export SAM_CLI_TELEMETRY=0
export AWS_DEFAULT_REGION=us-east-1
export AWS_EC2_METADATA_DISABLED=true
export PIP_CACHE_DIR="$PWD/.tools/pip-cache"
exec .tools/lambda-venv/bin/python .tools/sam-cli/bin/sam "$@"
