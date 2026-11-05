# data/

- `raw/`: 取得したままのデータ。変更しない。取り込みは `python3 tools/rk/rk.py data add <file> --url ... --provider ... --license ... --method ...`。
- `processed/`: 加工後のデータ。加工はスクリプトで行い、`provenance.jsonl` に kind: processing の記録を残す。
- `manifest-sha256.txt`: raw の SHA-256(`sha256sum -c` / `shasum -a 256 -c` で検査できる形式)。
- `numeric-claims.csv`: 本文の数値とデータのセルの対応(`rk.py data numbers --manuscript manuscript/main.md`)。
- `datapackage.json`: Frictionless Data Package v2(`rk.py data package` で作る)。
- 政府データの利用規約は「公共データ利用規約(第1.0版)」(2024-07-05)など、提供者の条件を provenance の license に書く。
