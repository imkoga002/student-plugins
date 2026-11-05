---
name: review-comments
description: "レビューコメント(review/annotations.json)と、指導教員の Word のコメントに応答する。「コメントに答えて」「レビューを見て」「指摘への対応」「論証をレビューして」「Word のコメントを取り込みたい」「respond to review comments」「review my argument」などで使う。AI は基準と問いと確かめ方だけを返し、書き換えの文も修正例も書かない。解決は学生が署名して付ける。"
---

# レビューコメント

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答・問い・説明を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
論証の欠陥への応答で修正例を示すと、論拠や本文を AI が書くことになる(ガイドラインⅢ-4)。示すのは、満たしていない基準と、学生が自分で考えるための問い 1〜2 個である(効くのは、誤りとその理由を示し、探索の方向を与えるフィードバック: Wisniewski, Zierer & Hattie 2020, Frontiers in Psychology 10:3087, DOI 10.3389/fpsyg.2019.03087。COPE の査読指針も「著者の論文であって、自分の好む書き方に書き直そうとしない」: COPE Ethical Guidelines for Peer Reviewers 2013, DOI 10.24318/cope.2019.1.9)。用語は「根拠 = data、論拠 = warrant」で固定する。

## 手順
1. 一覧: `python3 tools/rk/rk.py annot list --open`
2. 各コメントに返信(kind は question / howto / note。道具がこれ以外を受け付けない):
   - question: 問いで終える(「？」)。基準を名指しする。例の形: 「W2(論拠の裏づけ): この前提は、どの理論・先行研究に支えられていますか？」
   - howto: 確かめ方(どの資料のどこを見るか、どのコマンドで確認するか)
   - note: 事実の補足(出典つき)
   `python3 tools/rk/rk.py annot reply <id> --kind question --text "…？"`
3. 新しい指摘を置くとき(機械の検出は常に「要確認」になる):
   `python3 tools/rk/rk.py annot flag --doc manuscript/<file>.md --quote "<原稿の逐語>" --code W1 --comment "…？"`
   コードは 7 層(主張 C・定義 D・根拠 G・論拠 W・一般化と因果 I・弁証 R・構成 O)。誤謬名は判定ではなく問いのきっかけにする。
4. 解決は学生が付ける: 証拠ノートの「レビュー」でコメントを表示して「解決」を選び、合言葉で署名する(端末なら `./rk resolve`)。AI の道具には解決の操作がない。

## 「例文を出して」「直した文を見せて」と言われたら
断り方の例: 「この節の文は、あなたの言葉で書くものなので、例文は出しません(ガイドラインⅢ-4)。代わりに、W1(論理の飛躍)の観点で一つ聞きます: 根拠からこの主張へ進むのに、どんな前提が必要ですか？」。表記の見本が要るときだけ、学生の内容を含まない記号の見本(「X は Y である。」)を示してよい。

## Word のコメント(指導教員が docx に赤入れした場合)
- 一覧だけ見る: `python3 tools/rk/rk.py docx-comments <file>.docx`(pandoc の --track-changes=all で読む)
- 取り込みは学生が端末で: `./rk import-docx <file>.docx --doc manuscript/<file>.md`(合言葉で署名。T0 コメント・T1 変更履歴として指導教員の名で入る)
- 変更履歴は原稿に反映しない。学生が読んで自分で直す

## してはいけないこと
書き換え案・修正例・「次のように書く」、論拠や反論の文の提供、解決の印、学生の代わりの判断。
