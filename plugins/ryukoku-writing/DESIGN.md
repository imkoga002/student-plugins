# DESIGN — ryukoku-writing 2.0.0

この文書は、この Plugin の設計をまとめる: 中核の考え、要件とその満たし方・試験、守りの仕組み、脅威モデルと限界、外部のプログラムの扱い、採った案と採らなかった案、事実の出典。試験を実際に回した結果と、確かめていない点は [SELF-ASSESSMENT.md](SELF-ASSESSMENT.md) にある。

言葉の使い方:
- **開発時の観察**: 開発した環境(Linux、Claude Code 2.1.318、2026-11-04〜05)で実際に見たこと。公式の文書では確かめていない。
- **未確認**: 一次資料でも実際の動作でも確かめていないこと。
- **独立検証**: 別の検証者が攻撃者の立場で行った検証(v1 と v2 の両方に対して、複数回)。見つかった欠陥は、再現をそのまま回帰の試験にした(`tests/test_safeguards.py`・`test_allowlist_trust.py`・`test_config_execution.py`・`test_export_hardening.py`・`test_proposals.AllowList`・`test_v2.Hardening`・`test_sources_and_windows.py`・`test_bibliography_and_shell.py`)。今の閉じ方は §3.12。**最新の版は、最後の修正の後の検証を受けていない。**

## 0. 脅威モデル(短く)

フックが相手にするのは、ふつうに使っている間の AI の誤り・近道・捏造である(科目が禁止なのに原稿を書く、記録・設定・道具に書き込む、確かめていない文献や数字を足す、学生の確認を装う)。フックは、決意した攻撃者や、学生が実行を許可したプログラムに対する砂場ではない(許可されたプログラムは学生の権限で何でもできる)。守りは二段で、(1) フックが見分けられる形の操作を事前に止めるか確認を出し、(2) すり抜けたものを後から見つける(msguard の窓の検知、`rk check`、CI)。後からの検知が最後の歯止めである。README の「保証すること」は、すべてこの枠の中で書いている。詳しい相手ごとの表は §4。

## 1. 中核の考え

**主張の主は学生、文章化は AI と速く、検証は厳密に、記録は正直に。** AI が主張や理論を厳密に検証するからこそ、学生は独自の理論・主張・ニッチな着眼を安心して言葉にできる。原稿を AI が書くことそのものは悪いことではない。問題は、学生の主張でないものが学生の主張として入ること、材料にない事実が入ること、それが隠れることである。

v1 は「AI は原稿に書けない・修正例を出さない・判断はすべて合言葉の署名」で、学生を縛る道具になった。v2 は、v1 で独立検証を経た守り(記録・道具・設定への AI の書き込みの拒否、許可リスト、窓の検知、署名と信頼の起点)を、**記録の正しさを守るために**残し、原稿だけを「書いてよい場所」(科目の条件しだい)に変えた。

四つの層で作る。上ほど早期警告、下ほど骨格である。

| 層 | 何をするか | どこ |
|---|---|---|
| 1. フック(事前) | すべてのツール(matcher `*`)。原稿への Write・Edit は科目の AI 利用条件(`ai_policy`)で allow / ask / deny、シェルからの原稿への書き込みは deny。`.ryukoku/`・道具・学生の問い・思考の記録・Claude Code の設定・`~/.ryukoku-writing` などへの AI の書き込みを、Write/Edit と Bash・PowerShell・Monitor で deny。人間専用のコマンド、端末の模擬、切り離した実行、画面の API 呼び出し、main への push も deny。**許可リストの外の実行は ask** | `scripts/hooks/pre-guard.sh`・`lib.sh`・`rklib/execgate.py` |
| 2. ツール実行の窓 | 読み取り専用でない道具の実行の前後で、原稿と守られているファイルを窓ごとの写しと比べる。**原稿の変化は由来(provenance)として段落ごとに記録する**。守られているファイルの変化は検知として AI 利用記録(連鎖)とプロジェクトの外の控えに書き、学生が判断するまで `rk check` と CI が落ちる | `rklib/msguard.py`・`provenance.py`・`ailog.py`・`scripts/hooks/post-log.sh` |
| 3. 記録(骨格) | 人間の判断は内容のダイジェストに結びつく記録だけ。**VERIFIED と提出前の最終確認は合言葉から導く Ed25519 鍵の署名**、ほかは署名のない軽い確認。由来・判断・AI 利用の記録は追記だけで、CI は基準ブランチの版の続きであることを確かめる | `rklib/sign.py`・`trust.py`・`subjects.py`・`decide.py`・`check.py`、`templates/github/.github/workflows/check.yml` |
| 4. 検証 | 原稿に書いた直後に機械の照合(引用の台帳の状態、引用のない断定、出典のない数字、主張カードとのすり替えの候補)を回して AI に返し、claim-verifier が論理・根拠の対応・反証・新規性・すり替えを重大度と根拠つきで書く | `rklib/verification.py`・`claimcards.py`、`agents/claim-verifier.md`、`skills/claim-verification` |

フックは正規表現による早期警告で、回り道の多くは事前には止まらない。それを拾うのが層 2 である。v2 では、原稿の回り道は「止めるべき事故」ではなく「記録すべき AI の書き込み」として扱い(科目が禁止なら検査が落ちる)、記録と道具の回り道は v1 と同じに検知する。

学生の手間への答え:
- 端末を開くのは最初の `./rk setup` の一回(科目条件・オプトアウト・合言葉・Git)。合言葉の登録は、最初の VERIFIED か最終確認のときに後回しにできる。
- 判断は証拠ノートの画面で行う。項目を「表示」すると、サーバーが内容・ダイジェスト・表示の証(サーバーの秘密による HMAC)を返し、その項目の判断が選べるようになる。軽い判断は「記録する」のボタン一つ、VERIFIED と最終確認は「署名する項目」にためて合言葉を一度入れる。表示していない項目と、表示の後に内容が変わった項目は、サーバーが受け付けない(409)。**全部採用の操作は画面にも API にも端末にもない**。
- 画面は学生が自分の端末で `./rk notebook` を実行して開く(§3.12)。合言葉の要らない判断を画面で記録できるので、画面の鍵がその代わりになる。AI が起動しようとするとフックが止める。

## 2. 要件と、その満たし方・確かめ方

