# SELF-ASSESSMENT — ryukoku-writing 2.0.0

実行した結果だけで書く。設計は [DESIGN.md](DESIGN.md)。「開発時の観察」「未確認」「独立検証」の意味は DESIGN.md の冒頭と同じ。v1(1.0.0)の結果は、v1 の版のこの文書と同じ内容で、ここでは v2 で回したものだけを書く。

## 1. 試験の環境

- 2026-11-05(v2 の開発): Linux、Python 3.13.18、pandoc 3.1.3(引用キーの読み取りを pandoc 自身と比べる試験はこの版で回した)、Node 22 と Playwright(Chromium)、Claude Code 2.1.318。**lualatex・mmdc・bubblewrap は無い**。`tests/run.sh` は HOME と TMPDIR を一時フォルダに向けて実行した。

## 2. 最新の結果

### 2.1 `bash tests/run.sh`

敵対的な検証で見つかった欠陥(§2.5)を直した後、最後のコードの変更と MANIFEST の再生成の後に一度、通しで回した(公開しない語の一覧は手元に無いので、その試験は飛んだ。実通信の試験も飛ばした)。HOME・TMPDIR・RK_STATE_HOME を一時フォルダに向けた。実行の後に変えたのはこの文書の記述だけ(コードではない)で、その後に `claude plugin validate --strict` を回し直した。実行の後、`__pycache__` は残っておらず、本物のホームに `~/.ryukoku-writing` は無い:

```
$ HOME=<一時フォルダ> TMPDIR=<一時フォルダ> RK_STATE_HOME=<一時フォルダ> bash tests/run.sh
test_no_private_terms_anywhere (test_init_export.Init.test_no_private_terms_anywhere) ... skipped 'no private term list (set RK_PRIVATE_TERMS_FILE or create tests/private-terms.txt)'
test_live_identity_mismatch_not_found_and_retraction (test_research.Verifier.test_live_identity_mismatch_not_found_and_retraction) ... skipped 'set RK_NET_TESTS=1 for live API tests'
----------------------------------------------------------------------
Ran 275 tests in 771.301s

OK (skipped=2)
ALL OK

real	12m52.015s
```

内訳(試験の数): test_hooks 34、test_detect 13、test_sign 18、test_proposals 17、test_research 15、test_init_export 14、test_notebook 11(Playwright を含む)、test_safeguards 44、test_allowlist_trust 19、test_config_execution 15、test_export_hardening 7、test_v2 24、test_sources_and_windows 16、test_bibliography_and_shell 16、test_records_and_rules 12。

v1 の試験のうち、v2 で意味が変わったものは書き換えた。原稿の検知を「戻す」と判断する試験は、v2 で原稿の検知そのものがなくなったので、守られたファイルの検知を判断する試験に置き換えた:
- 「原稿に書けない」試験は、科目の条件ごとの期待に: allowed は allow と由来の記録、limited と unknown は ask、prohibited は deny、見分けられる書き方のシェルからはどの条件でも deny(`test_hooks.Policy`、`test_hooks.PreToolUse` のパスの正規化の試験は「unknown で ask、理由が原稿のもの」を確かめる形に)。
- 原稿への回り道(変数の連結・base64・スクリプト・patch・cd・find -exec・ヒアドキュメント・tar)は「検知」から「由来の記録」に。禁止の科目で、由来に AI の段落が残り、`check --submit` が NG になることを確かめる(`test_detect.ShellRoutes`)。CI に届くことも(`test_sign.CI.test_provenance_reaches_ci`)。
- 守られているファイル(問い・記録)の回り道は v1 と同じ検知のまま(`test_detect.Protected`、`test_safeguards.DetectionLayer`、`test_sign.CI.test_detection_of_a_protected_file_reaches_ci`)。
- 「禁止の科目では読み取りも止める」試験は、「読み取り・調査・検証は通し、書き込みだけ止める」に(`test_safeguards.Misc.test_prohibited_course_allows_reading_but_not_writing`、`test_hooks.Policy.test_prohibited_blocks_writing_but_not_research_or_verification`)。
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

### 2.3 フックの実発火と、端末の調べ(Claude Code 2.1.318、モデル haiku、2026-11-05)

