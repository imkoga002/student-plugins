---
name: style-extract
description: "学部の執筆要項(PDF)・シラバス・教員の配布資料・見本の論文の画像から、記法の規則(句読点、文体、字数、見出し、引用書式、図表のキャプション位置、注、数字の表記など)を抽出し、根拠と確信度つきの「提案」として置く。「執筆要項を読み込んで」「書式のルールを設定」「この PDF のルール」「extract style rules from this guide」などで使う。学生が一件ずつ承認するまで適用しない。"
---

# 記法規則の抽出

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜ提案にとどめるのか
規則の読み違いをそのまま検査に使うと、学生は誤った規則で原稿を直してしまう。だから抽出した規則は `proposals/style-rules.yml` に置き、学生が原典と照らして一件ずつ承認する(証拠ノートの「記法」のボタンか `./rk style`。合言葉は要らない)。承認された規則だけが `.ryukoku/style.yml` に入り、lint と表記の提案に使われる。国の表記の基準は学術文を拘束しない既定値にとどまり、優先するのは教員・学部の指示である(「公用文作成の考え方」(文化審議会建議、2022)は政府の公用文の手引: https://www.bunka.go.jp/seisaku/bunkashingikai/kokugo/hokoku/pdf/93731901_01.pdf 。常用漢字表(平成22年内閣告示第2号)の前書きは、科学・技術などの専門分野や個々人の表記にまで及ぼすものではないとする: https://www.bunka.go.jp/kokugo_nihongo/sisaku/joho/joho/kijun/naikaku/pdf/joyokanjihyo_20101130.pdf)。ガイドラインやシラバスの指示(Ⅲ-3)が常に優先する。

## 手順
1. 資料を学生から受け取る(PDF・画像・URL)。学部・学科・入学年度を尋ねる(卒論の規程は学部と入学年度で違う。履修要項Webサイト https://rishu.ryukoku.ac.jp/ に入学年度別に公開されている学部と、学科・指導教員に委ねる学部がある。2026-11-04 確認)。
2. 資料を読む(PDF は Read の pages 指定、画像は Read で見る)。読めなかった頁は「未読」と伝える。
3. 規則ごとに `proposals/style-rules.yml` に追記する。必須の欄:
   ```yaml
     - id: "punct"
       kind: "punctuation"        # punctuation | forbidden_word | ending_style | number_width | max_chars | min_chars
                                  # | heading_numbering | caption_position | citation_style | note_style | paper | font | other
       value: "、。"
       lang: "ja"
       source: "<資料名・URL・版>"
       page: "<頁・節>"
       quote: "<該当箇所の要約(長い転載はしない)>"
       confidence: "high"         # high | medium | low(読み取りの確かさ)
       status: "proposed"
   ```
   画像から読んだ値(余白・行数など)は confidence を下げ、学生が原典で確かめるよう note に書く。資料にない値を補わない。
4. 検査: `python3 tools/rk/rk.py rules validate`(source が空の規則、status が proposed でない規則はエラー)
5. 学生に案内: 「証拠ノートの『記法』で根拠と照らして一件ずつ承認・却下を記録する(合言葉は要らない。端末なら ./rk style)」。AI は .ryukoku/style.yml を書けない。
6. 承認後は `python3 tools/rk/rk.py lint` が承認済みの規則だけで指摘し、`propose style` で機械的な直しを提案にできる。

## テストや見本に使う資料
Plugin の tests/fixtures の要項は、公開資料(履修要項Webサイトの「経済学部 卒業研究・研究科について」https://rishu.ryukoku.ac.jp/curriculum/faculty-econ/s04 の要約)を出典つきで使っている。架空の数値を「規程」として置かない。
