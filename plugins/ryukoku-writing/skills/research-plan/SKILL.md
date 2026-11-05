---
name: research-plan
description: "学生の問いから調査計画を立てる(何を知りたいか、どの資料の種類、どの DB、どの検索語、反証の探し方、紙の資料)。「先行研究を探したい」「文献調査の計画」「どこで探せば」「research plan」「literature search strategy」などで使う。調査の問いは学生が research/questions.md に書いた問いから導き、AI が問いを決めない。"
---

# 調査計画

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
調査の問いは学生の問いに由来しなければならない(ガイドラインⅢ-1)。AI が問いを作ると、調べる範囲そのものを AI が決めることになる。だから `research/questions.md`(学生だけが書ける。フックが AI の書き込みを止める)に問いがないうちは検索を始めない。検索の道具も、そこにない問いの番号では通信せずに止まる。AI で見つけた情報は学生自身が真偽を確かめ、ネットにない紙の資料も探す(Ⅲ-4)。

## 手順
1. `research/questions.md` を読む。問いが空なら `rq-dialogue` で学生に書いてもらう(AI は書かない)。
2. 問いごとに、学生と一緒に `research/plan.md` の表を埋める(AI も書けるが、候補は「この DB は検討したか」の形で示し、選ぶのは学生):
   - 日本語の論文: CiNii Research(appid が要る)、J-STAGE / 図書: CiNii Books、NDL サーチ / 学位論文: CiNii Research の dissertations
   - 英語: Crossref、DataCite(データセット)、OpenAlex(任意)
   - 龍谷大学図書館(詳しくは `resource-recommendation`): OPAC、R-OCEAN(CiNii Books・CiNii Research の一部・SciFinder は対象外なので別に検索)、データベース一覧、学外からは学認か図書館リモートアクセス、他大学図書館の利用(ILL)、レファレンス・メールレファレンス(学部生向け)
   - 紙の資料: 図書館の書架、相互貸借、レファレンス
   - 統計: e-Stat(appId とクレジット表記が要る)。RESAS-API は 2025-03-24 に終了しているので勧めない
   - 反証・対抗仮説を探す検索も計画に入れる(`--purpose counter` で記録され、`bias-check` が数える)
3. 検索語は日本語と英語の両方を学生と決める。統制語(NDLSH など)は学生が確かめる。
4. 次は `research-run`。

## 根拠
DB の条件は各提供元の頁による(2026-11-04 確認。変わることがあるので使う前に確かめる):
- appid: CiNii Research の OpenSearch https://support.nii.ac.jp/ja/cir/r_opensearch 、CiNii ウェブ API のデベロッパー登録 https://support.nii.ac.jp/ja/cinii/api/developer
- J-STAGE の保存の制限(第3条5項)とクレジット表記(第9条): J-STAGE WebAPI 利用規約 https://www.jstage.jst.go.jp/static/pages/WebAPI/-char/ja
- NDL サーチの同時接続の制限: 「API利用について」 https://ndlsearch.ndl.go.jp/help/api
- e-Stat の appId: https://www.e-stat.go.jp/api/ 。RESAS-API の終了: https://opendata.resas-portal.go.jp/docs/api/v1/index.html
- 龍谷大学の提供一覧: 図書館のデータベース一覧 https://opac.ryukoku.ac.jp/iwjs0005opc/ermssrh.do?words=
