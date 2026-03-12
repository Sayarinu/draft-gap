#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
BACKEND_ROOT="$(pwd)"

PYTHON=""
for candidate in python3.13 python3.12; do
  if command -v "$candidate" &>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  if [ -x "/opt/homebrew/opt/python@3.13/bin/python3.13" ]; then
    PYTHON="/opt/homebrew/opt/python@3.13/bin/python3.13"
  elif [ -x "/opt/homebrew/opt/python@3.12/bin/python3.12" ]; then
    PYTHON="/opt/homebrew/opt/python@3.12/bin/python3.12"
  fi
fi
if [ -z "$PYTHON" ]; then
  echo "Python 3.12 or 3.13 is required (greenlet does not build on 3.14)."
  echo "Install with: brew install python@3.13"
  echo "Then run this script again, or create the venv manually:"
  echo "  $(brew --prefix python@3.13 2>/dev/null || echo '/opt/homebrew/opt/python@3.13')/bin/python3.13 -m venv .venv"
  exit 1
fi

echo "Using: $PYTHON"
rm -rf .venv
"$PYTHON" -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
echo "Done. Activate with: source $BACKEND_ROOT/.venv/bin/activate"
exit 0
