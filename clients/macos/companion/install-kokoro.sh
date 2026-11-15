#!/bin/zsh
set -eu
cd "${0:A:h}"

if ! command -v uv >/dev/null; then
  echo "Install uv first: brew install uv" >&2
  exit 1
fi

uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
  'mlx-audio>=0.3,<1' 'misaki>=0.9,<1' 'soundfile>=0.13,<1'
echo "Kokoro installed. The model downloads on the first companion run."
