#!/usr/bin/env bash
# Scaffold: course policy allowed, a confirmed claim card C001 and one identity-confirmed source (w2023) only.
set -eu
H="$(cd "$(dirname "$0")/.." && pwd)/_shared"
bash "$H/scaffold.sh" ja allowed
bash "$H/card.sh"
