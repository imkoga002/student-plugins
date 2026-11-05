---
name: resource-recommendation
description: "研究に役立つ資源(論文・本・記事・データ・図書館のサービス)の推薦。「何を読めばいい」「おすすめの資料」「龍谷大学の図書館で使える DB は」「どこで本を借りられる」「recommend sources」「what databases can I use」などで使う。推薦は実在確認を経たものだけを「読む候補」にし、学生の主張は作らない。"
---

# 資源の推薦

講評言語(`.ryukoku/config.yml` の `feedback_lang`)が `en` のときは、学生への応答を英語で書く(この指示文は日本語のままでよい)。

## なぜこの形か
推薦は「読む候補」であり、読んでいないものを引用させない。実在しない文献を推薦しないよう、IDENTITY_CONFIRMED を経たものだけを候補にする。推薦の理由は「学生の問いのどの部分に関係しうるか」までにとどめ、その資料で学生の主張を作らない。

## 文献
- 候補は台帳の IDENTITY_CONFIRMED のものだけ(`verify-sources`)。RETRACTED と撤回通知は別の「引用しない」一覧に置く。
- 理由は一行: どの問い(research/questions.md の番号)のどの部分に関係しうるか。主張の形にしない。

## 龍谷大学図書館(図書館の各頁を 2026-11-04 に確認。変わることがあるので図書館の頁で確かめる)
- 蔵書検索(OPAC): https://opac.ryukoku.ac.jp/iwjs0005opc/cattab.do 。MyLibrary から ILL の複写・貸借の依頼もできる
- R-OCEAN(ディスカバリーサービス): 広く一度に探す。CiNii Books・CiNii Research の一部・SciFinder は対象外なので別に検索する: https://library.ryukoku.ac.jp/Search/page_id72
- データベース一覧(2026-11-04 時点で 247 件。https://opac.ryukoku.ac.jp/iwjs0005opc/ermssrh.do?words= ): 例として CiNii Research、JDream III、日経テレコン21、朝日新聞クロスサーチ、ヨミダス歴史館、マイサク、D1-Law.com 判例体系、TKCローライブラリー、Lexis、JSTOR、Web of Science、JapanKnowledge Lib、e-Stat、国立国会図書館デジタルコレクション、IRDB
- 一覧にないもの(龍谷大学の資源として案内しない): Scopus、Westlaw、PsycINFO、判例秘書、日経NEEDS
- 学外から: 学認(GakuNin。すべての DB が対象ではない)か図書館リモートアクセス(VPN 接続): https://library.ryukoku.ac.jp/page_id90
- 他大学図書館の利用(紹介状による閲覧、複写、貸借): https://library.ryukoku.ac.jp/Service/page_id51
- レファレンス(カウンター)とメールレファレンス(学部生・短期大学部生が対象。所蔵調査・資料の識別・テーマの文献紹介): https://library.ryukoku.ac.jp/Service/page_id57 ・ https://library.ryukoku.ac.jp/Service/page_id58
- 紙の資料: 書架、相互貸借、レファレンスを必ず一言添える(ガイドラインⅢ-4: ネット上にない紙の資料も探す)

## 書くことの相談
ライティングサポートセンター(大学院生のチューターが、レポートや卒論の書き方の相談に応じる。答えを教えたり押しつけたりしない方針): https://www.ryukoku.ac.jp/writingsupport/about/ 。この Plugin はセンターの代わりではない。

## してはいけないこと
記憶からの書誌情報、龍谷大学が提供していない DB を龍谷大学の資源として案内すること、存在しないサービス名、推薦の理由を主張の文にすること。
