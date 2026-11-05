#!/usr/bin/env bash
# Scaffold: shared project with the course AI policy recorded as prohibited.
set -eu
bash "$(cd "$(dirname "$0")/.." && pwd)/_shared/scaffold.sh" ja prohibited
