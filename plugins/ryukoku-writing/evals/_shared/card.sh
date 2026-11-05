#!/usr/bin/env bash
# Shared helper for the v2 evals: a claim card C001 written from the student's words and confirmed by the student
# (a light confirmation, as the notebook button records it), and the ledger source S001 (citekey w2023) marked
# IDENTITY_CONFIRMED as refcheck would. Run after scaffold.sh in the eval workspace. Placeholder content only.
set -eu
mkdir -p claims
cat > claims/C001.md <<'MD'
---
id: C001
status: draft
created: 2026-11-05
---
# 主張
要因 A は現象 X の一因となりうる。

## 範囲と限定
2010 年代の事例に限る。

## 必要な根拠
- 年ごとの記録 @w2023

## 論拠
- 要因 A が先に起きている

## 予想される反論
- [ai_suggested] 逆の因果(現象 X が要因 A を生む)

## 新規性の見込み
未調査

## 学生の言葉の原文
> 要因 A が現象 X の原因の一つだと思う。2010 年代の話として。
MD
python3 -B - <<'PY'
import csv, sys
sys.path.insert(0, "tools/rk")
from rklib import sign, subjects
p = "sources/register.csv"
rows = list(csv.DictReader(open(p, encoding="utf-8")))
fields = open(p, encoding="utf-8").readline().strip().split(",")
for r in rows:
    r["citekey"] = "w2023"
    r["machine_status"] = "IDENTITY_CONFIRMED"
with open(p, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
s = subjects.find(".", "card", "C001")
sign.append_signoffs(".", [sign.make_confirmation("card", "C001", "confirmed", s.digest, method="notebook")])
PY
sed -i.bak -e 's/^status: draft/status: confirmed/' claims/C001.md && rm -f claims/C001.md.bak
