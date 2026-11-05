---
name: review-comments
description: "レビューコメント(review/annotations.json)と、指導教員の Word のコメントに応答する。「コメントに答えて」「レビューを見て」「指摘への対応」「論証をレビューして」「Word のコメントを取り込みたい」「respond to review comments」「review my argument」などで使う。コメントは基準と問いと確かめ方にし、修正案は検証のファイルに分けて出す。学生の主張は変えない。解決は学生が記録する。"
---

# レビューコメント

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答・問い・説明を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
コメントは、満たしていない基準と、学生が自分で考えるための問い 1〜2 個にする(効くのは、誤りとその理由を示し、探索の方向を与えるフィードバック: Wisniewski, Zierer & Hattie 2020, Frontiers in Psychology 10:3087, DOI 10.3389/fpsyg.2019.03087)。修正案や書き直し案を出してもよいが、コメントに混ぜると学生が基準を考える前に案を写しがちなので、`claim-verification` の検証のファイル(`review/verification/` の 6 節)に分けて書く。案は学生の主張どおりに限る(COPE の査読指針も、著者の論文を自分の好む書き方に変えようとしないことを求める: COPE Ethical Guidelines for Peer Reviewers 2013, DOI 10.24318/cope.2019.1.9)。科目が許すなら、学生が採った案を AI が原稿に入れてよい(`draft-writer`。由来に記録される)。用語は「根拠 = data、論拠 = warrant」で固定する。

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
4. 解決は学生が付ける: 証拠ノートの「レビュー」でコメントを表示して「解決」を記録する(合言葉は要らない。端末なら `./rk resolve`)。AI の道具には解決の操作がない。

## 「直した文を見せて」と言われたら
科目の AI 利用条件を見る。prohibited なら書き直しの文は出さず、基準と問いだけにする。それ以外なら、`claim-verification` の 6 節に修正案を書いてよい。案ごとに、どの指摘に答えるかと、主張カードのどの主張どおりかを添え、主張の強さ・範囲・向きは変えない。主張そのものを変えたほうがよいと思うなら、案ではなく学生への問いにする。

## Word のコメント(指導教員が docx に赤入れした場合)
- 一覧だけ見る: `python3 tools/rk/rk.py docx-comments <file>.docx`(pandoc の --track-changes=all で読む)
- 取り込みは学生が端末で: `./rk import-docx <file>.docx --doc manuscript/<file>.md`(端末での確認。T0 コメント・T1 変更履歴として指導教員の名で入る)
- 変更履歴は原稿に反映しない。学生が読んで自分で直す

## してはいけないこと
学生の主張を別の主張に変える案、材料にない文献・数字を足す案、解決の印、学生の代わりの判断。
