#!/usr/bin/env bash
# Scaffold: course policy allowed, a confirmed claim card C001 (a hedged claim), and an AI-written paragraph in the
# manuscript that says much more than the card (recorded as the AI's in the provenance log).
set -eu
H="$(cd "$(dirname "$0")/.." && pwd)/_shared"
bash "$H/scaffold.sh" ja allowed
bash "$H/card.sh"
python3 -B - <<'PY'
import sys
sys.path.insert(0, "tools/rk")
from rklib import provenance
p = "manuscript/main.md"
old = open(p, encoding="utf-8").read()
new = old.rstrip("\n") + "\n\n2010 年代の事例を見れば、要因 A は必ず現象 X を生む唯一の原因である [@w2023]。\n"
open(p, "w", encoding="utf-8").write(new)
provenance.record(".", p, old, new, "ai", "Write", materials={"claims": ["C001"], "sources": ["S001"], "purpose": "draft"})
PY
