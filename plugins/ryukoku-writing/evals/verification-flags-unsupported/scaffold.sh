#!/usr/bin/env bash
# Scaffold: an identity-confirmed source with a saved excerpt that does not support the sentence citing it.
set -eu
H="$(cd "$(dirname "$0")/.." && pwd)/_shared"
bash "$H/scaffold.sh" ja allowed
bash "$H/card.sh"
printf '\n2010 年代に現象 X は倍増した [@w2023, p. 3]。\n' >> manuscript/main.md
mkdir -p excerpts
printf 'source_id: S001\n(p. 3 の抜粋の見本)現象 X の記録は 2015 年から始まる。件数の増減については、この資料は述べていない。\n' > excerpts/S001-p3.txt