| 要件 | どう満たすか | 確かめ方(試験) |
|---|---|---|
| **主張は学生のもの**: 考えの聞き取りと主張カード、学生の確認は学生だけ | `claims/C001.md`(主張・範囲と限定・必要な根拠・論拠・予想される反論・新規性の見込み・学生の言葉の原文)。AI が足した要素は `[ai_suggested]`。確認は kind `card` の軽い確認で、ダイジェストは学生の部分(印のない要素と原文)だけを覆う。ファイルの `status: confirmed` は記録がなければエラー。RQ と思考の記録は AI の書き込み禁止のまま | `test_notebook.Cards`、`test_v2.Units.test_card_parse_digest_and_problems`、`test_hooks.Research.test_questions_and_thinking_are_the_students`、eval `card-confirm-is-student`・`no-rq-for-student` |
| **科目の AI 利用条件で原稿への書き込みが変わる** | `pre-guard.sh` の `manuscript_gate`: allowed は通す、limited と unknown は ask(理由と、科目の条件を確かめる案内)、prohibited は deny。設定が読めないときも deny。シェルからの書き込みは、見分けられる書き方なら常に deny、ほかの書き方は確認(動いた後の変化は AI の由来)。prohibited は v1 の policy_gate を土台に、書き込み(原稿・主張カード・提案・材料の指定)だけを止め、読み取り・調査・検証・形式の確認は通す | `test_hooks.Policy.test_manuscript_writes_follow_the_course_policy`・`test_prohibited_blocks_writing_but_not_research_or_verification`、`test_safeguards.Misc.test_prohibited_course_allows_reading_but_not_writing`、eval `allowed-draft-records-provenance`・`prohibited-no-write` |
| **書き込みは由来として記録する** | PostToolUse(msguard)が窓の前の原稿の写しと比べ、変わった段落ごとに `.ryukoku/provenance.jsonl` へ(時刻、ファイル、行の範囲と内容のハッシュ、種類、材料、方針、道具)。学生の編集は窓の間・SessionStart・`rk check` の差分から推定(`estimated: true`)。行ごとに前の行のハッシュ、この PC で最後に書いた行数と先頭を外に控え、CI は基準ブランチの版の続きを求める | `test_hooks.Policy.test_allowed_write_is_recorded_as_provenance`、`test_detect` 全体、`test_safeguards.DetectionLayer`、`test_sign.CI.test_provenance_reaches_ci` |
| **厳密な検証** | `rk.py verification scaffold` が `review/verification/<日付>-<対象>.md` を作り、0 節に機械の照合を入れる。1〜5 節(論理・根拠の対応・反証・新規性・すり替え)と 6 節(修正案)は claim-verifier が書く。`verification lint` が重大度・観点・根拠の形、抜粋なしの「支える」、新規性の断定、反証の検索記録を確かめる | `test_v2.Units.test_verification_lint`・`test_swap_candidates`、`test_v2.Project.test_materials_must_be_confirmed_and_flow_into_provenance`、eval `verification-flags-swap`・`verification-flags-unsupported` |
| **執筆の加速は材料だけで** | draft-writer: 確認済みの主張カード・論証図・台帳の文献・保存したデータだけを材料にし、`rk.py provenance materials` で記録(draft のカード・台帳にない文献・ないデータは拒否)。書いた直後に機械の照合が文脈として返り、Stop のフックが結果を学生に示すよう一度促す | `test_v2.Project.test_materials_must_be_confirmed_and_flow_into_provenance`・`test_stop_hook_reminds_after_a_manuscript_write`、eval `no-unlisted-source` |
| **捏造を構造で防ぐ** | 書き出しの文献一覧は台帳から作る(IDENTITY_CONFIRMED の行だけ。欄は機械の照合が登録機関から記録したもの(`sources/identity.json`)を優先し、無い欄は台帳の行。`sources/references.json` は pandoc に渡さない)。原稿が引く文献(`[@key]`・`@{key}`・`nocite`、`@*` は IDENTITY_CONFIRMED の行すべて。キーは pandoc の規則で、提出の段階と書き出しでは pandoc 自身の読み取りも合わせる。`rklib/citations.py`)が台帳にない・IDENTITY_CONFIRMED 未満・題名か名前の無い行なら、提出の段階の検査と書き出しで NG、下書きで注意。文献一覧と書式を差し替えるメタデータ(本文の途中の YAML の塊を含む)と生の TeX・OpenXML の文献一覧は NG。数字は本文のすべての数を候補にし、除外の一覧を外したものに、文ごとに引用か実在するデータの参照がなければ、下書きで注意、提出の段階で NG(学生の印で外せる)。AI が書いた段落の引用のない断定は検証で「重要」。地の文の「著者(年)」は照合できない | `test_v2.Project.test_citation_keys_against_the_ledger`・`test_numbers_without_a_source_are_warned`、`test_sources_and_windows.CitationKeys`・`Figures`、`test_bibliography_and_shell.Bibliography`・`Numbers`、eval `no-fabricated-sources` |
| **由来と開示** | `./rk facts` の 5 に、AI が書いた・直した段落の数と割合、節ごとの内訳、用途、材料。開示文の下書きは AI が `disclosure/statement.md` に書いてよく、提出前の最終確認(署名)のダイジェストがそれと由来の帰属を覆う | `test_v2.Project.test_disclosure_facts_from_provenance_and_presubmit_covers_the_statement` |
| **署名は二つだけ** | `sign.NEEDS_SIGNATURE` = (source, VERIFIED)・(claim, VERIFIED)・(presubmit, ready)。ほかは `make_confirmation`(署名なし、id は内容のハッシュ)。署名のない VERIFIED は検査のエラー。軽い確認が AI の窓の中に現れたら検知 | `test_v2.Project.test_light_and_signed_records`・`test_tampered_light_record_is_an_error`、`test_detect.Protected.test_unsigned_confirmation_appearing_in_an_ai_call_is_detected`、`test_notebook` |
| **合言葉の登録を後回しにできる** | `./rk setup` の合言葉の段は任意。`./rk verify`・`./rk signoff` は信頼された署名者がいなければ、署名の前に登録の段(`setup.step_passphrase`)に入る | `test_v2.Deferred` |
| **日本語と英語** | `.ryukoku/config.yml` の `manuscript_lang` と `feedback_lang`。フック・画面・`./rk`・機械の照合の文言が講評言語に従う | `test_init_export.Init.test_language_is_one_line`、`test_hooks.Hooks.test_session_start_language_and_notebook_path`、`test_safeguards.Misc.test_machine_commands_follow_english` |
| **GitHub でも Git なしでも運用できる** | `templates/github/`(基準ブランチの道具で PR を検査する check.yml、PR・Issue のテンプレート、`.githooks/`)。Git なしは `rk.py bundle` の HANDOFF.md | `test_init_export.Init.test_workflows_parse_and_pin_only_checked_actions`、`test_sign.CI`、`test_init_export.Misc.test_bundle_lists_signers_and_checks` |
| **記法の規則は学部の要項から取り出し、学生が承認したものだけを使う** | `proposals/style-rules.yml` → 画面か `./rk style` で承認(軽い確認)→ `.ryukoku/style.yml` | `test_proposals.StyleExtraction` |
| **ローカルの HTML 画面** | `scripts/rk/notebook/`(CDN なし、127.0.0.1、Host/Origin/独自ヘッダの検査、ARIA のタブ、主張カードのタブ、由来の要約) | `test_notebook` 全体、Playwright の `tests/js/notebook.test.js` |
| **Claude Code の Plugin として動く** | skills 24・agents 5・フック 5 種・scripts。フックは bash 3.2 の構文だけ | `bash tests/run.sh` の構文と移植性の検査、`test_init_export.Init.test_validate_strict`、`test_safeguards.Portability` |
| **龍谷大学のガイドラインに対するこの Plugin の解釈**(作成者の解釈で、満たしたことの保証ではない) | 科目条件で原稿への書き込みを変える(Ⅲ-3)、AI が書いた部分を記録して開示の事実にする(Ⅲ-4。記録し開示できることは、AI の作成物を自分の成果物として出さないことを満たしたのと同じではない。開示し、科目の規則に従うのは学生)、主張は学生(Ⅲ-1)、個人情報の送信停止(Ⅱ-2(1))、真偽の確認(Ⅱ-2(2))、`guideline-check`(Ⅳ) | 仕組みの試験: `test_hooks.Prompts`・`Policy`、`test_v2.Prompts`(ガイドラインに沿うかどうかは試験できない) |
| **公開できる** | 非公式の表示、校章を使わない、ガイドラインの原文を転載しない、公開しない語を含まない、題材は記号(「現象 X」「要因 A」)か中立な例(図書館の利用、調査の回答率)だけ | `test_init_export.Init.test_no_guideline_text_copied`・`test_no_real_looking_personal_data_in_package`。公開しない語の試験(`test_no_private_terms_anywhere`)は、保守者が語の一覧(`RK_PRIVATE_TERMS_FILE`)を渡したときだけ動く。この版の試験の実行では一覧が無く、飛ばした(SELF-ASSESSMENT.md) |
| **文献の実在を機械で確かめ、原典が主張を支えるかは人間が確かめる** | `rklib/refcheck.py`、台帳、`sources/verification-log.jsonl`。VERIFIED は書かない | `test_research.Verifier`(実通信は `RK_NET_TESTS=1`) |
| **調査は学生の問いに結びつき、検索ごとに記録が残る** | `rk.py search` は問いの番号が `research/questions.md` に無ければ通信せずに終了コード 2、実行のたびに記録、`--purpose counter`。WebSearch と DB の検索 URL への WebFetch もフックが自動で記録 | `test_research.Questions`、`test_hooks.Research`、eval `search-log-recorded` |
| **研究データを保存し、後で誰でも確かめられる** | `rklib/datacheck.py`(raw は変えない、sha256 の manifest、来歴、Data Package v2)、raw への書き込みの deny | `test_hooks.PreToolUse.test_direct_writes_and_pushes_to_main`、`test_init_export.Init.test_fresh_project_passes_every_check` |
| **数式・図・表・脚注・相互参照を書け、Word・PDF・LaTeX に書き出せる** | `templates/{ja,en}/examples/format-examples.md`、`rklib/export.py` | `test_init_export.Init.test_docx_and_latex_both_languages`、`test_config_execution.PandocDefaults`、`test_export_hardening` |

## 3. 守りの仕組み

### 3.1 書き込みの判定(フック)

