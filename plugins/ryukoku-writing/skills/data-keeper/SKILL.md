---
name: data-keeper
description: "研究データの保存と検証(生データは変更しない場所に、出所と SHA-256 を目録に、加工はスクリプトで、本文の数値と元データの対応)。「データを保存」「統計を取り込む」「数値を確認」「data provenance」「check my numbers」などで使う。"
---

# データの保存と検証

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
データの改ざんや都合のよい抜き出しを防ぎ、後で誰でも確かめられるようにするため。raw は変更しない(フックが書き込みを止める)。

## 手順
- 取り込み: `python3 tools/rk/rk.py data add <file> --url <取得元> --provider <提供者> --license <利用条件> --method <取得方法>`(raw に置き、読み取り専用にし、manifest と provenance.jsonl に記録)
- 検査: `python3 tools/rk/rk.py data verify`(ハッシュ、出所の欠落、datapackage.json)
- 本文の数値: `data/numeric-claims.csv` に「本文の値・ファイル・列・キー」を書き、`python3 tools/rk/rk.py data numbers --manuscript manuscript/<file>.md`
- Data Package v2: `python3 tools/rk/rk.py data package`
- 加工はスクリプトで data/processed/ に出し、provenance.jsonl に kind: processing の行(output・script・inputs・run_at)を残す

## 注意
- API の生の応答を raw に入れる前に、提供者の規約を確かめる(J-STAGE は機械可読な形での 24 時間以上の保存を禁じる)。e-Stat は appId とクレジット表記が要る
- 政府データの利用規約は「公共データ利用規約(第1.0版)」(2024-07-05)など、提供者の条件を license に書く
- 数値を記憶から出さない。データがなければ「ない」と伝える
