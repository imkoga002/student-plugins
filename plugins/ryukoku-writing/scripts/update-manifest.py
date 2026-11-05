#!/usr/bin/env python3
"""Developer helper: regenerate scripts/rk/MANIFEST.sha256 after changing anything under scripts/rk/.
The manifest is what `rk check` and the human-only commands compare the code with (a changed
copy is refused before the passphrase is asked); tests/run.sh fails when it is out of date."""
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "rk"))
from rklib import check  # noqa: E402

root = os.path.join(HERE, "rk")
with open(os.path.join(root, check.MANIFEST), "w", encoding="utf-8") as f:
    f.write(check.build_manifest(root))
print("wrote", os.path.join(root, check.MANIFEST))
