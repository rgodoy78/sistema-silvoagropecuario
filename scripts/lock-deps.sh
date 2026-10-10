#!/usr/bin/env bash
# Genera requirements.txt con versiones fijas y hashes SHA256 (pip --require-hashes).
set -euo pipefail
cd "$(dirname "$0")/.."
docker run --rm -v "$PWD":/w -w /w python:3.13-slim-trixie sh -c \
  'pip install -q pip-tools && pip-compile -q --generate-hashes --allow-unsafe --strip-extras -o requirements.txt requirements.in'
