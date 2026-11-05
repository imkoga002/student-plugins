---
name: argument-map
description: "学生が書いた文章から論証の構造(主張・根拠・論拠・裏づけ・限定・反論)を逐語の引用つきで取り出し、Mermaid で図示し、欠けている接続を問いで示す。「論理の飛躍を見つけたい」「論証を図に」「トゥールミン」「根拠と論拠」「map my argument」「argument structure」などで使う。欠けを埋める文は出さない。"
---

# 論証マップ

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答・問い・説明を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
論証を組み立てるのは学生である(ガイドラインⅢ-1)。AI は学生が書いたものを映す鏡になる。欠けた論拠を AI が補うと論証の中心を書くことになるので、図の欠けは「(未記載)」と描いて問いだけを付ける。抽出が創作にならないよう、要素ごとに原稿からの逐語の引用を必須にし、道具が原稿と照合する。用語は「根拠 = data、論拠 = warrant」で固定する。

## 手順
1. 範囲(段落・節)を学生に決めてもらい、先に「この段落で読者に受け入れてほしい一文はどれか」を学生に尋ねる。
2. `review/argument-<name>.json` を作る(review/ は AI が書ける)。要素は `text`(60 字以内の要約)と `quote`(原稿の逐語)。書かれていない要素は null。推測で埋めない。
   ```json
   {"title":"第2節","arguments":[{"id":"A1","claim":{"text":"(要約)","quote":"(原稿の逐語)"},
    "data":[{"id":"D1","text":"(要約)","quote":"(原稿の逐語)"}],"warrant":null,"backing":null,"qualifier":null,"rebuttal":null}]}
   ```
3. 検証と図: `python3 tools/rk/rk.py argmap review/argument-<name>.json --manuscript manuscript/<file>.md --out review/argument-<name>.md`
   「引用の不一致」が出たら抽出の誤り。直す。
4. 図(front matter で theme・look・layout を固定済み)と「欠けている接続と問い」を学生に見せる。問いは 1〜2 個まで足してよいが、答えは書かない。
5. 学生が原稿を直したら再実行して差を見せる。判断の記録は学生が `thinking/log.md` に書く。

## してはいけないこと
欠けた論拠・裏づけ・反論の文、「〜という論拠を加えるとよい」、引用のない要素、総合点。