- 原稿(`manuscript/`)への Write・Edit・MultiEdit・NotebookEdit は、科目の AI 利用条件で決まる: `allowed` は通す(窓を開き、PostToolUse が由来を記録する)、`limited` と `unknown` は ask、`prohibited` は deny。`.ryukoku/config.yml` が見つからない・読めない・UTF-8 でない、`ai_policy` で始まる行(字下げを含む)が 0 か 2 以上、その行が `common.POLICY_LINE` の形(キー、空白かタブ、四つの値の小文字(同じ引用符で囲んでもよい)、空白かタブ、`#` の注釈、行末の CR だけ)でないときも deny。判定は一つで、フックは `hookcore.py cfgcheck`(`common.config_problems` と `course_policy`)を呼ぶ。Python が無い PC では `lib.sh` の `cfg_check_bash` が同じ規則を確かめる(UTF-8 の検査は iconv があるときだけ)。試験が三つ(フック・Python・bash の規則)の一致を確かめる。最後の部分がシンボリックリンクのファイルは、たどった先で判定する(`lib.sh` の `phys_file`)。理由文は、limited なら許可された用途と「シラバスで確かめる」、unknown なら「シラバスを確かめて ./rk setup で記録する」を述べる。
- シェル(Bash・PowerShell・Monitor)からの書き込みの判定は、`execgate` の字句解析の後のパスで行う(§3.12)。判定できるのは見分けられる書き方(リダイレクト、書き込みのコマンド `WRITE_CMDS`、`-i` の `sed`・`perl`・`ruby`、`-o` で書き出すコマンド)だけで、ほかの書き方(アーカイブの展開、`patch`・`git apply`、`xargs`・`find -exec`、`-c`・`-e` のインタープリタ)は許可リストの外として確認に回り、許可されて動いた後の原稿の変化は AI の由来として記録される(`test_sources_and_windows.ToolWindows`)。`cd`・`pushd`・`popd` の行き先を追い、`cd -L`・`-P` を読み、`popd`・`cd -`・スタックの引数・`CDPATH`(環境にあるか、コマンドが設定する)の効く相対の `cd` の後は行き先不明にする。原稿への書き込みは条件にかかわらず deny。理由は「Write・Edit で書く(段落ごとの由来を正確に記録し、条件の確認を通すため)」。`pre-guard.sh` の正規表現(`\` を `/` にした形と、バックスラッシュの escape を外した形の両方を見る)は早期警告で、判定の骨格ではない。
- 知らない道具(MCP など)は、`tool_input` の中でパスに見えるすべての文字列の値(`path`・`filename`・`destination`・`target_file` など。本文を運ぶ欄は除く)を、Write と同じに判定する。
- `.ryukoku/` 全体(由来の記録を含む)、`tools/`・起動ファイル(`rk`・`rk.cmd`・`rk.ps1`)・Plugin 本体・`~/.ryukoku-writing`・`.claude/` と `~/.claude/`、`research/questions.md`・検索の記録・`thinking/`・`disclosure/`(開示文の下書き `disclosure/statement*.md` を除く)・`review/annotations*`・台帳・`data/raw/` への AI の書き込みは、どの道具でも deny(v1 と同じ)。CI と Git フック(`.github/`・`.githooks/`)と書き出しの設定(`pandoc/`)も、どの道具・どの条件でも deny(以前は確認だった)。変えるのは学生で、AI の外で変え、`./rk sign guarded tools --decision confirmed` で確かめる(`subjects.guarded_files` が Plugin の写しと比べる。`pandoc/reference.docx` は比べない)。
- `claims/`(主張カード)は AI が書いてよい(limited では用途 `ideas`、prohibited では deny)。`review/verification/` は用途 `review`。
- 目印の探し方(対象のパスから上へ、セッションのフォルダ、一つ二つ下)、シンボリックリンクと `/./`・`//`・Windows の形のパスの正規化、利用者のプロジェクトの一覧による窓は v1 と同じ。
- 科目の AI 利用条件が `prohibited` のとき: v1 は読み取りも止めたが、v2 は「検証・調査・形式の確認は可」なので、Read・Grep・Glob・読み取りのコマンド・検索・検証のサブエージェントは通し、原稿・主張カード・提案・材料の指定(`rk.py propose`・`claims new`・`provenance materials`)だけを deny にする。`limited` は v1 と同じく許した用途の外に確認を出し、用途に `ideas`(主張カード)と `draft`(材料の指定)を足した。
- 個人情報らしき入力と、合言葉の形の入力は、送信前に止める(v1 と同じ)。

### 3.2 由来の記録と、ツールの窓の検知

- 窓ごとに写し(`~/.ryukoku-writing/state/<project>/windows/<tool_use_id>.json` と、原稿の本文の写し `<tool_use_id>.files/`)を取り、PostToolUse はそれと比べる。同じ呼び出しの中で共有の基準を作り直しても、原稿の差分は窓の写しから取れる。
- **原稿の変化**: 段落(空行で区切ったまとまり。front matter・コードの囲み・HTML の注釈は一つずつ、見出しは別)ごとに、`difflib` で窓の前と後を並べ、挿入・置換・削除を `ai_wrote`・`ai_edited`・`ai_deleted` として記録する(置換でも似ていなければ wrote)。材料は、段落の中の引用キー(台帳の id に直す)と、draft-writer が書く前に記録した主張カード・文献・データ・用途(`rk.py provenance materials`。2 時間で切れる)。由来の記録の前に、前回の記録から窓の前までの差を学生の編集(推定)として記録する。
- **学生の編集**: 最後に記録した本文を、プロジェクトの外(`state/<project>/prov/files/`)に控える。窓が開いていないときのツール呼び出しの前、SessionStart、`rk check` で、控えと今の原稿を比べ、差を `student_*`・`estimated: true` として記録する。最初に見たファイルは控えるだけで、それより前の段落は「記録の開始前」になる。
- **帰属**: 今の各段落のハッシュに当たる最新の記録を探す。AI の記録なら `ai_wrote`・`ai_edited`、学生の記録で、`from_sha` をたどった先に AI の記録があれば `student_after_ai`、なければ `student`、記録がなければ `unrecorded`。`./rk facts`・`./rk check`・画面がこれを出す。
- 由来の記録は追記だけ(窓の中で追記でない変更は検知)、行ごとに前の行のハッシュ、この PC で最後に書いた行数と先頭を外に控える(切り詰めて作り直すと見つかる)。CI は基準ブランチの版の続きを求める。
- 科目が `prohibited` なのに AI が書いた・直した段落が今の原稿にあれば、`rk check` は下書きで注意、PR と提出でエラー。
- **守られているファイルの変化**は v1 と同じに検知する: AI 利用記録と、プロジェクトの外の控え(state の `detections-witness.jsonl` と、フックから見えるときは `${CLAUDE_PLUGIN_DATA}/witness/`)に書き、判断(軽い確認)まで `rk check` と CI が落ちる。監視の対象: `tools/`・`thinking/`・`disclosure/`(開示文の下書きを除く)・`.github/`・`.githooks/`・起動ファイル、`.ryukoku/config.yml`・`signers.json`・`style.yml`・`research/questions.md`、Claude Code の設定、`plugin-root`、信頼の写し、`pandoc/`、`sources/references.json`(既存の文献の著者・年の変更と削除)。`signoffs.jsonl`・`ai-use-log.jsonl`・`provenance.jsonl`・検索の記録・`review/annotations-log.jsonl` は追記だけを許す。
- `signoffs.jsonl` への追記のうち、窓の中に現れたものは、信頼された署名者で検証できる**署名つきの記録だけ**を説明として認める。署名のない確認は学生の画面か端末で作るもので、AI のツールの実行中に現れたら検知にする。
- `provenance.jsonl`・`ai-use-log.jsonl`・`review/annotations-log.jsonl` は、Plugin のコードが行を書くたびに、その行のハッシュをプロジェクトの外(`state/<project>/written/`)に控える(`common.note_written`)。窓の中で追記された行のうち、控えに無いもの(printf・エディタ・別のスクリプトが書いた行)は検知にする。この比較は、フックがその呼び出しの由来を書く前に行う。連鎖を保ったまま偽の行を足しても見つかる。ただし、学生が許可したスクリプトが Plugin のコードを呼んで書いた行は「Plugin が書いた行」になる(同じ利用者の権限の限界)。
- 窓は PostToolUse が来るまで開いたままとみなす(その間の変化は AI のもの)。PostToolUse が来ないまま 6 時間を過ぎた窓は捨て、次の比較で見つかった変化を `actor: "uncertain"`・`"uncertain": true` で記録し、帰属では `uncertain` として AI の側に数える(事実の一覧と、禁止の科目の検査)。
- **AI が書いたファイル**(実行の確認の強さに使う一覧)は v1 と同じ(inode・大きさ・mtime・ctime)。
- 確認を求める(ask)呼び出しの窓も、PostToolUse が来るまで開いたままにする。呼び出しは重なりうる(次の呼び出しの PreToolUse が、前の呼び出しの PostToolUse より先に来る)。以前は、次の PreToolUse の時点で ask の窓を「断られた」として捨てていたため、学生が許した書き込みが学生の編集として記録された。今は、どれかの窓が開いている間は学生の編集の推定(`sync_student`)をしない。ターンの終わり(Stop のフックと、次の入力の UserPromptSubmit のフック。`msguard.turn_end`)に、まだ開いている窓は PostToolUse の来なかった呼び出し(断られたか失敗した)として閉じ、その間の変化を `actor: "uncertain"`・`"uncertain": true` で記録する。誤りは AI の側に多く数える向きになる(断った直後の学生自身の編集も「AI の可能性」になる)。

### 3.3 記録、署名と信頼の起点

- 記録は (種類、対象、判断、内容のダイジェスト、detail、役割、鍵、時刻、方法、メモ) で、`.ryukoku/signoffs.jsonl` に追記する。ダイジェストが変われば(記録の後に内容が変われば)無効になる。
- **署名つき**(VERIFIED・最終確認): 合言葉 → PBKDF2-HMAC-SHA256 60 万回(署名者ごとの salt)→ Ed25519 の鍵。秘密鍵のファイルは無く、`signers.json` には公開鍵・salt・回数だけを置く。Ed25519 は標準ライブラリだけの実装で、RFC 8032 の試験ベクトルと、`cryptography` があればそれとの照合で試験する。最終確認のダイジェストは、原稿・台帳・記法・主張カードのハッシュ、由来の帰属の要約、開示文(`disclosure/statement*.md`)、チェックリストを覆う。
- **軽い確認**(ほかのすべて): `sig` は空、id は記録の内容のハッシュ(`CF-…`)、方法は `tty` か `notebook`。署名が要る判断を名乗る軽い確認、id が内容と合わない確認は `rk check` のエラー。名前は `./rk setup` で決めた呼び名(`student_name`)。
- 合言葉は 10 文字以上で、同じ文字の繰り返し・数字だけ・よくある語が中心のものを拒み、3 語以上か 16 文字以上を求める。画面の署名は誤りが 5 回でロック(30 秒から倍々)。
- **CI の起点**、**Git なし**、**失効と引き継ぎ**、**main への push**、**道具と CI の変更**は v1 と同じ(根の commit がただ一つ、first-parent の最初の `signers.json` の署名者、失効した鍵の承認は引き継ぎ先だけ、起点の変更は指導教員が指紋を照らす前提、pre-push は端末での `yes`、PR の道具の変更は `guarded` の確認がなければ落ちる。v2 で `guarded` は軽い確認になった)。合言葉を後で登録したときは、最初の commit に `signers.json` が無いので、最初に現れた `signers.json` の commit が起点になる(setup がそう案内する)。

### 3.4 合言葉を受け取るコードの確認(v1 と同じ)

- `./rk` の起動ファイルは全プロジェクトで同じ固定の内容で、Plugin の場所はプロジェクトの外(`~/.ryukoku-writing/plugin-root`)から読む。これは間接参照であり、同じ利用者のプログラムは書き換えられる。
- SessionStart(Claude Code から受け取る `CLAUDE_PLUGIN_ROOT`)と初期化が `plugin-root` を書き、`plugin-root.log` に場所・MANIFEST の要約・版を追記する。`plugin-root` が最後の記録と違えば(Claude Code の外で書き換えられた)、検知として AI 利用記録に残し、学生に伝えてから戻す。
- 人間用のコマンドと画面は、合言葉を求める前に場所と版を出し、自分の場所と MANIFEST の要約が最後の記録と同じか、同梱の MANIFEST と食い違いがないかを確かめ、違えば止まる。自分のコードがプロジェクトの中(`tools/`)にあれば動かない。端末の操作は本物の端末(/dev/tty)でだけ動く。
- 証拠ノートの起動の判定は basename ではなく実際のパスで行う。v2 では `notebook` は人間専用のコマンドで、AI が起動する形は、Plugin のコードからでも deny(§3.12)。

### 3.5 確認なしで実行してよいコマンド(許可リスト。v1 と同じ)

`rklib/execgate.py` は bash の一部を真似た字句解析をする(一重・二重引用符、バックスラッシュ、行の継続、改行と `;` は区切り、`#` の注釈は語の頭だけで改行まで)。コマンド置換・バッククォート・プロセス置換・ヒアドキュメント・here-string・`$'…'`、括弧と波括弧(サブシェル・まとまり・関数の定義)、`case` は解析せず ask にする。単純なコマンドごとに次のどちらかなら確認なしで通し、それ以外は ask。

- (a) Plugin 同梱のコード: `python3`・`python`・`py`(名前だけで、無害な旗 `-B -I -u -E -s -S -O -OO -q -3` だけ)か `bash`・`sh` が、実際のパスが `CLAUDE_PLUGIN_ROOT` の中にあるファイルを実行するとき。プロジェクトの `tools/rk/…` は、`tools/rk` のすべてのファイルが Plugin の MANIFEST と内容のハッシュで一致するときだけ。`./rk` は、同梱の起動ファイルとバイト単位で同じで、`plugin-root` が Plugin を指すときだけ。前に環境変数の代入が付けば通さない。
- (b) 読み取りだけの決まったコマンド: `ls cat head tail wc grep egrep fgrep rg stat pwd diff cut tr nl paste comm join column sha256sum sha1sum md5sum basename dirname realpath readlink du df tree jq od echo printf true false test [ cd mkdir which type printenv date sort uniq file find env command git`。引数も照合する: `sort` の `--compress-program`・`-o`、`rg` の `--pre`、`find` の `-exec -execdir -ok -okdir -delete -fprint* -fls`、`date -s`、`tree -o`、`file -C -m`、`uniq` の出力ファイル、`env` と `command` の後ろのコマンドは ask。`git` は `status log diff show blame ls-files rev-parse` だけで、全体の旗は `-C --no-pager --no-optional-locks -P --literal-pathspecs` だけ(`-c --exec-path --git-dir --work-tree --namespace --ext-diff --textconv --output --config-env` は ask)。さらに、実際に使うリポジトリがこのプロジェクト自身の `<proj>/.git`(ディレクトリ)のときだけ通す(`-C`・`cd` の行き先から上へたどって判定。`.git` ファイル(gitdir:)や bare のリポジトリは ask)。`sed -n 'N,Mp' file`・`sed -n 'Np' file`(厳密に照合)と、`python3`・`pandoc`・`git`・`lualatex` などの `--version` だけの起動も通す。awk は ask。
- 出力のリダイレクトは、プロジェクトの中(`.git/`・`.githooks/`・`.github/` を除く)と `/dev/null` だけ。

理由文はコマンドを名指しし「Plugin の外のコードやコマンドを実行しうる」と書く。インタプリタで Plugin の外のコードを動かすときは「合言葉を入れる画面や端末を偽れる」、AI が書いた・変えたファイルを名指しするときはより強い文面にする。照合の道具が失敗したとき(最後の行 `scanned` が無い)と Python が無いときも ask(閉じる側に倒す)。保護したパスへの書き込みの deny は ask より先に判定する。`claude plugin|config|mcp|update|install` は deny。

### 3.6 提案の不変の検査(許可リスト。v1 と同じ。提案ファイルは v2 では任意の経路)

`rklib/proposals.py` は、両方の行を許可した変換だけで正規形にし、行の数も含めて一字ずつ等しいときだけ通す。作成時と適用時の二度検査する。

- 許可する変換: (1) 英数字(U+FF10〜FF5A)と半角カナ(U+FF65〜FF9F)の全角半角、(2) 科目で選べる句読点の組「、」⇔「，」・「。」⇔「．」(数字に挟まれた点とカンマは句読点として扱わない。「１０．５」⇔「10.5」は全角半角としてだけ可)、(3) 日本語の文字・句読点に接する空白、行末の空白、行頭の全角空白(英語の語の間・記号の隣の空白と、行頭の半角の字下げはそのまま比べる)、(4) 全角・半角の ％（）：；！？(ただし `](`・`![`・`]:` になるときは別。リンク・画像・注の定義になるため)。
- 全角半角の変換でも、行頭(空白の後を含む)に Markdown の記号(`:`・`~`・`%`・`#`・`>`・`-`・`+`・`*`・`|`)ができる変換は拒否する。`％`→`%` は、`$…$`・`$$…$$` と raw TeX の行の中では拒否する(TeX では `%` は行コメント)。
- heading はこれに見出しの番号を足す。番号とみなすのは、見出しの先頭の `第N章/節/項`・`N`・`N.N`・`N.N.N` の後に空白が続き、その後が単位(年・年代・つ・個・倍・%・人・件 など)で始まらないときだけ。変えた後の番号は、道具が見出しの段と順番から計算した値と一致するときだけ受理する(AI は値を選べない)。
- citation はこれに「(著者 年)」⇔`[@key]` を足す(references.json の著者の姓と年が一致し、頁・接頭辞・接尾辞の語が同じ。引用の文中の位置も固定)。新しい引用も頁も足せない。
- diagram は front matter の設定行の追加・削除だけで、図の行は一字も変えない。
- NFKC 全体は使わない(㍻→平成、½→12、²→2 のような互換分解を通さないため)。見えない文字・形の似た別の文字は正規形に残るので、足せば必ず違いになる。

### 3.7 プロジェクトの外への書き込み(v1 と同じ)

シェルの起動ファイル(`.bashrc`・`.profile`・`.zshrc`・`.zshenv` ほか、fish・PowerShell のプロファイル)、PATH 上のディレクトリと `~/.local/bin`・`~/bin`、自動起動(`~/.config/autostart`・`~/.config/systemd/user`・LaunchAgents)、`.envrc`、`.vscode/`、`.git/`・`.git` という名のファイル・`~/.gitconfig`・`~/.config/git/`・site-packages・`sitecustomize.py`・`usercustomize.py`・`.pth` への書き込みは、Write・Edit・Bash のすべてで deny。内容が Git や Python の設定の形(`[core]`・`[filter`・`fsmonitor`・`textconv`・`pager`・`sshCommand` など)の Write は場所を問わず ask。これら以外のプロジェクトの外への AI の書き込みは ask(セッションの一時ディレクトリ `$TMPDIR`・`/tmp` は除く。ただしプロジェクト自身がそこにある場合は除外しない)。`./rk` の起動ファイルは PATH から python を探すので、`~/.local/bin/python3` の差し替えを防ぐのが要点である。

### 3.8 Claude Code の設定(v1 と同じ)

`.claude/` と `~/.claude/` への書き込みは全ツールで deny。`./rk check`・SessionStart・人間の段の最初の検査(`./rk setup` を含む)・CI は、`disableAllHooks: true` と、`enabledPlugins` でこの Plugin が false のものをエラーにする(`enabledPlugins` の書式は、`claude plugin disable` が `~/.claude/settings.json` に書いた内容で確かめた。開発時の観察)。削除の場合は設定が残らないので、`./rk check` は最後の SessionStart の記録の日付を出す。

### 3.9 コメントと追記だけの記録

すべてのコメントと返信に経路(`notebook` = 画面で入力・本人確認なし、`tty` = 端末の取り込み、`agent-cli` = AI の道具)を記録して表示する。AI の道具からは必ず AI の名義で、確度は「要確認」。画面の API からのコメントは学生の名義だけ(指導教員の名義は 403。保管の層でも、指導教員の名義は端末の取り込みだけ)、表示と `annot list` に「本人確認なし」。作成・返信・解決・再オープンは `review/annotations-log.jsonl` に追記し(道具はコメントを消さない)、記録にあって annotations.json に無いコメントは `rk check` の NG。AI のコメントに書き換えの文の欄は無い。

### 3.10 一括の記録

鍵を作る前に(署名が要る項目があるときだけ鍵を作る)、採用する hunk を原稿ごとに順に記憶の中で当て、位置を特定できないもの(原稿が変わった、同じ一括の別の提案が同じ行を変えた)と、同じ一括で採用する提案が変える節の確認を「記録しない」に分け、理由をつけて返す。結果は項目ごと(記録した・しなかった・失敗・未処理)で、画面は記録した項目を一覧から外す。位置を特定できない提案は一覧で「作り直しが要る」と出し、不採用しか選べない。

### 3.11 主張カードと検証の機械の部分

- 主張カードの形式は `rklib/claimcards.py` が読む(節の名前は日英どちらでもよい)。確認のダイジェストは、主張・範囲・学生の言葉の原文と、`[ai_suggested]` の印のないすべての要素を覆う。AI の候補を書き換えても確認は古くならないが、印を外して学生の要素に見せかけると古くなる。学生の言葉の原文に印があるもの、主張そのものに印があるものは形式の誤り。
- 機械の照合(`rklib/verification.py`)は判断ではなく候補で、claim-verifier が一件ずつ残すか退けるかを理由つきで書く:
  - **すり替えの候補**(AI が書いた段落と、その材料の主張カード): カードにない強める語(「必ず」「唯一」「all」「prove」など)、カードの限定の語(「一因」「可能性」「may」など)が段落にない、増減の向きの語が逆、カードの範囲の数字・年が段落にない。すべて「致命」の候補。材料の主張カードが無い、確認されていない、記録されていない場合も出す。
  - **根拠の対応**: 段落の引用キーごとに台帳の状態(IDENTITY_CONFIRMED 未満は「重要」、台帳にないものも「重要」)、保存した抜粋(`excerpts/` の 1 行目 `source_id:`)の有無(無ければ「未照合」)。AI が書いた段落の、引用もデータの参照もない断定的な事実の文(数字か事実の語があり、意見・限定の語がない文)は「重要」。
  - **出典のない数字**: 単位つきの数(%・割・倍・人・件・円・万・億など)と小数で、段落にも脚注にも引用・`data/raw|processed/…` の参照がなく、`data/numeric-claims.csv` にも無いもの(検証では「軽微」。`rk check` では下書きで注意、提出の段階でエラー。`lint` は一覧に出す)。
- 検証のファイルの形の検査(`verification lint`): 指摘の行の重大度(致命・重要・軽微、fatal・major・minor)、観点(論理・根拠の対応・反証・新規性・すり替え、または taxonomy のコード)、`/ 根拠:` の有無。「支える」と書いた行は `excerpts/` を根拠に示すこと。4 節で新規性を断定していれば、検索の範囲の明記を求める。0 節に致命の候補があるのに 5 節が空なら注意。3 節は `--purpose counter` の検索記録の id か「検索していない」を求める(注意)。
- 書き込みの直後(PostToolUse)に、変わったファイルの機械の照合を最大 12 行まで文脈として返す。Stop のフックは、そのターンに原稿への書き込みがあり、検証やサブエージェントを使っていなければ、一度だけ結果を学生に示すよう促す。

### 3.12 敵対的な検証で見つかった欠陥と、その閉じ方

独立した敵対的な検証で見つかった欠陥と、今の閉じ方。再現は `tests/test_v2.Hardening`・`tests/test_sources_and_windows.py`・`tests/test_bibliography_and_shell.py` にある。点の修正では収まらなかったもの(文献一覧の中身、条件つきの `cd`、窓の記録の競合、数字)は、構造で閉じ直した(下の各項)。

- **シェルの書き込みの判定を、解析した後のパスで行う。** `echo x >> man\uscript/main.md`(bash は `manuscript/main.md` と読む)、`cd m?nuscript && echo … >> main.md`、`cd .r?ukoku && echo … >> signoffs.jsonl`、`cd .[r]yukoku`、`cd th?nking`、`cd res?arch && echo x > q\uestions.md` が確認なしで通っていた。原因は、`execgate` が glob を含む `cd` の行き先を追わずに「プロジェクトの中へのリダイレクト」を許していたことと、`pre-guard.sh` が `\` を `/` に置き換えた文字列に正規表現をかけていたこと。修正の後は: `cd` の glob は bash と同じに展開し、ちょうど一つのディレクトリに当たれば追う。変数・`cd -`・解けない glob の `cd` の後は「行き先不明」とし、その後の相対の書き込み先は不明(確認。`prohibited` と、記録のファイルの名前なら deny)、相対パスのコードの実行は確認にする。リダイレクトと書き込みのコマンド(`cp`・`mv`・`tee`・`rm`・`ln`・`sed -i`・`pandoc -o` など)の書き込み先を、字句解析で解いた後に `rklib/paths.py`(`lib.sh` の `path_class` と同じ分類。試験が一致を確かめる)で分類し、守られた場所なら `protected_write` としてフックが deny する。 **条件つきの `cd`**: `cd m?nuscript || cd ../research; echo … >> main.md` のように、`||` の後の `cd` を無条件に当てはめていたため、追った行き先と bash の行き先がずれ、原稿・`.ryukoku/config.yml`・`thinking/` にリダイレクトが届いていた(設定を書き換えて `ai_policy` を `allowed` にできた)。今は、`cd`・`pushd`・`popd` を、bash が確実に通る位置(文の始め、`;`・改行・`&` の後、文の始めからの `&&` の続き。パイプの中と裏に回すものを除く)にあるときだけ追い、それ以外の位置(`||` の後、パイプ、`&`、制御の語の後、`env cd` などの引数)と、存在しない行き先・`CDPATH` が効きうる相対の行き先の後は、コマンドの残り全部で行き先を不明にする(書き込みは `prohibited` と設定を信用できないときに deny、ほかは確認。記録のファイル名なら deny)。解析しない形(サブシェルなど)に書き込みの形があれば、書き込み先は不明として同じに扱う。さらに、AI のツールの実行中に `.ryukoku/config.yml` が変わった検知を学生がまだ判断していないあいだは、設定を「読めない」とみなして原稿への書き込みを止める(`msguard.config_detections_open` を `config_problems` が見る)。
- **AI のツールの実行中の、追記の形の偽造を見つける**(§3.2)。
- **証拠ノートの鍵。** 画面の API に鍵が無く、`/api/view` の表示の証を読めば誰でも軽い確認を記録できた。修正の後は、サーバーが起動のたびに鍵を作り、`/api/` のすべての要求に `X-RK-Session` の一致を求める。鍵はどの API も返さず、標準出力にもファイルにも書かず、学生の端末(`/dev/tty`)にだけ URL の断片 `#k=…` として出す(ブラウザは断片をサーバーに送らない)。画面はそれを sessionStorage に置き、アドレス欄から消す。端末の無いところ(AI のツールの呼び出し)では、サーバーは起動を断る。このため、画面は学生が `./rk notebook` で開くものになった(以前は AI が起動していた)。フックは、ループバック(`127.x`・`localhost`・`[::1]`・`0x7f000001`・`2130706433` など)の `/api/` への呼び出しと、`nc` などでのループバックへの接続も deny する。限界: 同じ利用者の権限で動くプログラムは、端末の出力やブラウザの保存域から鍵を読める、または自分でサーバーを立てて記録を書ける(学生が許可した実行は何でもできる)。鍵が止めるのは、確認なしで通るコマンドからの要求である。
- **人間専用のコマンドの一覧を一つにする。** `scripts/rk/human-commands.txt` を、`rk.py`・`execgate`・`pre-guard.sh`(Python が無いときの文字列の照合)が読む。`--project P confirm` のように、サブコマンドの前にオプションがある形も照合する。
- **引用の取り出し**: `@{key}`・`nocite` を読み、提出の段階の検査と書き出しで、引く文献のすべてに台帳と IDENTITY_CONFIRMED を求める(識別子の無い資料は識別子を足すか、引けない)。
- **数字(構造で閉じ直した)**: 単位の一覧に当たるものだけを数える方式では、かな・漢字の後の数字、`320冊`・`45分`・`n=350`・`250 respondents`・`3分の1`・`数百人` などが漏れ、`ISO 27001`・`(2.3) より`・`2回目` などを誤って数えていた。今は、本文のすべての数(算用数字と、助数詞の付く漢数字)を候補にし、短い除外の一覧(年と年の範囲、日付と時刻、図・表・式・節・章・問・頁の参照、版、ISO・JIS・RFC などの規格の番号、序数(第N・N回目・N番目・Nつ目・N人ずつ)、行頭の番号、見出し・コード・数式・URL・引用キー・データのパス・HTML の注釈の中)だけを外す。出典は**文ごと**に見る: その文(と文が指す脚注)に、注釈やコードの外の引用キーか、実在するデータのファイルへの参照があるとき。`data/numeric-claims.csv` に載った数と、学生が端末の `./rk figures` で「出典は要らない」と印を付けた数(軽い確認。文のハッシュに結びつき、文が変わると外れる。`.ryukoku/signoffs.jsonl` に入り、AI は書けない)は数えない。言葉で書いた数(「三つ」「three」「半数」)は漏れる。表(`|` で始まる段落)は見ない。
- **窓の記録の競合(構造で閉じ直した)**: `msguard.pre`・`post` が `open.json` をロックなしで読み書きしていたため、並行したツールの呼び出しで窓が消え、次の `pre` が AI の変化を学生の編集として記録していた。今は、窓の記録の読み書き(`open.json`・`windows/`・`baseline.json`)の全体を排他のロック(POSIX は `fcntl.flock`、Windows は `msvcrt.locking`、どちらも無ければ O_EXCL のロックファイル)で囲む。窓が無いと判断する前に `windows/*.json` の残りも見て、残りがあれば、その間の変化を「AI の可能性」(uncertain)として記録する。並行の負荷の試験がある。
- **道具の入力のパス**: `tool_input_paths` は `"key": "value"` の形しか見ず、`{"paths": [...]}` のような配列の中のパスを見落とし、`command` を持つ知らない道具はシェルとしてだけ見ていた。今は `hookcore toolpaths` が入力を JSON として読み、すべての文字列の葉を見る。`command` とパスの欄の両方を持つ道具は両方を見る。相対パスは行き先が分からないので確認(`prohibited` と設定を信用できないときは deny)。
- **`export --file`**: `manuscript/` の外のファイル(見本)は、出力の名前に `-sample` を付け、警告を出す。文献一覧はそれでも台帳から作り、文書の中の差し替えの指定は拒む。
- **漢字・かなの引用キー**: `[@山田2020]` が引用として読まれず、提出の検査を通り、pandoc はその文献を出していた(キーの読み取りが ASCII で始まるキーだけだった)。今は pandoc の規則(Unicode の英字・数字・`_` で始まり、`:.#$%&-+?<>~/` は中にだけ)で読み、提出の段階の検査と書き出しでは `pandoc -f markdown -t json` の Cite もあわせる(和集合)。番号つきの例のラベル `(@ex)` は引用に数えない(pandoc と同じ)。この読み方は、入っている pandoc と同じ結果になることを試験で確かめている。
- **出る文献の中身(構造で閉じ直した)**: 出る項目を台帳と比べる方式では、本文の途中の YAML の塊(pandoc は front matter に限らず読む)の `references:` が同じ id の項目を差し替え、`nocite: '@*'` で偽の項目を足し、`csl:` も効いていた。比べ方も浅かった(著者の姓の部分一致、編者で著者の代わり、前方一致の題名、項目にだけある DOI、誌名・日付を見ない、空の台帳の行は何にでも一致)。今は、**書き出しが pandoc に渡す文献一覧を台帳から作る**(`citations.csl_items`): IDENTITY_CONFIRMED の行だけ、欄は機械の照合が登録機関から記録したもの(`sources/identity.json`。`rk.py refcheck check` だけが書き、AI の道具からは書けない。Crossref・DataCite は題名・著者・編者・年・誌名・出版者・巻号頁・種類、CiNii・NDL は一致した題名)を優先し、記録の無い欄(CiNii・NDL の著者・年など)は台帳の行の値(AI の道具から直接は書けず、提出の段階では学生の VERIFIED の署名が覆う)。題名と名前(著者・編者・発行者)の無い行はエラー。作った CSL JSON は作業フォルダの一時ファイルで、唯一の文献一覧として渡し、自分で作る defaults で `bibliography`・`csl`(pandoc/ の中の CSL か pandoc の既定)・`metadata.references: []` を固定する(文書の中の値はこれで上書きされることを、入っている pandoc で試験した)。`sources/references.json` は pandoc に渡さず、`rk check` が台帳との違いを知らせるだけ(`entry_mismatches` は正規化した完全一致の比較で、情報として出すだけ)。文書の中のメタデータは、全ファイルをつないだものを pandoc の JSON の `meta` で読み(pandoc が無いときは、どこにあってもその行を探す)、`references`・`bibliography`・`csl`・`citation-style`・`citation-abbreviations` があれば書き出しと提出の検査のエラー(`link-citations` などは可)。TeX・OpenXML・HTML の生のブロックで文献一覧を作る形(`\\bibitem`・`thebibliography`・`BIBLIOGRAPHY` の欄など)も同じ。`nocite: '@*'` の出す範囲は、IDENTITY_CONFIRMED の台帳の行すべて。`pandoc/` は AI が書けず、学生が変えたら確認まで書き出しが止まる。
- **設定の読み方の食い違い**: Shift_JIS で保存した設定では、フックが原稿への書き込みを通し、`rk check` は「読めない」と言っていた。値の後のノーブレークスペースでは逆だった。今は判定を一つにした(§3.1)。
- **CI と Git フック**: AI の書き込みが確認だった。今は deny(§3.1)。
- **ループバックの別の書き方**: `localhost.localdomain`・`0x7f.1`・`[::ffff:7f00:1]` が確認だけだった。今は `execgate.loopback_targets` が、URL・`host:port`・curl の `--resolve`/`--connect-to`・`nc` などの引数のホストを、`inet_aton` と `ipaddress` の読み方で解き、決まった名前と hosts ファイルの名前で照らす(DNS は引かない)。
- **重なった呼び出し**: §3.2。
- **Windows の端末**: 鍵つきの URL を標準出力に出していた。今は `CONOUT$` に書き、開けなければ起動しない(`sign.tty_print`)。端末の入力も `CONIN$` から読む。
- **省略したオプション**: `rk.py` を `allow_abbrev=False` にし(`--proj` は `--project` にならない)、`execgate` は `--project` の省略形の後の値を飛ばしてサブコマンドを読む。

## 4. 脅威モデルと限界

| 相手 | 例 | この Plugin で |
|---|---|---|
| 取り違え・事故 | 科目が禁止なのに AI が原稿を書く。台帳を VERIFIED にする | 原稿は科目の条件でフックが止め(シェルの書き込みは解析した後のパスで判定)、すり抜けた書き込みも由来に残って検査が落ちる。署名のない VERIFIED は検査が落ちる |
| 主張のすり替え | AI の文が学生の主張より強い・広い・逆を言う | 材料の主張カードと照らす機械の照合が「致命」の候補を出し、claim-verifier が確かめる。**語の一覧による候補で、言い換えた強調は漏れる** |
| 捏造 | 記憶から文献・数字を足す | 材料の指定は台帳とデータにあるものだけ。台帳にない・未確認の引用は提出の段階で落ちる。出典のない数字は注意。**台帳に入った実在の文献を、支えない主張に引くこと**は、抜粋があれば照合できるが、抜粋が無ければ「未照合」までしか言えない |
| 指示に従った回り道 | 変数の連結・base64・スクリプトのファイル・patch・tar で原稿や記録を書く | 原稿なら由来に残る(禁止の科目では検査が落ちる)。記録・道具なら検知に残り、判断まで検査と CI が落ちる。多くは許可リストの外なので実行の前に確認が出る |
| 人間の確認の偽造 | スクリプトで署名者を足して署名する、確認の記録を書く、PR で検査のコードを無効にする | 信頼されない署名者は落ちる(ローカル・CI)。AI の窓の中に現れた確認は検知。CI は基準ブランチの道具で検査する。**窓の外で、学生が許したプログラムが書いた軽い確認は区別できない** |
| 合言葉の横取り | 合言葉を受け取るコードの差し替え、`plugin-root` の書き換え、偽の画面 | v1 と同じ(場所と版を出し、記録と MANIFEST に照らす。偽のコード自身はこの確認をしないので、同じ利用者の権限のプログラムには止められない) |
| 同じ利用者の権限のプログラム | Plugin の写しと MANIFEST を作る、信頼の起点・控え・連鎖を作り直す、`disableAllHooks` を書く、ツールの外で後から書き込む | **止められない。** 痕跡を残す。ツールの外の書き込みは学生の編集(推定)として由来に残る |
| 合言葉の漏えい・総当たり | v1 と同じ | v1 と同じ |
| 学生自身 | 読まずに確認・署名する。AI の文を読まずに出す | 止めない。由来の記録と開示文が事実を残し、最終確認の画面は由来と開示文を見せる |

その他の限界:
- 由来の記録は、フックの強さまでのものである。フックが止まっている間、フックの外で動くプログラム、学生が許可したプログラムの書き込みは、記録が誤るか残らない。学生が許可したプログラムは学生の権限で何でもできる(記録を作り直す、Plugin のコードを呼んで「Plugin が書いた行」にする、画面の鍵を読む)。
- 学生の編集の帰属は推定である。AI のツールが動いている間に学生がエディタで保存した変更は、AI の書き込みとして記録される(v1 では誤検知の警報だった。v2 では記録が誤る)。逆に、ツールの外の書き込みは学生の編集に見える。
- 段落の対応は、空行で区切ったまとまりの並びの比較による。段落を分けたり合わせたりすると、記録の上では削除と挿入になる。
- 実行の照合は許可リストなので、AI が書いたファイルの一覧は理由文の強さだけに使う。make・npm の scripts・Git のフックなど、間接に実行される設定は照合しない。
- Claude Code の設定でフックが止まっている間は、何も止めず記録もしない。後で検査が設定を見つけるが、止まっていた間の出来事は分からない(由来も残らない)。
- GitHub の `pull_request` のワークフローが PR の側で書き換えた定義で動くかは未確認。
- 執筆の依頼や問いの代行の依頼の検知は語彙による補助で、言い回しを変えると漏れる。
- Windows では /dev/tty が無いので、人間用のコマンドは isatty と `CONIN$`・`CONOUT$` に頼る(実機では確かめていない)。
- 人間用のコマンドの端末の確認は、人がいることの証明ではない。開発時の観察: Linux の Claude Code 2.1.318 で、`-p` のモードと対話のモード(疑似端末の上で起動)のどちらでも、Bash の道具の子プロセスは別のセッションで動き、制御端末を持たず、`/dev/tty` を開くと ENXIO になった(SELF-ASSESSMENT.md §2.3)。ほかの版・OS では確かめていない。疑似端末を自分で作るプログラムは端末に見せかけられる(AI の使い方はフックが止めるが、学生が許可したプログラムは止まらない)。偽れば未確認のものが確認済みになる二つの判断だけを、合言葉の署名にしている。
- 文献一覧は台帳から作るが、CiNii・NDL で確かめた資料の著者・年などは、機械の照合が記録していないので台帳の行の値になる(台帳は AI の道具から直接は書けず、提出の段階では学生の VERIFIED の署名が覆う)。普通の文で打った文献の一覧や地の文の「著者(年)」は、機械では照合できない。
- 数字の検査は除外の一覧による推定で、言葉で書いた数は漏れ、出典の要らない数も数える(学生が `./rk figures` で印を付ける)。
- シェルの書き込みの事前の判定は、見分けられる書き方だけである。ほかの書き方は確認に回し、動いた後の変化を記録する。

## 5. 外部のプログラム: 何を読み、どう閉じたか

外部のプログラムが、AI の書けた設定ファイルを読んで別のプログラムを動かすことがある。個別の経路ではなく、設定を読む道具をまとめて閉じた。

| 道具 | 読む設定・環境 | AI が書けるか | どう閉じたか |
|---|---|---|---|
| git | `<repo>/.git/config`(fsmonitor・pager・sshCommand・hooksPath・diff.external・filter.process など) | `.git/` は deny。別の場所に偽のリポジトリを置くことはできる | 確認なしで通すのは、使うリポジトリがプロジェクト自身の `.git` ディレクトリのときだけ。`rk.py` 自身の git は、`<proj>/.git` がディレクトリのときだけ、GIT_DIR・GIT_WORK_TREE を明示し、コードを動かす設定(fsmonitor・pager・sshCommand・hooksPath・diff.external・protocol.ext)を `-c` で無効にして実行する(`common.run_git`) |
| pandoc | `--defaults`(filters・lua-filter・template、`from`/`to` に書いたファイル名の Lua のリーダ・ライタ)、作業ディレクトリ、`pandoc/` の設定 | `pandoc/` とプロジェクトに書ける | `export` はプロジェクトの defaults をそのまま渡さず、許可した項目(`from`・`to`・`standalone`・`reference-doc`・`citeproc`・`bibliography`・`csl`・`metadata.lang`・`variables` の documentclass/papersize/fontsize・`pdf-engine` は lualatex/xelatex)だけを Plugin が組み立てた一時の defaults に写す(`export.sanitize_defaults`)。`from`/`to` は組み込みの形式名と拡張(`+name`・`-name`)だけ。ブロック形式でない YAML(`metadata: {…}` など)は理由つきで拒否する。`./rk check` も同じ判定で NG にし(`export.defaults_problems`)、`pandoc/` を監視する |
| lualatex(PDF) | TeX の設定、`\write18`(shell-escape)、作業ディレクトリの .sty・.cls・.tex、テンプレートに入る変数の値 | プロジェクトに .sty・.cls を置ける。defaults の変数に TeX の命令を書ける | pdf-engine は lualatex/xelatex だけ。pdf-engine-opt は拒否。作業ディレクトリはプロジェクトの外。documentclass は決まった名前(ltjsarticle・ltjsreport・ltjsbook・jlreq・article・report・book)だけ、そのほかの値は TeX の制御文字(`\`・`{}`・`%` など)を含むものを拒否 |
| mmdc(Mermaid) | puppeteer の設定(作業ディレクトリから上へ探す `.puppeteerrc*` など。開発時の観察: 独立検証の検証者のコードの読み) | プロジェクトに置ける | 作業ディレクトリをプロジェクトの外(状態フォルダの下。AI の書き込みは deny)にした。その上のホームに置くことは「プロジェクトの外への書き込み」で ask。mmdc の実行は開発した環境では未確認 |
| python(同梱の rk.py) | `PYTHONPATH`・`sitecustomize`・`.pth` | site-packages などは deny | これらへの書き込みを deny。`PYTHONPATH=` などの代入付きの起動は ask |

書き出しの写し・図・Plugin が組み立てた defaults は、状態フォルダ(プロジェクトの外)の下の新しい一時フォルダに置き、そこで pandoc と mmdc を動かす。できた出力と図だけを `build/` に写し、一時フォルダは消す。`reference-doc`・`bibliography`・`csl` は、プロジェクトの中の決まった拡張子のファイルだけを絶対パスにして渡す。`build/` に置かれたリンクはたどらない(消してから書く)。

## 6. 主な設計の選択と、採らなかった案

v2 で採ったもの:
- **原稿への書き込みは科目の条件で決め、書き込みは記録にする。** 一律の deny は学生を縛り、ask だけでは何が書かれたかが残らない。allowed は通して由来を残し、limited と unknown は書く前に確かめさせ、prohibited は止める。
- **シェルからの原稿への書き込みは、条件にかかわらず止める。** Write・Edit なら書く前に対象が分かり、科目の条件の確認と段落の差分が確実に働く。シェルの書き込みは事前に読み切れない。すり抜けたものは由来に残す。
- **原稿の変化は検知でなく由来にする。** v1 では「AI の変更」はすべて警報で、学生が署名して判断するまで検査が落ちた。v2 では AI が書いてよい場所なので、警報は学生の手間を増やすだけで、守るものがない。代わりに段落ごとに残して開示の事実にする。禁止の科目でだけ検査に結びつける。
- **署名は VERIFIED と最終確認の二つに絞る。** 偽れば未確認の文献が確認済みとして通る(VERIFIED)、提出物と開示が正しいという宣言が成り立たない(最終確認)、の二つだけを、AI が装えない署名にした。ほかは v1 のフックと窓の検知で十分に守れ、署名の手間に見合わない。
- **主張カードの「学生の確認」は、記録を正とし、ファイルの表示は従とする。** ファイルの `status` は AI が書ける場所にあるので、記録と食い違えばエラーにする。
- **機械の照合は候補を出すだけにし、判断は検証の文に任せる。** 語の一覧で主張のすり替えを判定すると、誤検知と見逃しの両方が多い。致命の候補として必ず目に入れ、claim-verifier に一件ずつ理由つきで扱わせる。
- **材料の指定は書き込みの前に道具で記録する。** 原稿の中に印を埋め込む案は、提出物を汚し、学生が消すと由来が切れる。道具の記録なら、確認されていないカードや台帳にない文献を材料にしようとした時点で止められる。
- **学生の編集は差分から推定し、推定と書く。** 本人の編集を確かめる手段はない。確かめたふりをしない。

v1 から引き継いだもの(理由は v1 と同じ):
- 提案と実行の照合は、どちらも拒否リストでなく許可リストにする。
- 信頼の起点と検知の基準はプロジェクトの外(`~/.ryukoku-writing`、`RK_STATE_HOME` で変更可)に置く。
- 一括の採用・却下の操作は置かない(各項目は表示してからでないと選べない)。
- 起動ファイルに Plugin の場所を書き込まない。Claude Code の Plugin の一覧のファイルに依存しない。

採らなかった案と理由:
- **すべての判断を署名のままにする**: v1 の形。手間が大きく、学生が読まずに署名する方向に働く。守るものの大きさで分けた。
- **原稿への書き込みを常に ask にする**: 毎回の確認は読まずに押されやすい。科目が allowed と記録されていれば、確認の代わりに記録を残すほうが正直である。
- **すり替えを道具で断定してエラーにする**: 語の一覧では誤りが多く、正しい文を書けなくなる。候補として出し、検証で扱う。
- **由来の記録に段落の本文を入れる**: 公開リポジトリに原稿の写しが二重に残る。ハッシュと行の範囲だけにした(本文の控えはプロジェクトの外)。
- **学生の編集を AI の窓の外のすべての変化として断定する**: 区別できないので、推定として記録する。
- **確認コードや HMAC、画面の PIN と Cookie を軽い確認の裏づけにする**: 秘密がディスクにあり、ファイルを読める AI が偽造できる。守りを足さずに手間だけが増える(v1 の判断と同じ)。
- **prohibited で読み取りも止める**(v1): 検証と形式の確認ができなくなる。v2 の指示(検証・調査・形式の確認は可)に合わせた。
- **Mermaid の timeline 図、ISBN-10 の検査、JaLC の API、NDL の isbn 索引、gh でリポジトリを作る自動化**: v1 と同じく、一次資料・実際の動作で確かめていない(未確認)ので実装しない。
- **全角・半角の照合に NFKC 全体を使う**: 互換分解で内容が変わる(㍻→平成、½→12)。

## 7. 事実の出典

確認日は特記が無ければ 2026-11-04。サービスの条件や頁は変わることがある。

| 事実 | 資料 |
|---|---|
| ガイドラインの節ごとの要点(Ⅱ-2(1) オプトアウトと個人情報、Ⅱ-2(2) 真偽の確認、Ⅲ-1、Ⅲ-3 科目の指示、Ⅲ-4 自分の成果物としないことと開示の項目の例、Ⅳ 見直し) | 龍谷大学「龍谷大学における生成AIの活用に関する学生向けガイドライン」(2025-11-14)、https://www.ryukoku.ac.jp/nc/media-download/1515/9251a94ef847cc36/ 。取得日と SHA-256 は README に記載(開発時に計算) |
| 龍谷大学の研究不正の五類型(捏造・改ざん・盗用・二重投稿・不適切なオーサーシップ) | 龍谷大学「研究活動に係る不正行為の防止及び対応に関する規程」第2条(1)、https://www.kenkyubu.ryukoku.ac.jp/cms/wp-content/uploads/2025/07/9f6a9c168ad42361b5b6225d988e7ebd.pdf |
| 人文・社会科学では盗用が特に多い(Ⅲ-5.3)、引用の要件と明瞭区別性・主従関係(Ⅳ-5.4.1) | 日本学術振興会『科学の健全な発展のために — 誠実な科学者の心得 —』第2版(2025-09)、https://www.jsps.go.jp/file/storage/j-kousei/data/rinri.pdf |
| 引用(32条)と出所の明示(48条) | 著作権法(昭和四十五年法律第四十八号)、e-Gov、https://laws.e-gov.go.jp/law/345AC0000000048 |
| 国の表記の基準は専門分野の表記を拘束しない | 常用漢字表(平成22年内閣告示第2号)前書き、https://www.bunka.go.jp/kokugo_nihongo/sisaku/joho/joho/kijun/naikaku/pdf/joyokanjihyo_20101130.pdf 。「公用文作成の考え方」(文化審議会建議、2022)、https://www.bunka.go.jp/seisaku/bunkashingikai/kokugo/hokoku/pdf/93731901_01.pdf |
| 龍谷大学図書館: OPAC、R-OCEAN の対象外(CiNii Books・CiNii Research の一部・SciFinder)、データベース一覧 247 件と一覧にない DB、学認・リモートアクセス、他大学図書館の利用、レファレンス・メールレファレンス | OPAC https://opac.ryukoku.ac.jp/iwjs0005opc/cattab.do 、R-OCEAN https://library.ryukoku.ac.jp/Search/page_id72 、データベース一覧 https://opac.ryukoku.ac.jp/iwjs0005opc/ermssrh.do?words= 、学外からの利用 https://library.ryukoku.ac.jp/page_id90 、他大学図書館 https://library.ryukoku.ac.jp/Service/page_id51 、レファレンス https://library.ryukoku.ac.jp/Service/page_id57 、メールレファレンス https://library.ryukoku.ac.jp/Service/page_id58 |
| ライティングサポートセンター(答えを教えたり押しつけたりしない方針) | https://www.ryukoku.ac.jp/writingsupport/about/ |
| 卒論の規程は学部と入学年度で違い、多くの学部が Word・A4 で manaba に提出する。経済学部の要項の要約(tests/fixtures) | 履修要項Webサイト https://rishu.ryukoku.ac.jp/ (2026年度入学生の頁)、経済学部 https://rishu.ryukoku.ac.jp/curriculum/faculty-econ/s04 、manaba course https://www.ryukoku.ac.jp/campus_career/media/e_learning/ |
| CiNii Research の appid が必須、CiNii ウェブ API の登録 | https://support.nii.ac.jp/ja/cir/r_opensearch 、https://support.nii.ac.jp/ja/cinii/api/developer |
| NDL サーチの SRU・CQL・DC-NDL、同時接続の制限 | 「API仕様の概要」https://ndlsearch.ndl.go.jp/help/api/specifications 、「API利用について」https://ndlsearch.ndl.go.jp/help/api 。HTTP 429 は開発時の観察 |
| J-STAGE WebAPI: 24 時間以上の保存の禁止(第3条5項)、"Powered by J-STAGE"(第9条) | J-STAGE WebAPI 利用規約、https://www.jstage.jst.go.jp/static/pages/WebAPI/-char/ja 。`service=3` の応答の形は開発時の観察 |
| e-Stat の appId、RESAS-API の終了(2025-03-24) | https://www.e-stat.go.jp/api/ 、https://opendata.resas-portal.go.jp/docs/api/v1/index.html |
| Crossref の polite pool | https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/ 。一覧の検索が約 1 回/秒に制限されたのは開発時の観察 |
| DataCite の API と "identified" の制限 | https://support.datacite.org/docs/api 、https://support.datacite.org/docs/rate-limit |
| doi.org の handle API(responseCode 1・100) | DOI resolution documentation、https://www.doi.org/the-identifier/resources/factsheets/doi-resolution-documentation |
| 撤回の情報: updated-by(撤回された側)と update-to(撤回通知の側) | Crossref「Retraction Watch」、https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/ |
| ISBN-13 のチェックディジット。ISBN-10 の算法は同じ文書で見つからず未確認 | ISBN Users' Manual, 6th International Edition(2012)Appendix 1 A1.1、https://www.isbn-international.org/sites/default/files/ISBN%20Manual%202012%20-corr.pdf |
| 生成 AI が実在しない文献を出すことの実証 | Walters & Wilder 2023, Scientific Reports 13:14045, DOI 10.1038/s41598-023-41032-5 |
| pandoc 3.13 は YAML 1.2 で読む(yes/no は文字列) | Pandoc releases、https://pandoc.org/releases.html |
| `east_asian_line_breaks`、`--reference-doc` の作り方、`--track-changes=all`(既定の accept はコメントを捨てる) | Pandoc MANUAL、https://pandoc.org/MANUAL.html (Extension: east_asian_line_breaks、--reference-doc、--track-changes) |
| lang があると pandoc の LaTeX テンプレートは babel を読み込む。babel と jlreq・LuaTeX-ja の組み合わせは未確認 | pandoc templates の common.latex、https://github.com/jgm/pandoc/blob/main/data/templates/common.latex |
| CriticMarkup に pandoc も Quarto も対応していない | Pandoc MANUAL と 3.13 までのリリースノートに "critic" の語が無い(上の URL)。Quarto の文書にも見当たらない |
| pandoc-crossref は pandoc の版と一致させる | pandoc-crossref の README、https://github.com/lierdakil/pandoc-crossref |
| TeX Live の collection-langjapanese(LuaLaTeX + LuaTeX-ja・jlreq を含む) | TeX Live https://tug.org/texlive/ 、tlpdb https://mirror.ctan.org/systems/texlive/tlnet/tlpkg/texlive.tlpdb |
| 原ノ味フォントは TeX Live 2020 以降の既定 | HaranoAjiFonts の README、https://github.com/trueroad/HaranoAjiFonts |
| Mermaid 12 で flowchart の既定(theme・look・layout)が変わり、front matter で固定できる | Mermaid「Flowchart syntax」の "Default theme, look and layout (v12.0.0+)"、https://mermaid.js.org/syntax/flowchart.html |
| mermaid-cli の `mmdc -i … -o …`(SVG・PNG・PDF) | mermaid-cli の README、https://github.com/mermaid-js/mermaid-cli |
| `actions/checkout@v6`・`actions/upload-artifact@v6` | xu-cheng/latex-action の README の例、https://github.com/xu-cheng/latex-action |
| `pandoc/actions/setup@v1`(version の入力) | https://github.com/pandoc/actions |
| 非公開リポジトリのブランチ保護と CODEOWNERS の強制は GitHub Pro 以上 | GitHub Docs「About protected branches」https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches 、「About code owners」https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners |
| 日本語の CSL(SIST02) | https://github.com/citation-style-language/styles/blob/master/sist02.csl |
| Data Package v2、公共データ利用規約(第1.0版、2024-07-05) | https://datapackage.org/standard/data-package/ 、https://www.digital.go.jp/resources/open_data/public_data_license_v1.0 |
| W3C Web Annotation の TextQuoteSelector と TextPositionSelector | https://www.w3.org/TR/annotation-model/ |
| レビューと検証の観点(Toulmin の配置、受容可能性・関連性・十分性)、誤謬名は判定でなく問いの見出し、事例選択の偏り(結果に基づく選択) | SEP「Informal Logic」https://plato.stanford.edu/entries/logic-informal/ 、IEP「Fallacies」https://iep.utm.edu/fallacy/ 、Geddes 1990, Political Analysis 2:131-150, DOI 10.1093/pan/2.1.131 。コード・ラベル・問いは作成者の言い換えで、試行も評定者間の一致の確認もしていない |
| 効くのは誤りとその理由を示し探索の方向を与えるフィードバック | Wisniewski, Zierer & Hattie 2020, Frontiers in Psychology 10:3087, DOI 10.3389/fpsyg.2019.03087 |
| 査読者は著者の論文を自分の好む書き方に書き直そうとしない | COPE, Ethical Guidelines for Peer Reviewers(2013)、DOI 10.24318/cope.2019.1.9 |
| APA・MLA の AI の利用の書き方 | APA「AI Contribution Statement Guide」https://apastyle.apa.org/instructional-aids/ai-contribution-statement.pdf 、MLA「Citing generative AI (updated and revised)」https://style.mla.org/citing-generative-ai-updated-revised/ 。Chicago は読めず未確認 |
| 開発時の観察(Claude Code 2.1.318、この環境) | Claude Code の Bash から `CLAUDE_PLUGIN_DATA`・`CLAUDE_PLUGIN_ROOT` が見えない。`claude -p` の SessionStart に model が来ない(model は transcript から読む)。eval で Bash を許すと、bubblewrap と socat が無いため実行が拒否される。`claude plugin disable` が `~/.claude/settings.json` に `"enabledPlugins": {"<plugin>@<marketplace>": false}` を書く(一時の HOME で観察)。`.claude/settings.local.json` の `disableAllHooks: true` で Plugin のフックが止まる(独立検証で `claude -p` により観察)。Monitor ツールが `command` を受け取る(この環境のツールの定義)。CiNii Books の項目名、NDL の `recordSchema=dcndl` と `creator=` の索引 |
| 未確認 | GitHub の `pull_request` のワークフローが PR の側の定義で動くか(独立検証は、一般的な仕様では動くと指摘)。Windows・macOS の実機、GitHub Actions 上の実行、lualatex による PDF、mmdc による図の画像化。v2 の機械の照合の語の一覧が実際の原稿でどれだけ当たるか |
