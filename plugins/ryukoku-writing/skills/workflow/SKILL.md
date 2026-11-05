---
name: workflow
description: "執筆の進め方: Git を使わない最小の経路と、Git・GitHub を使う場合(節ごとのブランチ → PR → CI → 人間のレビュー → マージ)。指導教員への受け渡し(HANDOFF)。「Git の使い方」「GitHub で管理したい」「Git を使わずにやりたい」「PR を作りたい」「指導教員に渡したい」「version control for my thesis」「I don't use git」などで使う。"
---

# 進め方(Git あり / なし)

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## どちらでも同じもの
人間の判断の記録(.ryukoku/signoffs.jsonl。VERIFIED と最終確認は署名、ほかは確認)、主張カード、由来の記録、台帳、検索記録、AI 利用記録、`./rk check` は、Git がなくても同じに動く。Git は履歴と共有を足すもので、人間のレビューの仕組みそのものではない。

## Git を使わない場合(最小の経路)
1. 考えを AI に話して主張カードにし、画面で確認する。原稿は自分で書くか、科目が許せば AI に下書きを頼む(由来が記録される)
2. AI に調査・検証・レビューを頼む → 証拠ノート(画面)で一件ずつ確かめて記録する(VERIFIED だけ合言葉)
3. 指導教員に渡すとき: `python3 tools/rk/rk.py bundle` で HANDOFF.md を作る。署名者の指紋・登録日・数と検査の結果が載るので、指導教員は初回の面談で控えた指紋と照らす(別の PC で開くときは、そこで `./rk trust`)。docx は `export-submission`。返ってきた Word のコメントは `./rk import-docx`
4. 区切りごとにフォルダを日付つきでコピーしておく(手動の版管理)
5. 提出前に証拠ノートの「提出前」か `./rk signoff`

## Git と GitHub を使う場合
1. `./rk setup` で Git を選ぶと、main に最初の commit を作る(合言葉を登録していれば署名者の公開鍵を含み、CI はそれを信頼の起点にする。後で登録したら、signers.json を main で commit して自分の端末から push する)。また commit と push の前に `./rk check` を走らせるフックを有効にする
2. 節ごとにブランチを作る(例: `git switch -c section/2-1`)。コミットと push は学生が行う
3. PR を作ると、PR テンプレートのチェックリストと CI(`.github/workflows/check.yml`)が動く。CI は **基準ブランチの道具** で PR を検査する: 署名者は基準ブランチのものだけを信頼し、変更された節には現在の内容を読んだ確認(キー一つ)を求め、AI 利用記録・由来の記録・判断の記録が消されていないこと、検知した変更が判断済みであること、科目が禁止なのに AI が書いた段落がないこと、tools/ や CI の設定が PR の中で変わっていないことを確かめる
4. 指導教員やゼミ仲間にレビューを頼む。指摘は「箇所 / コード / 観点 / 問い」の形で
5. 非公開リポジトリのブランチ保護と CODEOWNERS の強制は GitHub Pro 以上が必要(GitHub Docs「About protected branches」https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches 、「About code owners」https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)。ローカルのフック、PR のチェックリスト、CI の検査で補う
6. Plugin を更新したときは、main で `./rk update-tools` を実行して commit する(PR に混ぜない)

## AI がしないこと
main への push、強制 push、`--no-verify`、PR の承認やマージ、署名と確認。push とコミットは学生が自分で行う。
