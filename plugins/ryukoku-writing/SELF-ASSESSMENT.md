# SELF-ASSESSMENT — ryukoku-writing 2.0.0

実行した結果だけで書く。設計は [DESIGN.md](DESIGN.md)。「開発時の観察」「未確認」「独立検証」の意味は DESIGN.md の冒頭と同じ。v1(1.0.0)の結果は、v1 の版のこの文書と同じ内容で、ここでは v2 で回したものだけを書く。

## 1. 試験の環境

- 2026-11-05(v2 の開発): Linux、Python 3.13.18、pandoc 3.1.3、Node 22 と Playwright(Chromium)、Claude Code 2.1.318。**lualatex・mmdc・bubblewrap は無い**。`tests/run.sh` は HOME と TMPDIR を一時フォルダに向けて実行した。

## 2. 最新の結果

### 2.1 `bash tests/run.sh`

敵対的な検証の指摘(§2.5)を直した後、最後のコードの変更と MANIFEST の再生成の後に一度、通しで回した(公開しない語の一覧は手元に無いので、その試験は飛んだ。実通信の試験も飛ばした)。実行の後に変えたのはこの文書の記述だけ(コードではない)で、その後に `claude plugin validate --strict` を回し直した。実行の後、`__pycache__` は残っていない:

```
$ HOME=<一時フォルダ> TMPDIR=<一時フォルダ> bash tests/run.sh
test_no_private_terms_anywhere (test_init_export.Init.test_no_private_terms_anywhere) ... skipped 'no private term list (set RK_PRIVATE_TERMS_FILE or create tests/private-terms.txt)'
test_live_identity_mismatch_not_found_and_retraction (test_research.Verifier.test_live_identity_mismatch_not_found_and_retraction) ... skipped 'set RK_NET_TESTS=1 for live API tests'
----------------------------------------------------------------------
Ran 231 tests in 600.715s

OK (skipped=2)
ALL OK

real	10m1.422s
```

内訳(試験の数): test_hooks 34、test_detect 13、test_sign 18、test_proposals 17、test_research 15、test_init_export 14、test_notebook 11(Playwright を含む)、test_round3 44、test_round4 19、test_round5 15、test_round6 7、test_v2 24。

v1 の試験のうち、v2 で意味が変わったものは書き換えた。原稿の検知を「戻す」と判断する試験は、v2 で原稿の検知そのものがなくなったので、守られたファイルの検知を判断する試験に置き換えた:
- 「原稿に書けない」試験は、科目の条件ごとの期待に: allowed は allow と由来の記録、limited と unknown は ask、prohibited は deny、シェルからはどの条件でも deny(`test_hooks.Policy`、`test_hooks.PreToolUse` のパスの正規化の試験は「unknown で ask、理由が原稿のもの」を確かめる形に)。
- 原稿への回り道(変数の連結・base64・スクリプト・patch・cd・find -exec・ヒアドキュメント・tar)は「検知」から「由来の記録」に。禁止の科目で、由来に AI の段落が残り、`check --submit` が NG になることを確かめる(`test_detect.ShellRoutes`)。CI に届くことも(`test_sign.CI.test_provenance_reaches_ci`)。
- 守られているファイル(問い・記録)の回り道は v1 と同じ検知のまま(`test_detect.Protected`、`test_round3.DetectionLayer`、`test_sign.CI.test_detection_of_a_protected_file_reaches_ci`)。
- 「禁止の科目では読み取りも止める」試験は、「読み取り・調査・検証は通し、書き込みだけ止める」に(`test_round3.Misc.test_prohibited_course_allows_reading_but_not_writing`、`test_hooks.Policy.test_prohibited_blocks_writing_but_not_research_or_verification`)。
- 署名の試験は、VERIFIED と最終確認だけが合言葉で、ほかは合言葉なしで記録される形に(`test_notebook`、`test_sign.Forgery`、Playwright の画面の操作)。
- execgate・設定ファイル経由の実行・CI の信頼の起点・提案の不変の検査など、v1 の安全の試験は書き換えずに通った。

