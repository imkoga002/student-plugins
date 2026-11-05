#!/usr/bin/env bash
# Scaffold: shared project, course policy allowed, a confirmed claim card C001 and an identity-confirmed source.
set -eu
H="$(cd "$(dirname "$0")/.." && pwd)/_shared"
bash "$H/scaffold.sh" ja allowed
bash "$H/card.sh"
