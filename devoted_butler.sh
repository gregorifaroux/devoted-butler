#!/usr/bin/env bash
cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")" || exit 1
source .venv/bin/activate

if ! curl -sf http://127.0.0.1:11434 > /dev/null; then
  echo "Ollama isn't running, starting it..."
  ollama serve > /dev/null 2>&1 &
  until curl -sf http://127.0.0.1:11434 > /dev/null; do sleep 1; done
fi

echo "Ollama is up."
python devoted_butler.py