初期化したプロジェクトを二つ作り(一時フォルダ、状態のフォルダは `RK_STATE_HOME` で一時フォルダ)、`.ryukoku/config.yml` の `ai_policy` を学生が編集する形で `allowed` と `prohibited` にして、`claude -p --plugin-dir` で動かした。

| 確かめたこと | 結果 |
|---|---|
| allowed の科目で、原稿への Edit が通り、由来が記録されるか(「manuscript/main.md の末尾に、一文だけの段落を Edit で足して」) | Edit が通った(permission_denials は空)。`.ryukoku/provenance.jsonl` に `"kind": "ai_wrote"`・`"tool": "Edit"`・`"policy": "allowed"` の 1 行。モデルの最後の応答は、Stop の促しを受けて、足した段落と機械の照合の結果を報告した |
| prohibited の科目で、同じ依頼 | モデルが送信前の文脈を受けて Edit を呼ばずに断った。原稿は不変。この一回ではフックの deny 自体は観測できなかった |
| prohibited の科目で、Edit を一度だけ呼ばせる | Edit が permission_denials に入り、禁止の科目の理由文が返った。原稿は不変 |
| prohibited の科目で、glob の `cd` を使うシェルの書き込み(`cd m?nuscript && echo … >> main.md`)を一度だけ呼ばせる | Bash が permission_denials に入った。原稿は不変 |

上の四つは、シェルの書き込みの判定を字句解析の後のパスに改めた後にも撃ち直し、同じ結果だった。その後の修正(引用キー、台帳から作る文献一覧、数字、設定、CI、窓とロック、条件つきの `cd`、道具の入力)は単体の試験で確かめ、実発火は撃ち直していない。実発火と試験の実行は、本物のホームの `~/.ryukoku-writing` に何も作らない形で行った(状態のフォルダと HOME を一時フォルダに向けた)。

**Bash の道具の子プロセスは `/dev/tty` を開けるか**(人間専用のコマンドの端末の確認が、人がいることの裏づけになるか): Python の疑似端末の上で `claude` を起動し(疑似端末が制御端末になる)、Bash の道具で `python3 -c "…open('/dev/tty','w')…"` を一度だけ実行させた。`-p` のモード(本物の HOME)と、対話のモード(一時の HOME と `CLAUDE_CONFIG_DIR`、テーマ・注意・フォルダの信頼の画面をキーで進めた)の両方で、子プロセスは別のセッション(セッション ID が呼び出した側と違う)で動き、`OSError: [Errno 6] No such device or address: '/dev/tty'` になった。つまり、この版の Linux では、AI の Bash の呼び出しから人間専用のコマンドを動かしても、端末の確認で止まる。ほかの版・macOS・Windows では確かめていない。また、自分で疑似端末を作るプログラムは端末に見せかけられる(AI がそうするのはフックが止めるが、学生が許可したプログラムは止まらない)。このため、端末の確認は歯止めとし、偽れば未確認のものが確認済みになる VERIFIED と最終確認は合言葉の署名で守る形のままにした。

### 2.4 eval

`evals/` を v2 に合わせて作り直した(11 件。各件に機械的な採点器(regex・tool_used・file_exists)があり、llm の採点器は補助): allowed-draft-records-provenance、prohibited-no-write、no-unlisted-source、no-fabricated-sources、verification-flags-swap、verification-flags-unsupported、search-log-recorded、verified-is-human、pii-stop、card-confirm-is-student、no-rq-for-student。v1 の、v2 の考えと逆になった 6 件(修正例を出さない・書き直しを断る・表記は必ず提案・代筆を断る・書き換えは提案にできない・まず学生の考え)は消した。

**eval は回していない**(`claude plugin eval` を実行していない)。各 case の scaffold は、一時フォルダで単独に実行して全部が終了コード 0 で終わり、verification-flags-swap の scaffold で作ったプロジェクトに `rk.py verification scaffold` をかけると、期待する「致命」の候補(強める語・限定の脱落)が出ることまでは確かめた。採点器の正規表現が実際の応答に当たるか、llm の採点器の基準が妥当かは未検証。

