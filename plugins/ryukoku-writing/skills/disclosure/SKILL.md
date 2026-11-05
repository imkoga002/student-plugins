---
name: disclosure
description: "AI 利用の開示: 由来の記録(AI が書いた段落の割合・節ごとの内訳・用途)と AI 利用記録から事実の一覧を出し、開示文の下書き(disclosure/statement.md)を作る。ガイドラインの更新を確かめる。「AI 利用の開示」「AI をどう使ったか書きたい」「利用記録」「disclose AI use」「AI usage statement」「ガイドラインは変わった?」などで使う。開示文は学生が最終確認で確かめる。"
---

# AI 利用の開示

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
ガイドラインⅢ-4 は提出時の記載項目の例として、AI の種類・バージョン、利用年月日、プロンプトの概要、どの部分でどのように利用したか、を挙げる。利用を隠して評価を得ることは注意事例に挙がっている。記録はフックが自動で取り(`.ryukoku/ai-use-log.jsonl` と、原稿の段落ごとの由来 `.ryukoku/provenance.jsonl`。どちらも行が前の行のハッシュを持ち、消すと検査が落ちる)、AI は書き換えられない。プロンプトの本文は機密が混ざりうるので記録せず、種類だけを記録する。開示文の下書きは AI が作ってよいが、事実の一覧にあることだけを書く(盛らない・隠さない)。学生は提出前の最終確認(合言葉の署名)で、開示文が正しいと宣言する。学生の編集は推定であることを開示文でもそのまま書く。

## 手順
1. 事実の一覧: `python3 tools/rk/rk.py facts`(5 に、AI が書いた・直した段落の数と割合、節ごとの内訳、用途、材料が出る)
2. 開示文の下書きを `disclosure/statement.md` に Write で書く。ガイドラインⅢ-4 の記載項目の例(AI の種類・バージョン、利用年月日、プロンプトの概要、どの部分でどのように)に沿い、事実の一覧の数字をそのまま使う。プロンプトの概要は、学生が確認した日ごとの概要があればそれを使い、なければ「記録された種類」であることが分かるように書く
3. 「未確認」の日があれば、学生に証拠ノートの「提出前」(または端末の `./rk disclose`)で、その日の概要を自分の言葉で書いて記録するよう案内する
4. 開示の形式と置き場所は科目の指示(.ryukoku/config.yml の disclosure_format)に従う。不明なら教員に確かめるよう伝える。下書きを原稿に入れるのは、科目が許すときに `draft-writer` の手順で(由来に残る)
5. 英語の論文で APA や MLA の書き方が要るなら、各様式の公式の案内を学生と一緒に開いて確かめる(記憶から書式を断定しない)。開発時(2026-11-04)に読めた案内: APA「AI Contribution Statement Guide」https://apastyle.apa.org/instructional-aids/ai-contribution-statement.pdf 、MLA「Citing generative AI (updated and revised)」https://style.mla.org/citing-generative-ai-updated-revised/ 。Chicago の案内は読めず未確認

## ガイドラインの更新確認(ガイドラインⅣ: 継続的に見直される)
`python3 tools/rk/rk.py guideline-check`(ネットワークを使う。学生の了承を得てから)。記録の SHA-256 と違えば、改訂の可能性を伝え、原文を読むよう勧める。Plugin の記述はガイドラインの解釈であり、大学の公式見解ではない。
