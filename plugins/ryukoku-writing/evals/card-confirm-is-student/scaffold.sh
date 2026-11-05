#!/usr/bin/env bash
# Scaffold: shared project with placeholder content.
set -eu
bash "$(cd "$(dirname "$0")/.." && pwd)/_shared/scaffold.sh" ja allowed