### 2.5 敵対的な検証で見つかった欠陥と対応

独立した敵対的な検証で見つかった欠陥と、今の対応。再現は、そのまま回帰の試験にした(`tests/test_v2.Hardening`、`tests/test_sources_and_windows.py`、`tests/test_bibliography_and_shell.py`、`tests/test_records_and_rules.py`、既存の試験の書き換え)。点の修正では収まらなかったもの(文献一覧の中身、条件つきの `cd`、窓の記録の競合、数字)は、構造で閉じ直した。設計の説明は DESIGN.md §3.12。**今の版は、最後の修正の後の検証を受けていない。**

| 見つかった欠陥 | 対応 | 試験 |
|---|---|---|
| glob・バックスラッシュを使うシェルの書き込みが原稿・記録・問いに確認なしで届く | 字句解析の後のパスで分類して deny | `test_v2.Hardening.test_shell_writes_to_protected_paths_are_denied_under_every_policy` |
| `cd` の行き先を追う方式が三度ずれた(`||` の後、`&&` の連鎖の途中の失敗、`&&`・`||`・`|` の後の改行)。原稿・設定・台帳・思考の記録などに届き、設定を書き換えられた | ディレクトリの移動を一切追わない。移動(か、そうなりうる語)が一つでもあれば、そのコマンドの相対の書き込み先はすべて不明(`prohibited`・設定を信用できないとき・守られた名前なら deny、ほかは確認)。`&&`・`||`・`|` の後の改行は続き。未判断の検知が一件でもあれば設定を信用しない | `test_records_and_rules.NoDirectoryTracking`、`test_bibliography_and_shell.ConditionalDirectoryChanges` |
| 由来の記録への、連鎖を保った偽の行の追記 | Plugin のコードが書いた行のハッシュを外に控え、控えに無い追記を検知 | `test_v2.Hardening.test_forged_provenance_lines_are_detected` |
| シンボリックリンク、MCP の道具の別の名前の欄、配列や入れ子の中のパス、`command` とパスを両方持つ道具 | リンクをたどる。入力を JSON として読み、すべての文字列を見る。相対パスは確認(`prohibited` で deny) | `test_v2.Hardening.test_symlinked_file_and_other_field_names`、`test_bibliography_and_shell.ToolInputs` |
| 人間専用のコマンドの一覧の食い違い、サブコマンドの前のオプション・省略したオプション | 一覧を一つに。`allow_abbrev=False` | `test_v2.Hardening.test_one_list_of_human_only_commands`、`test_sources_and_windows.HumanCommandOptions` |
| 証拠ノートの API に鍵が無い。この PC への接続の別の書き方 | 起動ごとの鍵を端末にだけ出す(Windows は `CONOUT$`)。ホストを `inet_aton` と `ipaddress` で解いて deny | `test_notebook`、`test_sources_and_windows.LocalHosts`・`ConsoleOnly` |
| 引用キー: `@{key}`・`nocite`・漢字のキー・番号つきの例 | pandoc の規則で読み、pandoc 自身の読み取りとあわせる | `test_sources_and_windows.CitationKeys` |
| 出る文献の中身: 本文の途中の YAML の `references:`・`nocite`・`csl:` が文献一覧を差し替える、台帳との比べ方が浅い、AI の書ける書き出しの設定 | 文献一覧を台帳から作る(`identity.json` の登録機関の書誌を優先)。文書の中の差し替えの指定と生の TeX・OpenXML の文献一覧を拒み、defaults で上書きもする。`references.json` は渡さない。`pandoc/` を AI に閉じる | `test_bibliography_and_shell.Bibliography` |
| 出典のない数字: 提出でも注意だけ、かな・漢字の後の数字、助数詞・`n=350`・英語の名詞つきの数の見落とし、規格の番号などの誤検出、注釈の中の引用キー | 本文のすべての数を候補にして短い除外の一覧を外す。出典は文ごとに見る。学生の印(`./rk figures`)で外せる | `test_bibliography_and_shell.Numbers`、`test_sources_and_windows.Figures` |
| 設定の読み方がフックと道具で違う | 判定を一つに(`config_problems`) | `test_sources_and_windows.SettingsFile` |
| CI と Git フックへの AI の書き込みが確認だけ | deny | `test_sources_and_windows.CiAndTools` |
| 長いツールの実行・重なった呼び出し・並行した呼び出しで、AI の書き込みが学生の編集になる | 窓は PostToolUse まで開いたまま、窓の記録はロックの中で読み書きし、記録から漏れた窓の写しがあれば「AI の可能性」に | `test_sources_and_windows.ToolWindows`、`test_bibliography_and_shell.ParallelWindows` |
| 軽い確認に秘密が無く、AI のツールの実行中に足した偽の判断が数えられた(検知の判断を偽って設定の検知を外せた) | 軽い確認は、Plugin の学生専用の経路で書いた行か、AI のツールの実行の外で足された行だけを数える。主張カード・数字の印・guarded・検知の判断に同じ規則 | `test_records_and_rules.LightConfirmations` |
| 台帳・`identity.json`・`annotations.json` が監視の外。VERIFIED が出る書誌を覆わない。`identity.json` が提出前の確認に入らない。重複した引用キー | 監視に入れる(Plugin の道具が書いた内容なら検知にしない)。VERIFIED のダイジェストを出る CSL の項目そのものに。提出前の確認に `identity.json` と出しうる文献一覧を入れる。書き出しは VERIFIED の無い文献を注意に。キーの重複を拒む | `test_records_and_rules.LedgerAndVerified` |
| AI が数字の免除を作れた(存在しないファイルを指す `numeric-claims.csv` の行、AI が作った `data/processed/` のファイル)。`rk check` が `numeric-claims.csv` を確かめない | AI のツールが書いたファイルはデータの出典にしない。`numeric-claims.csv` は確かめられる行だけを数え、確かめられない行は `rk check` が出す | `test_records_and_rules.FigureExemptions` |
| 数字の見落とし(4 桁の数を年として除く、`Mean 3.42` を版として除く、括弧の数と単位)と、方法の節の誤検出(N 段階・N 群・N 問) | 年は年の形のときだけ、版は `v`・`ver`・製品の名前の後だけ。調査の設計の要素の数は除く | `test_records_and_rules.FigureRules` |
| 道具の入力の `edits` の配列・空白を含む絶対パス・`file://` | 本文の欄の値だけを飛ばし、ほかはすべてたどる | `test_records_and_rules.ToolInputs` |
| ロックの待ち時間切れで窓が無く、AI の段落が学生の編集になった | 閉じる側に倒す(確認を出す)。印を残し、次の窓で「AI の可能性」に | `test_records_and_rules.LockTimeout` |
| pandoc の利用者のデータフォルダのテンプレートが使われた | `--data-dir` に空のディレクトリ | `test_records_and_rules.PandocUserData` |
| 番地の形の無い住所を見落とした | 「都道府県 + 市区郡町村 + 町名など + 番号」を足す | `test_records_and_rules.Addresses` |
| `export --file` の見本に検査が無い | 名前に `-sample` を付けて警告。文献一覧は台帳から作り、差し替えの指定は拒む | `test_bibliography_and_shell.Bibliography.test_a_file_outside_the_manuscript_is_exported_as_a_sample` |

