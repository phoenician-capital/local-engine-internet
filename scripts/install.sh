#!/bin/sh
# One-command install for teammates. From the repo root, or:
#   curl -fsSL https://raw.githubusercontent.com/phoenician-capital/local-engine-internet/main/scripts/install.sh | sh
set -e
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required (3.12 recommended)" >&2
  exit 1
fi
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
pip install -q -r requirements-dev.txt
python -m engine setup
echo
echo "Next: put SERPAPI_KEY in .env if setup said it is missing, then:"
echo "  .venv/bin/python -m engine"