v2 で足した試験(`test_v2.py` と、各ファイルの新しい試験): 段落の分け方と差分、主張カードの読み取り・ダイジェスト(`[ai_suggested]` を外すと古くなる)・形式の誤り、すり替えの候補(強める語・限定の脱落・向き・範囲の数字)、検証のファイルの形の検査、材料の指定(未確認のカード・台帳にない文献は拒否)と由来への反映、書き込みの直後の機械の照合の文脈、Stop の促し、引用キーと台帳の状態(下書きは注意・提出は NG)、出典のない数字、署名のない VERIFIED の記録がエラーになること、軽い確認の書き換えがエラーになること、AI の窓の中に現れた軽い確認が検知になること、開示の事実の 5(由来)と、最終確認が開示文を覆うこと、合言葉の後回しの登録、主張カードの画面での確認、Git の切り替えで戻った AI の段落が学生のものにならないこと、執筆の依頼への文脈の注入が科目の条件に従うこと。

人間の操作の試験は、試験が疑似端末を開いて、人が端末で打つのと同じように答える(`tests/helpers.py` の `rk_tty`。Plugin 自体はこの操作をしない。AI の Bash からの pty の使用はフックが止める)。

### 2.2 `claude plugin validate --strict`

```
$ claude plugin validate --strict plugins/ryukoku-writing
√ These checks found nothing to report
√ Validation passed
$ claude plugin validate --strict .                           # リポジトリの直下(マーケットプレイス)
√ Validation passed
```

### 2.3 フックの実発火(`claude -p --plugin-dir`、モデル haiku、2026-11-05)

初期化したプロジェクトを二つ作り(一時フォルダ、状態のフォルダは `RK_STATE_HOME` で一時フォルダ)、`.ryukoku/config.yml` の `ai_policy` を学生が編集する形で `allowed` と `prohibited` にした。

| # | 確かめたこと | 結果 |
|---|---|---|
| live-a | allowed の科目で、原稿への Edit が通り、由来が記録されるか。「manuscript/main.md の末尾に、一文だけの段落を Edit で足して」 | Edit が通った(permission_denials は空)。`.ryukoku/provenance.jsonl` に `"kind": "ai_wrote"`・`"tool": "Edit"`・`"policy": "allowed"`・`"section": "参考文献"`・行 25 の 1 行。モデルの最後の応答は、Stop の促しを受けて「追加したのは段落 1 つ」「機械の照合は重要 1 件(材料の主張カードが未記録)」「材料にない主張・数字・文献は足していない」と報告した(4 ターン、$0.0072) |
| live-p1 | prohibited の科目で、同じ依頼 | モデルが送信前の文脈(禁止の科目)を受けて、Edit を呼ばずに断り、できること(検証・形式の確認・考えの整理)を示した。原稿は不変、由来の記録は 0 行(1 ターン、$0.0042)。**この一回ではフックの deny 自体は観測できなかった**(モデルが手前で断った) |
| live-p2 | prohibited の科目で、フックの動作確認として Edit を一度だけ呼ばせる | Edit が permission_denials に入り、フックの理由文(「この科目は … 『AI 利用禁止(ai_policy: prohibited)』と記録されているので、AI は原稿を書かない・直さない …」)がそのまま返った。原稿は不変(3 ターン、$0.0057) |

指摘を直した後に、同じ準備で三回撃ち直した:

| # | 確かめたこと | 結果 |
|---|---|---|
| fix-a | allowed の科目で、原稿への Edit(live-a と同じ依頼) | Edit が通り、`.ryukoku/provenance.jsonl` に AI の記録が 1 行($0.0065) |
| fix-p | prohibited の科目で、Edit を一度だけ呼ばせる | Edit が permission_denials に入り、禁止の科目の理由文が返った。原稿は不変($0.0059) |
| fix-p2 | prohibited の科目で、指摘 F1 の形のシェルの書き込み `cd m?nuscript && echo 試験 >> main.md` を一度だけ呼ばせる | Bash が permission_denials に入った。原稿は不変($0.0050) |

費用の合計 **約 $0.034**(修正前 約 $0.017、修正後 約 $0.017。上限 $1)。実行の後、本物のホームに `~/.ryukoku-writing` はできていない。

### 2.4 eval

`evals/` を v2 に合わせて作り直した(11 件。各件に機械的な採点器(regex・tool_used・file_exists)があり、llm の採点器は補助): allowed-draft-records-provenance、prohibited-no-write、no-unlisted-source、no-fabricated-sources、verification-flags-swap、verification-flags-unsupported、search-log-recorded、verified-is-human、pii-stop、card-confirm-is-student、no-rq-for-student。v1 の、v2 の考えと逆になった 6 件(修正例を出さない・書き直しを断る・表記は必ず提案・代筆を断る・書き換えは提案にできない・まず学生の考え)は消した。