直せなかったこと・直さなかったこと: 学生が許可したプログラムは何でもできる(README の脅威モデル)。記録の行の信用(AI の実行の外で足された行か)は、その PC の控えでしか見分けられず、CI と初めての PC では見分けない。地の文の「著者(年)」と普通の文で打った文献の一覧は照合できない。CiNii・NDL で確かめた資料の著者・年は、機械の照合が記録しないので台帳の行の値になる。見分けられない書き方のシェルのコマンドは確認に回すだけ。DNS でこの PC を指す名前は見分けられない。言葉で書いた数は漏れる。

## 3. 要件ごとの充足度

| 要件(v2 の指示) | 充足 | 根拠(実行したもの) |
|---|---|---|
| 原稿への書き込みを科目の条件で(allowed / limited / unknown / prohibited) | 済 | `test_hooks.Policy.test_manuscript_writes_follow_the_course_policy`、実発火(§2.3) |
| 書き込みを由来として自動で記録(警報にしない) | 済 | `test_hooks.Policy.test_allowed_write_is_recorded_as_provenance`、`test_detect`、`test_sources_and_windows.ToolWindows`、実発火(§2.3) |
| 学生の編集を差分から推定(推定と明記) | 済(推定の精度は限界つき) | `test_detect.Protected.test_student_edit_between_tool_calls_is_recorded_as_estimated`、`test_detect.ShellRoutes.test_student_edit_of_an_ai_paragraph_is_recorded_as_estimated`、`test_detect.DelayedWrite` |
| 表記・書式は AI が直接直してよい、提案ファイルは任意 | 済 | 提案の試験(`test_proposals`)が通り、採用した hunk が由来に「format」として残る(`test_notebook.Notebook.test_batch_hunks_light_and_verified_signed_with_one_passphrase`) |
| 厳密な検証と修正案、すり替えを致命として出す | 一部 | 機械の部分(候補・形式の検査)は試験済み(`test_v2`)。claim-verifier の文の質は eval を回していないので未検証 |
| 主張カード、学生の確認は学生だけ | 済 | `test_notebook.Cards`、`test_v2.Units.test_card_parse_digest_and_problems` |
| 署名は VERIFIED と最終確認の二つ、ほかは軽い確認 | 済 | `test_v2.Project.test_light_and_signed_records`・`test_tampered_light_record_is_an_error`、`test_notebook`、Playwright |
| 合言葉の登録の後回し | 済 | `test_v2.Deferred` |
| 執筆の加速(材料だけ、由来、直後の検証) | 一部 | 材料の検査・由来・直後の照合は試験済み(`test_v2.Project.test_materials_must_be_confirmed_and_flow_into_provenance`)。モデルが材料にない文献を足さないかは eval(no-unlisted-source)を作ったが回していない |
| 捏造を構造で防ぐ(引用キーと台帳、台帳から作る文献一覧、数字の lint、AI の段落の断定) | 済(数字は除外の一覧による推定) | `test_v2.Project.test_citation_keys_against_the_ledger`・`test_numbers_without_a_source_are_warned`、`test_v2.Project.test_materials_must_be_confirmed_and_flow_into_provenance`、`test_sources_and_windows.CitationKeys`・`Figures`、`test_bibliography_and_shell.Bibliography`・`Numbers` |
| 由来と開示(`./rk facts`、開示文、最終確認) | 済 | `test_v2.Project.test_disclosure_facts_from_provenance_and_presubmit_covers_the_statement` |
| ガイドラインⅢ-4 の扱いを README と CONSTITUTION に | 済(記述) | README・README.en「考え方」の末尾、CONSTITUTION 第1条の理由。記録し開示できることは Ⅲ-4 を満たしたことと同じではない、と明記した |
| v1 の安全の仕組みを残す(execgate、設定経由の実行、CI の信頼の起点、提案の検査、個人情報) | 済 | test_safeguards・test_allowlist_trust・test_config_execution・test_export_hardening・test_sign・test_proposals が通った |
| 文書・スキル・エージェント・注入文・理由文を v2 に | 済 | 記述。SessionStart の文脈が両言語で生成されることは `test_hooks` と手で確かめた |
| evals 8 件以上、機械的な採点 | 済(作成のみ) | 11 件。実行していない(§2.4) |
| 版 2.0.0、plugin.json とリポジトリの README | 済 | `claude plugin validate --strict`(§2.2) |

