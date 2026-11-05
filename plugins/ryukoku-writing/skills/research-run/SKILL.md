---
name: research-run
description: "調査計画に沿って検索を実行し、検索の記録(DB・検索式・日付・件数・問いの番号・目的・選んだ理由)を自動で残し、候補を実在確認する。複数の観点はサブエージェントで並列に調べる(NDL は逐次)。「調べて」「文献を探して」「検索して」「run the search」「find sources for Q1」などで使う。結論は出さない。"
---

# 調査の実行

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
検索の記録は、卒論の「先行研究の探し方」や指導教員への説明にそのまま使える形で残す必要がある。人が書き忘れないよう、`rk.py search` は実行のたびに `research/search-log.jsonl` に一行を自動で書き、WebSearch と、データベースの検索 URL への WebFetch も PostToolUse フックが自動で記録する。検索記録は AI が直接書き換えられない(フック)。候補は自動で選ばない(上位を自動で採らない。開発時の観察: Crossref の書誌検索で、雑誌に載った版より前刷り(preprint)が上位に出た)。

## 手順
1. `research/questions.md` の問いの番号(Q1 など)を確かめる。ない番号では検索の道具が通信せずに止まる(終了コード 2)。
2. 観点ごとに `research-scout` サブエージェントを並列に起動する(例: 日本語の論文、英語の論文、図書・統計、反証)。各サブエージェントへの指示に、問いの番号、DB、検索語、目的(main / counter)、返す形式(候補の表と検索記録の id)を書く。**NDL を使うのは一つのサブエージェントだけ**(同時接続で 429 が出る。道具もロックで逐次にする)。
3. 検索(自動で記録される):
   ```
   python3 tools/rk/rk.py search crossref "<検索語>" --question-ref Q1
   python3 tools/rk/rk.py search cinii-books "<検索語>" --question-ref Q1
   python3 tools/rk/rk.py search cinii-research "<検索語>" --question-ref Q1 --type articles   # appid が要る
   python3 tools/rk/rk.py search ndl "<題名の語>" --question-ref Q1
   python3 tools/rk/rk.py search jstage "<検索語>" --question-ref Q1    # 表示に Powered by J-STAGE
   python3 tools/rk/rk.py search datacite "<検索語>" --question-ref Q1
   python3 tools/rk/rk.py search crossref "<対立する説明の語>" --question-ref Q1 --purpose counter
   ```
   件数は DB が返した値だけを記録する(不明なら null)。候補の一覧は .ryukoku/cache/ に置かれ、次の検索・SessionStart・rk check のたびに 24 時間より古いものが消される(J-STAGE 規約 第3条5項)。
4. 読む候補を選んだら理由を記録する: `python3 tools/rk/rk.py searchlog annotate S003 --selected "doi:10.…" --reason "Q1 の時期に関わる"`。自動記録(WebSearch など)にも `--question-ref` と理由を補う。学生は証拠ノートの「問いと調査」で記録を確かめられる。
5. 選んだものを台帳に入れて機械で確かめる: `python3 tools/rk/rk.py ledger add-source --doi …(または --ncid / --ndl-id / --crid と --title --authors --year)`、`python3 tools/rk/rk.py refcheck check --id S00x`
6. IDENTITY_CONFIRMED になったものだけを「読む候補」として `research-report` にまとめる。RETRACTED は「引用しない」一覧へ。
7. 学生には、図書館の紙の資料・相互貸借も探すよう一言添える。

## してはいけないこと
記憶から書誌情報を出す、件数を推測で書く、学生の問いにない調査を始める、候補から結論を導く、API の生の応答を Git に入れる。
