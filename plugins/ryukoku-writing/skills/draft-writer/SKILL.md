---
name: draft-writer
description: "科目の AI 利用条件が許すとき、学生が確認した主張カード・論証図・台帳の文献・保存したデータだけを材料に、節の原稿を書く・直す。書いた段落の由来は自動で記録され、直後に検証(すり替えと根拠の対応)が回る。「この節を書いて」「下書きを作って」「文章にして」「続きを書いて」「この段落を直して」「draft this section」「turn my notes into prose」などで使う。材料にない主張・数字・文献は足さない。"
---

# 執筆の加速

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への説明を英語で書く(原稿は原稿の言語 `manuscript_lang` で書く)。

## なぜこの形か
原稿を AI が書くことそのものは悪いことではない。問題になるのは、学生の主張でないものが学生の主張として入ること、材料にない事実が入ること、それが隠れることである(ガイドラインⅢ-4)。だから材料を学生が確認したものに限り、書いた段落ごとに由来を記録し、書いた直後に検証する。科目の指示が優先する(Ⅲ-3)。

## 書く前に
1. 科目の条件(`.ryukoku/config.yml` の `ai_policy`):
   - `allowed`: 書いてよい
   - `limited`・`unknown`: 書く前に確認が出る。学生に、シラバスや教員の指示で AI の執筆が許されているかを確かめてもらう(許されていなければ書かない)
   - `prohibited`: 書かない。検証・調査・形式の確認はできると伝える
2. 材料を集める: 確認済みの主張カード(`python3 tools/rk/rk.py claims list` で confirmed のもの)、論証図(`review/argument-*.md`)、台帳の文献(`python3 tools/rk/rk.py ledger list`。IDENTITY_CONFIRMED のもの)、保存したデータ(`data/`)。draft のカードは材料にしない。学生に確認を頼む
3. 材料を記録する(書き込みの由来に入る):
   `python3 tools/rk/rk.py provenance materials --file manuscript/<file>.md --claims C001,C002 --sources S001 --data data/processed/<x>.csv --purpose draft`
   (直すときは `--purpose revise`、表記だけなら `--purpose format`、科目が許す翻訳なら `--purpose translate`)

## 書く
- Write か Edit で `manuscript/` に書く(シェルでは書かない。フックが止める)
- 主張は主張カードの主張・範囲・限定のとおりに書く。強めない、広げない、向きを変えない
- 事実の主張には台帳の文献を `[@citekey, p. 12]` の形で引く。頁は台帳か抜粋で確かめたものだけ
- 数字はデータの参照(脚注に `data/processed/<x>.csv` など)か引用をつける
- 材料にない主張・数字・文献を本文に足さない。足したほうがよいと思うものは、本文の外(学生への返答)に「追加の提案」として列挙する(何を、なぜ、どう確かめるか)

## 書いた後
- 書き込みの直後に、フックが由来を記録し(`.ryukoku/provenance.jsonl`)、機械の照合の結果を返す。学生に、書いた段落と結果を短く示す
- 致命・重要の候補があれば `claim-verification` で確かめる。主張カードと食い違っていたら、文を直すか学生に尋ねる(主張を文に合わせて変えない)
- 学生が書き直した部分は、学生の編集(推定)として記録される

## してはいけないこと
draft の主張カードを材料にする、RQ や主張を新しく作る、記憶からの文献・数字・頁、由来の記録を消す・書き換える。
