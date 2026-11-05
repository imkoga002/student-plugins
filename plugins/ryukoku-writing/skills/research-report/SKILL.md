---
name: research-report
description: "調査の結果を、出典つきの「証拠の一覧」にまとめる(調査報告)。「調査結果をまとめて」「何が見つかった」「research report」「summarise the evidence」などで使う。結論や主張は書かない。"
---

# 調査報告

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
調査結果は証拠の一覧であり、結論は学生が出す(ガイドラインⅢ-1)。報告に AI の結論や主張の文を入れると、学生の論証の材料を AI が選んで並べることになる。

## 形(research/reports/report-<日付>.md に置く。AI が書ける)
1. 調べた問い(学生の言葉のまま `research/questions.md` から引用し、番号を付ける)
2. 検索の記録(`python3 tools/rk/rk.py searchlog export` の表をそのまま貼る。反証の検索も含む)
3. 読む候補(IDENTITY_CONFIRMED のもの): 台帳 id、識別子のリンク(doi.org、CiNii の NCID・CRID、NDL のパーマリンク)、どの問いのどの部分に関係しうるか(一行。主張の形にしない)
4. 確認できなかったもの(CANDIDATE・NOT_FOUND・METADATA_MISMATCH)と、学生が確かめる方法(OPAC、NDL サーチの画面、図書館)
5. 引用しない一覧(RETRACTED と、撤回通知の DOI)
6. まだ探していない資料の種類(紙の資料、統計、反対の立場の資料。`bias-check` の観点)
7. 「この一覧は読む候補であり、読んで確かめた文献ではない。VERIFIED は原典を読んだ後に、証拠ノートか ./rk verify で自分で付ける」

## してはいけないこと
「〜と言える」「〜が明らかになった」などの結論、資料の内容を主張として要約すること(要約が要るなら、出典と該当箇所つきで、学生が原典を読む前提で)。