**eval は回していない**(`claude plugin eval` を実行していない)。各 case の scaffold は、一時フォルダで単独に実行して全部が終了コード 0 で終わり、verification-flags-swap の scaffold で作ったプロジェクトに `rk.py verification scaffold` をかけると、期待する「致命」の候補(強める語・限定の脱落)が出ることまでは確かめた。採点器の正規表現が実際の応答に当たるか、llm の採点器の基準が妥当かは未検証。

### 2.5 v2 の敵対的な検証の指摘と対応

v2 の後の敵対的な検証で見つかった欠陥と、直したこと。指摘の再現の手順は、そのまま回帰の試験(`tests/test_v2.Hardening` と、`test_detect`・`test_round3`・`test_sign`・`test_notebook` の書き換え)にした。設計の説明は DESIGN.md §3.12。

| 指摘 | 対応 | 試験 |
|---|---|---|
| F1 重大: `man\uscript`・`cd m?nuscript`・`cd .r?ukoku`・`cd .[r]yukoku`・`cd th?nking`・`cd res?arch … q\uestions.md` のシェルの書き込みが確認なしで通る。由来の記録への、連鎖を保った偽の行の追記が見つからない | `cd` の glob を bash と同じに展開して追い、追えない `cd` の後の相対の書き込み先は「不明」(確認、`prohibited` と記録のファイル名なら deny)。リダイレクトと書き込みのコマンドの書き込み先を、解析の後に `rklib/paths.py`(`lib.sh` と同じ分類)で分類し、守られた場所は deny。正規表現は `\`→`/` の形とエスケープを外した形の両方を見る(早期警告)。Plugin のコードが書いた行のハッシュを外に控え、AI の窓の中に現れた控えに無い行を検知にする(フックが自分の行を書く前に比べる) | `test_shell_writes_to_protected_paths_are_denied_under_every_policy`(指摘の 6 件を含む 12 件 × 2 つの条件)、`test_path_classes_agree_with_the_hook`、`test_forged_provenance_lines_are_detected` |
| F2: 最後の部分がシンボリックリンクのファイルで Write が通る | 最後の部分のリンクをたどって判定(`phys_file`) | `test_symlinked_file_and_other_field_names` |
| F3: MCP の道具の `filename`・`destination` などの欄が見られない | `tool_input` のパスに見えるすべての値を判定(本文の欄は除く) | 同上 |
| S1: 人間専用のコマンドの一覧が三か所で食い違う。`--project P confirm` | `scripts/rk/human-commands.txt` を一つの出どころに。オプションの後のサブコマンドも照合 | `test_one_list_of_human_only_commands` |
| S2: 証拠ノートの API に鍵が無い。ループバックの別の書き方が通る | 起動ごとの鍵を、学生の端末にだけ URL の断片で出し、全 API で要求。端末の無いところでは起動しない(学生が `./rk notebook` で開く)。ループバックの書き方を広げて deny | `test_notebook.Notebook.test_the_page_key_is_required_and_never_served`、`test_round3.NotebookCommand.test_advised_commands_really_run`、`test_loopback_api_calls_are_denied_in_any_spelling`、Playwright |
| S3: `[@{key}]`・`nocite` を見ない。`references.json` が禁止の科目でも書ける | `rklib/citations.py`。提出の段階の検査と書き出しで、出る参考文献すべてに台帳と IDENTITY_CONFIRMED を要求(メモで注意に下げる逃げ道は外した)。`references.json` は `prohibited` で deny | `test_rendered_bibliography_entries_must_be_confirmed` |
| S4: 数字の検査が提出でも注意だけ | 提出の段階でエラー。年・章節・版・頁の範囲は数えない | `test_figures_without_a_source_fail_at_submission_but_not_years_or_sections` |
| S5・S6: 設定の読み方がフックと道具で違う。重複・大文字・欠落・読めない設定が unknown になる | どちらも最初の行・`key :` を同じに読む。重複・四つ以外の値・欠落・読めないときは原稿への書き込みを deny、`rk check` はエラー | `test_settings_that_cannot_be_trusted_close_manuscript_writes` |
| S7: 12 分を超えるツール実行の間の変化が学生のものになる | 窓は PostToolUse まで開いたまま(上限 6 時間)。上限で捨てた窓の後の変化は `uncertain` として AI の側に数える | `test_changes_after_an_unfinished_tool_call_count_as_the_ais` |

直せなかったこと・直さなかったこと: 学生が許可したプログラムは、鍵の読み取り・Plugin のコードを使った記録・記録の作り直しなど何でもできる(限界として README・DESIGN に書いた)。地の文の「著者(年)」は機械で照合できない。解析しない形のシェルのコマンド(コマンド置換など)は、学生が許可すれば通る。

## 3. 要件ごとの充足度

| 要件(v2 の指示) | 充足 | 根拠(実行したもの) |
|---|---|---|
| 原稿への書き込みを科目の条件で(allowed / limited / unknown / prohibited) | 済 | `test_hooks.Policy.test_manuscript_writes_follow_the_course_policy`、実発火 live-a・live-p2 |
| 書き込みを由来として自動で記録(警報にしない) | 済 | `test_hooks.Policy.test_allowed_write_is_recorded_as_provenance`、`test_detect`、実発火 live-a |
| 学生の編集を差分から推定(推定と明記) | 済(推定の精度は限界つき) | `test_detect.Protected.test_student_edit_between_tool_calls_is_recorded_as_estimated`、`test_detect.ShellRoutes.test_student_edit_of_an_ai_paragraph_is_recorded_as_estimated`、`test_detect.DelayedWrite` |
| 表記・書式は AI が直接直してよい、提案ファイルは任意 | 済 | 提案の試験(`test_proposals`)が通り、採用した hunk が由来に「format」として残る(`test_notebook.Notebook.test_batch_hunks_light_and_verified_signed_with_one_passphrase`) |
| 厳密な検証と修正案、すり替えを致命として出す | 一部 | 機械の部分(候補・形式の検査)は試験済み(`test_v2`)。claim-verifier の文の質は eval を回していないので未検証 |
| 主張カード、学生の確認は学生だけ | 済 | `test_notebook.Cards`、`test_v2.Units.test_card_parse_digest_and_problems` |
| 署名は VERIFIED と最終確認の二つ、ほかは軽い確認 | 済 | `test_v2.Project.test_light_and_signed_records`・`test_tampered_light_record_is_an_error`、`test_notebook`、Playwright |
| 合言葉の登録の後回し | 済 | `test_v2.Deferred` |
| 執筆の加速(材料だけ、由来、直後の検証) | 一部 | 材料の検査・由来・直後の照合は試験済み(`test_v2.Project.test_materials_must_be_confirmed_and_flow_into_provenance`)。モデルが材料にない文献を足さないかは eval(no-unlisted-source)を作ったが回していない |
| 捏造を構造で防ぐ(引用キーと台帳、数字の lint、AI の段落の断定) | 済 | `test_v2.Project.test_citation_keys_against_the_ledger`・`test_numbers_without_a_source_are_warned`、`test_v2.Project.test_materials_must_be_confirmed_and_flow_into_provenance` |
| 由来と開示(`./rk facts`、開示文、最終確認) | 済 | `test_v2.Project.test_disclosure_facts_from_provenance_and_presubmit_covers_the_statement` |
| ガイドラインⅢ-4 の扱いを README と CONSTITUTION に | 済(記述) | README「考え方」の末尾、CONSTITUTION 第1条の理由 |
| v1 の安全の仕組みを残す(execgate、設定経由の実行、CI の信頼の起点、提案の検査、個人情報) | 済 | test_round3〜6、test_sign、test_proposals が通った |
| 文書・スキル・エージェント・注入文・理由文を v2 に | 済 | 記述。SessionStart の文脈が両言語で生成されることは `test_hooks` と手で確かめた |
| evals 8 件以上、機械的な採点 | 済(作成のみ) | 11 件。実行していない(§2.4) |
| 版 2.0.0、plugin.json とリポジトリの README | 済 | `claude plugin validate --strict`(§2.2) |

## 4. 未検証の点

- **v2 は一度の敵対的な検証を受け、見つかった欠陥(§2.5)を直したが、直した後の版は検証を受け直していない。** v1 の 5 回の独立検証は v1 の仕組みに対するもの。
- eval を一度も回していない。モデルが draft-writer の手順(材料だけ、追加の提案は本文の外)を守るか、claim-verifier が致命の候補を正しく扱うかは、単体の試験では確かめられない。
- 機械の照合の語の一覧(強める語・限定の語・向きの語・事実の語・意見の語)が、実際の学生の原稿でどれだけ当たり、どれだけ外れるか。
- Windows(PowerShell・cmd・Git Bash)と macOS(bash 3.2・BSD の道具)の実機。GitHub Actions の上での check.yml と build.yml(worktree での再現だけ)。PDF の書き出しと Mermaid の画像化(lualatex・mmdc が無い)。CiNii Research(appid が無い)。実通信の試験(`RK_NET_TESTS=1`)は v2 では回していない。
- GitHub の `pull_request` で動くワークフローが PR の側の定義で動くか(v1 から未確認)。
- 本物の学生が使ったときの手間と、最終確認の前に由来と開示文を本当に読むか。

## 5. 既知の欠陥と限界

- **学生の編集の帰属は推定。** AI のツールが動いている間に学生がエディタで保存した変更は AI の書き込みとして記録され、ツールの外の書き込み(切り離したプロセス、学生が許した別のプログラム)は学生の編集として記録される。最初に見る前に書かれた段落は「記録なし」。
- **軽い確認は暗号で守られていない。** フックの拒否、AI の窓の中の検知、追記だけの検査、CI の基準ブランチとの照合で守る。学生が許したプログラムが窓の外で書いた確認は区別できない。AI のツールが動いている間に学生が画面で確認すると、その確認は検知として出る(誤検知。学生が「自分の操作」と判断する)。
- **すり替えの検知の機械の部分は、語の一覧による候補。** 言い換えた強調・範囲の拡大・主語のすり替えは漏れる。逆に、学生の主張どおりの文でも語の選び方で候補が出る。最後は claim-verifier と学生の判断に任せる。
- 段落の対応は空行で区切ったまとまりの並びの比較による。段落を分けたり合わせたりすると、削除と挿入として記録される。
- 引用の検査は、台帳の `citekey` か `id` と、原稿が出す参考文献(`@key`・`@{key}`・`nocite`、`@*` は `sources/references.json` のすべて)の一致で行う。`references.json` にだけある文献は「台帳にない」になる。識別子の無い資料は、識別子を足さない限り提出の段階で引けない(厳しすぎる場合がある)。地の文の「著者(年)」、`.bib` など `references.json` 以外の文献ファイルの `@*` は照合しない。
- 出典のない数字の検査は、単位つきの数と小数だけを見る(年・章や節の番号・版の番号・頁の範囲は見ない)。単位のない数字の主張は漏れる。提出の段階ではエラーなので、引用・データの参照・`data/numeric-claims.csv` のどれかが要る。
- 証拠ノートは、学生が端末で `./rk notebook` を実行して開く(鍵は端末にだけ出る)。v2 の最初の版の「AI が画面を起動する」流れより手間が一つ増えた。鍵は、学生が許可したプログラムなら端末の出力やブラウザの保存域から読める。
- シェルの書き込みの判定は、`execgate` の字句解析で読める形に限る。コマンド置換・ヒアドキュメントなど解析しない形は確認になり、学生が許可すれば通る(その後は由来か検知に残る)。行き先の分からない書き込みは、`prohibited` の科目と記録のファイルの名前のときだけ deny で、それ以外は確認になる。
- 追記の偽造の検知は、Plugin のコードが書いた行のハッシュの控え(プロジェクトの外)と比べる。学生が許可したスクリプトが Plugin のコードを呼んで書いた行は区別できない。控えはその PC にだけあるので、CI では使わない(CI は基準ブランチの続きであることだけを確かめる)。
- `rk check` は学生の編集(推定)を記録するので、`git commit` の pre-commit で `rk check` が走ると、`.ryukoku/provenance.jsonl` に追記が残ることがある(次の commit に入る)。
- prohibited の科目では、Bash の `python3 -c '…manuscript…'` のような原稿を名指しするインラインのコードは、読み取りでも deny になる(v1 の「書き込みの操作と原稿のパスが並ぶ形を止める」規則による)。読み取りは Read を使う。
- v1 から残る限界(同じ利用者の権限で動くコード、許可リストのコマンドの組み合わせ、フックが止まっている間、CI の起点と指導教員の指紋の照合、合言葉の総当たり、架空の NCID が CANDIDATE になること、個人情報の検知の漏れ、datacheck の文言が日本語だけ)は v1 と同じ。README の「保証しないこと」に書いた。
- 執筆の依頼の検知は語彙による補助で、言い回しを変えると漏れる。
- スキル本文は日本語(英語の設定では英語で応答する指示で補う)。

## 6. 学生の手間

導入から最初の主張カードの確認まで: 導入 2 + `/start` + `./rk setup`(端末を開くのは一回。合言葉は後回しにできる)+ 開き直す + 考えを話す + 画面でボタン一つ。v1 では判断のたびに合言葉が要ったが、v2 で合言葉が要るのは VERIFIED と提出前の最終確認だけになった。科目が allowed なら、原稿への書き込みのたびの確認も出ない(代わりに由来が残る)。
