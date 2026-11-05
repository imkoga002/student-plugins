---
name: disclosure
description: "AI 利用の開示の材料(事実の一覧)を出す。ガイドラインの更新を確かめる。「AI 利用の開示」「AI をどう使ったか書きたい」「利用記録」「disclose AI use」「AI usage statement」「ガイドラインは変わった？」などで使う。開示文は学生が書く。"
---

# AI 利用の開示

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
ガイドラインⅢ-4 は提出時の記載項目の例として、AI の種類・バージョン、利用年月日、プロンプトの概要、どの部分でどのように利用したか、を挙げる。利用を隠して評価を得ることは注意事例に挙がっている。記録はフックが自動で取り(`.ryukoku/ai-use-log.jsonl`。行が前の行のハッシュを持ち、消すと検査が落ちる)、AI は書き換えられない。プロンプトの本文は機密が混ざりうるので記録せず、種類だけを記録する。日ごとの概要は学生が自分の言葉で書いて署名する。開示文そのものは学生が書く(AI が書くと開示文の代筆になる)。

## 手順
1. 事実の一覧: `python3 tools/rk/rk.py facts`
2. 「未確認」の日があれば、学生に証拠ノートの「提出前」(または端末の `./rk disclose`)で、その日の概要を自分の言葉で書いて署名するよう案内する
3. 採用した表記の提案は、署名つきの記録と disclosure/ai-involvement.jsonl に自動で入っている
4. 開示の形式と置き場所は科目の指示(.ryukoku/config.yml の disclosure_format)に従う。不明なら教員に確かめるよう伝える
5. 英語の論文で APA や MLA の書き方が要るなら、各様式の公式の案内を学生と一緒に開いて確かめる(記憶から書式を断定しない)。開発時(2026-11-04)に読めた案内: APA「AI Contribution Statement Guide」https://apastyle.apa.org/instructional-aids/ai-contribution-statement.pdf 、MLA「Citing generative AI (updated and revised)」https://style.mla.org/citing-generative-ai-updated-revised/ 。Chicago の案内は読めず未確認

## ガイドラインの更新確認(ガイドラインⅣ: 継続的に見直される)
`python3 tools/rk/rk.py guideline-check`(ネットワークを使う。学生の了承を得てから)。記録の SHA-256 と違えば、改訂の可能性を伝え、原文を読むよう勧める。Plugin の記述はガイドラインの解釈であり、大学の公式見解ではない。
