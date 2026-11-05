---
name: export-submission
description: "原稿を提出形式(Word の docx、PDF、LaTeX)に書き出す。Mermaid の図と TeX の数式を含む。「Word にしたい」「docx に変換」「PDF にしたい」「提出用に書き出し」「export to Word」「make a PDF」などで使う。原稿は書き換えず、build/ に写しを作る。"
---

# 提出形式への書き出し

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
龍谷大学の多くの学部は Word・A4 で manaba に提出する(履修要項Webサイト https://rishu.ryukoku.ac.jp/ の学部ごとの卒業論文の頁。2026年度入学生の頁を 2026-11-04 に確認。入学年度で違うことがある)ので、docx の経路を第一にする。書き出しは原稿を変えない(build/ の写しで処理する)。

## 手順
- docx: `python3 tools/rk/rk.py export docx` → build/manuscript.docx
  - 設定は `pandoc/defaults-<lang>-docx.yaml`(.ryukoku/config.yml の manuscript_lang で切り替わる)。日本語は `+east_asian_line_breaks`(ないと段落内の改行が空白になる)
  - 見た目は `pandoc/reference.docx`(初期化時に pandoc の既定から作った)。学生が Word でスタイル(フォント・余白・A4・行数)だけを直す。数値は学部の要項に従う
  - 引用は citeproc + `sources/references.json`(CSL-JSON)。書式は学部が指定する CSL を `pandoc/` に置く(日本語は公式 CSL リポジトリに SIST02 がある)
- PDF: `python3 tools/rk/rk.py export pdf`(LuaLaTeX + LuaTeX-ja、`ltjsarticle` か `jlreq`。TeX Live の collection-langjapanese。英語は標準の article)。PDF・LaTeX の設定では `lang` を設定しない(pandoc は lang があると babel を読み込む: pandoc の LaTeX テンプレート common.latex、https://github.com/jgm/pandoc/blob/main/data/templates/common.latex 。babel と jlreq・LuaTeX-ja の組み合わせは未確認のため)
- LaTeX: `python3 tools/rk/rk.py export latex`(提出先が LaTeX を求めるとき)
- 書式の見本(数式・論証図・因果図・研究の流れ・年表・概念図・表・脚注・相互参照)の確認: `python3 tools/rk/rk.py export docx --file examples/format-examples.md`

## Mermaid
- mmdc(@mermaid-js/mermaid-cli。Node 22.13 以上)があれば、書き出しで図を PNG にして差し込む(docx・LaTeX は PNG が無難)。日本語フォントがない環境では文字化けするので確かめる
- なければ図はコードのまま出る。手で `mmdc -i build/fig-1.mmd -o build/fig-1.png` を実行するか、pandoc-ext/diagram(Lua フィルタ。同梱していない)を使う
- 図の先頭の front matter(theme・look・layout)を消さない(Mermaid 12 で既定の見た目が変わった)

## 道具がないとき(手作業の経路)
manuscript/*.md の本文を Word に貼り、見出しを Word のスタイルに合わせ、図は mmdc を使える環境で PNG にして挿入し、数式は Word の数式機能で入力する。書き出しの前後で内容が変わっていないか学生が確かめる。

## CI
`.github/workflows/build.yml` が pandoc 3.13(pandoc/actions/setup@v1)で docx を作り、成果物として残す。
