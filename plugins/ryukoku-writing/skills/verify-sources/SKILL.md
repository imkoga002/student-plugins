---
name: verify-sources
description: "文献の実在確認(識別子 → 解決 → メタデータ照合 → 撤回の確認)と、主張の台帳の扱い。原稿に引く文献は IDENTITY_CONFIRMED 以上。「この文献は本物？」「DOI を確認」「出典の検証」「VERIFIED にして」「verify my sources」「check this citation」などで使う。VERIFIED は学生が原典を読み、合言葉で署名して付ける。"
---

# 出典の検証

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
生成 AI は実在しない文献をもっともらしく出すことが実証研究で確かめられている(例: Walters & Wilder 2023, Scientific Reports 13:14045, DOI 10.1038/s41598-023-41032-5)。だから記憶から書誌情報を出さず、識別子で解決し、メタデータを照合する。それでも「原典が主張を支えるか」は機械には分からないので、VERIFIED は学生が原典を読み、合言葉で署名して付ける。台帳に直接 VERIFIED と書いても、署名がなければ `rk check` と CI が落とす。

## 状態
- 機械(AI の道具が付ける): IDENTITY_CONFIRMED(識別子が解決し、題名・著者・年が一致)/ NOT_FOUND / METADATA_MISMATCH / RETRACTED / CANDIDATE(照合する項目が足りない・未確認)。通信の失敗は状態を付けない
- 人間(学生だけが付ける): 文献 VERIFIED / REJECTED、主張 VERIFIED / CONTRADICTED / NOT_FOUND。VERIFIED は原典を読んだという宣言なので合言葉の署名、それ以外は画面か端末の確認
- 原稿に引用する文献は、台帳で IDENTITY_CONFIRMED 以上であること。台帳にない・それ未満のものを引くと、提出の段階の検査が通らない(下書きの段階では注意)。識別子の無い資料(古い本など)は、NCID・NDL ID などの識別子を台帳に足して確かめる。それでも確かめられない資料は、提出の段階では引けない。書き出し(export)も同じ規則で止まる。front matter の nocite(`@*` は references.json のすべて)も対象。引用キーは pandoc の規則で読む(`[@山田2020]` のような漢字・かなのキーも)
- 文献一覧は `sources/references.json` だけから作る。その項目(DOI・ISBN・題名・年・著者)は台帳の記録と同じでなければならない(違えば提出の検査と書き出しのエラー)。references.json を書くときは、台帳の記録をそのまま写し、記憶から補わない
- 題名なし、題名の一語だけ、ISBN のチェックディジットだけ、では IDENTITY_CONFIRMED にならない

## 手順
1. 台帳に入れる: `python3 tools/rk/rk.py ledger add-source --doi 10.… --title "…" --authors "姓, 名; 姓, 名" --year 2023`(日本の図書は `--ncid` か `--ndl-id`、CiNii Research は `--crid`)
2. 機械の確認: `python3 tools/rk/rk.py refcheck check --id S001`
   - DOI: doi.org → Crossref → (なければ)DataCite。撤回は Crossref の updated-by(この論文が撤回された)と update-to(この DOI 自体が撤回通知)
   - NCID: CiNii Books / CRID: CiNii Research(appid が要る)/ NDL ID: NDL サーチ(逐次)
   - CiNii・NDL・DataCite には撤回の情報がない。「撤回されていない」とは言わず「未確認」と伝える
   - ISBN-10 の検査は実装していない(算法を一次資料で確かめていない)
3. 主張を台帳に入れる: `python3 tools/rk/rk.py ledger add-claim --claim "<学生が書いた主張の文>" --source-id S001`。`--locator`(頁・節)は AI が入れない。頁は学生が原典を開いて確かめ、自分の端末の `./rk verify` で入れる(AI が頁を書くと、頁の捏造や読み違いがそのまま台帳に入るため)
4. 学生に案内する: 「原典の該当箇所を読んだら、証拠ノートの『文献と主張』で項目を表示して判断を選ぶ。VERIFIED は合言葉で署名する(端末なら `./rk verify`)」
5. 原典が主張と矛盾したら、主張を原典に合わせて直すことを提案する(逆は禁止)。直すのは学生。

## 推薦するとき
IDENTITY_CONFIRMED のものだけを「読む候補」にする(`resource-recommendation`)。読んでいないものを引用させない。