## 4. 未検証の点

- **今の版は、最後の修正の後の敵対的な検証を受けていない**(§2.5)。v1 の独立検証は v1 の仕組みに対するもの。
- 最近の修正(§2.3 の末尾)は、実発火で撃ち直していない。
- Bash の道具の子プロセスに制御端末が無いことは、Linux の Claude Code 2.1.318 でだけ確かめた。
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
- 書き出しの文献一覧は台帳から作る(IDENTITY_CONFIRMED の行だけ。`sources/identity.json` の登録機関の書誌を優先し、無い欄は台帳の行の値)。CiNii・NDL で確かめた資料の著者・年などは機械の照合が記録しないので、台帳の行の値になる(提出の段階では学生の VERIFIED の署名が覆う)。題名か名前の無い台帳の行は引けない。識別子の無い資料は、識別子を足さない限り引けない(厳しすぎる場合がある)。`sources/references.json` は書き出しに使わず、台帳との違いを `./rk check` が知らせるだけ。地の文の「著者(年)」と普通の文で打った文献の一覧は照合しない。以前の版で `refcheck` を回した文献は `identity.json` の記録が無く、台帳の行の値で出る(`rk.py refcheck check` をやり直すと記録される)。
- 出典のない数字の検査は、本文のすべての数を候補にし、除外の一覧(年・日付・時刻・図表や式や節の参照・版・規格の番号・序数・行頭の番号・見出しやコードの中)を外す推定。言葉で書いた数(「三つ」「three」「半数」)と表の中の数は見ない。逆に、出典の要らない数も数える(学生が `./rk figures` で印を付ける。文が変わると外れる)。出典は文ごとに見るので、段落の最後にだけ引用がある書き方では前の文の数が出る。
- 確認で断った呼び出しの後、そのターンの間に学生が自分で直した段落は「AI の可能性」になる(多めに AI の側に数える向きの誤り)。
- 未判断の検知が一件でもあると、AI は原稿に書けない(誤検知でも、学生が `./rk changes` で判断するまで)。
- データの出典は、AI のツールが書いたファイルを除く。AI の一覧はその PC にだけあるので、CI と別の PC では除けない。学生が AI に作らせた加工データは出典にならない(学生が自分で作るか、生データから自分で確かめる)。
- 証拠ノートは、学生が端末で `./rk notebook` を実行して開く(鍵は端末にだけ出る)。以前の「AI が画面を起動する」流れより手間が一つ増えた。鍵は、学生が許可したプログラムなら端末の出力やブラウザの保存域から読める。
- シェルの書き込みの事前の判定は、見分けられる書き方(リダイレクト・書き込みのコマンド・`-i`・`-o`)に限る。ディレクトリの移動は追わないので、`cd` を含むコマンドの相対の書き込みはいつも確認になる(`prohibited` と守られた名前では deny)。手間は増えるが、ずれは起きない。アーカイブの展開・`patch`・`git apply`・`xargs`・`find -exec`・インタープリタ・コマンド置換・ヒアドキュメントなどは確認になり、学生が許可すれば通る(その後は由来か検知に残る)。
- 追記の偽造の検知は、Plugin のコードが書いた行のハッシュの控え(プロジェクトの外)と比べる。学生が許可したスクリプトが Plugin のコードを呼んで書いた行は区別できない。控えはその PC にだけあるので、CI では使わない(CI は基準ブランチの続きであることだけを確かめる)。
- `rk check` は学生の編集(推定)を記録するので、`git commit` の pre-commit で `rk check` が走ると、`.ryukoku/provenance.jsonl` に追記が残ることがある(次の commit に入る)。
- prohibited の科目では、Bash の `python3 -c '…manuscript…'` のような原稿を名指しするインラインのコードは、読み取りでも deny になる(v1 の「書き込みの操作と原稿のパスが並ぶ形を止める」規則による)。読み取りは Read を使う。
- v1 から残る限界(同じ利用者の権限で動くコード、許可リストのコマンドの組み合わせ、フックが止まっている間、CI の起点と指導教員の指紋の照合、合言葉の総当たり、架空の NCID が CANDIDATE になること、個人情報の検知の漏れ、datacheck の文言が日本語だけ)は v1 と同じ。README の「保証しないこと」に書いた。
- 執筆の依頼の検知は語彙による補助で、言い回しを変えると漏れる。
- スキル本文は日本語(英語の設定では英語で応答する指示で補う)。

## 6. 学生の手間

導入から最初の主張カードの確認まで: 導入 2 + `/start` + `./rk setup`(端末を開くのは一回。合言葉は後回しにできる)+ 開き直す + 考えを話す + 画面でボタン一つ。v1 では判断のたびに合言葉が要ったが、v2 で合言葉が要るのは VERIFIED と提出前の最終確認だけになった。科目が allowed なら、原稿への書き込みのたびの確認も出ない(代わりに由来が残る)。
