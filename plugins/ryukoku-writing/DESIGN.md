# DESIGN — ryukoku-writing 1.0.0

この文書は、この Plugin の設計をまとめる: 中核の考え、要件とその満たし方・試験、守りの仕組み、脅威モデルと限界、外部のプログラムの扱い、採った案と採らなかった案、事実の出典。試験を実際に回した結果と、確かめていない点は [SELF-ASSESSMENT.md](SELF-ASSESSMENT.md) にある。

言葉の使い方:
- **開発時の観察**: 開発した環境(Linux、Claude Code 2.1.318、2026-11-04〜05)で実際に見たこと。公式の文書では確かめていない。
- **未確認**: 一次資料でも実際の動作でも確かめていないこと。
- **独立検証**: 開発の後に、別の検証者が攻撃者の立場で 5 回行った検証。見つかった欠陥は、再現をそのまま回帰の試験にした(`tests/test_round3.py`〜`test_round6.py`、`test_proposals.AllowList`)。

## 1. 中核の考え

**学生が問い・主張・本文を作り、AI は問いかけ・調査・検証・表記の提案だけをする。AI の出力が原稿に入るのは、学生が一件ずつ見て、合言葉で署名したものだけ。人間の判断は署名としてだけ存在し、ローカルでも CI でも照合される。**

三つの層で作る。上ほど早期警告、下ほど骨格である。

| 層 | 何をするか | どこ |
|---|---|---|
| 1. フック(事前) | すべてのツール(matcher `*`)。原稿・`.ryukoku/`・道具・学生の問い・思考の記録・Claude Code の設定・`~/.ryukoku-writing` などへの AI の書き込みを、Write/Edit と Bash・PowerShell・Monitor で deny。人間専用のコマンド、端末の模擬、切り離した実行、画面の API 呼び出し、main への push も deny。**許可リストの外の実行は ask**(確認なしで通すのは Plugin 同梱のコードと読み取りだけの決まったコマンドだけで、解析しきれない書き方も ask)。対象のパスから目印(`.ryukoku/config.yml`)を探し、見つからなければ利用者の登録済みのプロジェクトで窓だけ開く | `scripts/hooks/pre-guard.sh`・`lib.sh`・`rklib/execgate.py` |
| 2. ツール実行の窓の検知 | 読み取り専用でない道具の実行の前後で、原稿と守られているファイルのハッシュを、窓ごとの写しと比べる。変われば検知を AI 利用記録(Git で管理。行ごとに前の行のハッシュ)とプロジェクトの外の控えに書き、学生が署名して判断するまで `rk check` と CI が落ちる。窓の中で変わったファイルは「AI が書いたファイル」として覚える | `rklib/msguard.py`・`ailog.py`・`scripts/hooks/post-log.sh` |
| 3. 署名(骨格) | 人間の状態(VERIFIED・採否・承認・解決・節・提出前・科目条件・オプトアウト・日ごとの概要・検知の判断)は、合言葉から導く Ed25519 鍵の署名つきの記録だけ。記録は内容のダイジェストに結びつく。信頼する署名者は、GitHub では基準ブランチの最初の `signers.json`、Git なしでは利用者ごとの信頼の起点。CI は基準ブランチの道具で検査する | `rklib/sign.py`・`trust.py`・`subjects.py`・`decide.py`・`check.py`、`templates/github/.github/workflows/check.yml` |

フックは正規表現による早期警告で、回り道の多くは事前には止まらない(変数の連結、base64、スクリプトのファイル、patch、tar など)。それを拾うのが層 2 で、人間の確認を装えないようにするのが層 3 である。

学生の手間への答え:
- 端末を開くのは最初の `./rk setup` の一回(合言葉の登録・科目条件・オプトアウト・Git を、一度の合言葉の入力で署名する)。最後に「Claude Code をこのフォルダで開き直す」を必ず表示する。
- 以後の判断は証拠ノートの画面でまとめて行う。項目を「表示」すると、サーバーが内容・ダイジェスト・表示の証(サーバーの秘密による HMAC)を返し、その項目の判断が選べるようになる。選んだものは「署名する項目」にたまり、合言葉を一度入れると、それぞれのダイジェストで署名される。表示していない項目と、表示の後に内容が変わった項目は、サーバーが受け付けない(409)。鍵はその要求が終わると捨てる。**全部採用の操作は画面にも API にも端末にもない**(各項目は表示してからでないと選べない)。
- 画面は AI が起動してよい(何かを成立させるには合言葉が要るため)。フックはコマンドを解析し、実行する `rk.py` の実際の場所がインストールされた Plugin(フックが受け取る `CLAUDE_PLUGIN_ROOT`)でなければ止める。端末と画面は合言葉を求める前に、動いているコードの場所と版を出し、Claude Code が記録した場所と MANIFEST に合わなければ止まる。

## 2. 要件と、その満たし方・確かめ方

| 要件 | どう満たすか | 確かめ方(試験) |
|---|---|---|
| **日本語と英語**: 原稿の言語と講評の言語を別々に選べ、一行で切り替わる | `.ryukoku/config.yml` の `manuscript_lang`(テンプレート・規則・`pandoc/defaults-<lang>-*.yaml`)と `feedback_lang`(フック・画面・`./rk`・スキル・エージェントの応答)。両言語のテンプレートと書き出し設定を常に置く | `test_init_export.Init.test_language_is_one_line`、`test_hooks.Hooks.test_session_start_language_and_notebook_path`、`test_round3.Misc.test_machine_commands_follow_english`、eval `en-rewrite-declined` |
| **GitHub でも Git なしでも運用できる**: 節ごとのブランチ → PR → CI → 人間のレビュー、Git が無ければフォルダの受け渡し | `templates/github/`(基準ブランチの道具で PR を検査する check.yml、build.yml、PR・Issue のテンプレート、`.githooks/pre-commit`・`pre-push`)。`./rk setup` の Git の段で main に最初の commit(信頼の起点)。Git なしは `rk.py bundle` の HANDOFF.md | `test_init_export.Init.test_workflows_parse_and_pin_only_checked_actions`、`test_sign.CI`、`test_init_export.Misc.test_bundle_lists_signers_and_checks` |
| **記法の規則は学部の要項から取り出し、学生が承認したものだけを使う** | `proposals/style-rules.yml`(AI が書く提案)→ 画面か `./rk style` で署名して承認 → `.ryukoku/style.yml`。署名の裏づけがない規則は適用しない。手順は `skills/style-extract` | `test_proposals.StyleExtraction`、`test_hooks.PreToolUse.test_protected_files_all_tools` |
| **ローカルの HTML 画面で読み、判断できる**(外部への通信なし) | `scripts/rk/notebook/`(CDN なし、127.0.0.1、Host/Origin/独自ヘッダの検査、ARIA のタブと矢印キー、ダークモード)。注釈は W3C Web Annotation の TextQuoteSelector と TextPositionSelector(`review/anchor.py`・`store.py`) | `test_notebook` 全体、Playwright の `tests/js/notebook.test.js` |
| **Claude Code の Plugin として動く**: macOS の bash 3.2・Linux・Windows の Git Bash、jq なし、Python が無ければ機能を落として知らせる | skills 21・agents 4・フック 5 種・scripts。フックは bash 3.2 の構文だけ | `bash tests/run.sh` の構文と移植性の検査、`test_init_export.Init.test_validate_strict`、`test_round3.Portability` |
| **龍谷大学のガイドラインに沿う**: 代筆しない、個人情報を送らない、真偽を確かめる、科目の条件に従う、利用を隠さない、改訂を確かめる | 代筆・問いの代行の依頼への文脈の注入(prompt-guard)、原稿への書き込みの禁止、開示の 4 項目の事実(`./rk facts`)、科目条件で道具の動作を変える(policy_gate)、個人情報の送信停止、真偽の確認の手順、紙の資料、`guideline-check` | `test_hooks.Prompts`・`Policy`、`test_round3.Misc.test_disclosure_suggestion_states_only_facts`、`test_proposals.Flow` |
| **公開できる**: 非公式であることの表示、校章を使わない、ガイドラインの原文を転載しない、公開しない語を含まない、実在しそうな個人情報を含まない | README の注記、LICENSE(MIT)、ガイドラインは節番号つきの言い換えだけ、テスト・eval・テンプレート・例文の題材は記号(「現象 X」「要因 A」)だけ。公開しない語の一覧はリポジトリに置かず、手元の一覧で試験する | `test_init_export.Init.test_no_private_terms_anywhere`・`test_no_guideline_text_copied`・`test_no_real_looking_personal_data_in_package` |
| **人間のレビューが厳密である**: 提出物に入る AI の変更は、学生が一件ずつ見て署名したものだけ。人間の確認を AI が装えない | 二段の状態(機械の `machine_*` と署名つきの `human_*`)、Ed25519 の署名、基準ブランチの信頼の起点、提案の一件ずつの採否、節ごとの署名と提出前の記録 | `test_sign` 全体、`test_detect` 全体、`test_notebook`、`test_proposals` |
| **文献の実在を機械で確かめ、原典が主張を支えるかは人間が確かめる** | `rklib/refcheck.py`(DOI → doi.org → Crossref → DataCite、撤回の印、NCID → CiNii Books、CRID → CiNii Research、NDL ID → NDL サーチ)、台帳、`sources/verification-log.jsonl`。VERIFIED は書かない | `test_research.Verifier`(実通信は `RK_NET_TESTS=1`) |
| **資源の推薦は「読む候補」だけ**: 実在確認を経たもの、龍谷大学図書館の資源は確かめたものだけ | `skills/resource-recommendation`(IDENTITY_CONFIRMED だけを候補に、撤回は別の一覧、紙の資料)、`agents/research-scout` | スキルの記述を一次資料と照合した(§7)。機械の試験は無い |
| **研究データを保存し、後で誰でも確かめられる** | `rklib/datacheck.py`(raw は変えない、sha256 の manifest、来歴、Data Package v2)、raw への書き込みの deny | `test_hooks.PreToolUse.test_direct_writes_and_pushes_to_main`(raw への書き込み)、`test_init_export.Init.test_fresh_project_passes_every_check`(`data verify`) |
| **数式・図・表・脚注・相互参照を書け、Word・PDF・LaTeX に書き出せる** | `templates/{ja,en}/examples/format-examples.md`(数式、論証図・因果図・研究の流れ・年表・概念図の 5 種を front matter で固定、表、脚注、相互参照)、`rklib/export.py`、reference.docx を初期化で生成、PDF・LaTeX の設定に lang を置かない | `test_init_export.Init.test_docx_and_latex_both_languages`、`test_round5.PandocDefaults`、`test_round6` |
| **調査は学生の問いに結びつき、検索ごとに記録が残る** | research-plan → research-run(サブエージェント並列、NDL は一つずつ+ロック)→ verify-sources → research-report。`rk.py search` は問いの番号が `research/questions.md` に無ければ通信せずに終了コード 2、実行のたびに記録、`--purpose counter`。WebSearch と DB の検索 URL への WebFetch もフックが自動で記録 | `test_research.Questions`、`test_hooks.Research`、eval `search-log-recorded`、`claude -p` での実発火 |
| **問い・主張・結論は学生が立てる** | rq-dialogue、argument-map(逐語の引用を道具が照合)、learning-protection、thinking-log、`research/questions.md` と `thinking/` は AI の書き込み禁止、判断の依頼には「まず学生の考え」を注入 | `test_hooks.Research.test_questions_and_thinking_are_the_students`、`test_hooks.Prompts.test_ghostwrite_and_delegation_variants`、eval `no-rq-for-student`・`student-view-first` |
| **研究不正の予防と指導教員とのやりとり**: 剽窃の点検、偏りの点検、研究不正の五類型、引用の要件、Word のコメントの往復 | `rklib/overlap.py`・`bias.py`・`docx_comments.py`、`skills/integrity-check`・`bias-check`・`review-comments`、`./rk import-docx`(署名つきの取り込み)、evals 11 件、作業憲法(CONSTITUTION.md) | eval(`comment-has-no-fix-example` ほか)。重なりの点検・偏りの点検・論証図・Word の取り込みには専用の単体試験が無い(SELF-ASSESSMENT の既知の欠陥) |

## 3. 守りの仕組み

### 3.1 書き込みを止める(フック)

- 原稿(`manuscript/`)への AI の書き込みは、どの道具でも deny に固定し、設定でも戻せない。`.ryukoku/` 全体、`tools/`・起動ファイル(`rk`・`rk.cmd`・`rk.ps1`)・Plugin 本体・`~/.ryukoku-writing`・`.claude/` と `~/.claude/`、`research/questions.md`・検索の記録・`thinking/`・`disclosure/`・`review/annotations*`・台帳・`data/raw/` も同じ。
- 目印は対象のパス(file_path、Bash の語のうちパスらしいもの)から上へ探し、次にセッションのフォルダから上へ、無ければ一つ二つ下を探す。シンボリックリンクは解決し、`/./` と `//` を正規化し、Windows の形のパスもそろえてから照合する。セッションのフォルダがプロジェクトの中にあれば、Bash は `cd <位置>/ ;` を足した形で照合する。SessionStart は子フォルダの目印を見つけたら「開き直す」を一度だけ伝える。
- 目印も対象のパスも見えないコマンド(別のフォルダ、glob、変数)では、利用者が使ったプロジェクトの一覧(`~/.ryukoku-writing/projects.tsv`)のすべてに窓を開き、tool_use_id で閉じる。目印を退けても、一覧にある限りフックは働く。
- 目印が無く子フォルダにも無ければ、全フックが無出力でファイルも作らない。
- 科目の AI 利用条件(`ai_policy`)が `prohibited` なら、Read・Grep・Glob はプロジェクトの中で path にかかわらず deny し、Bash は状態の確認(`rk check`・`status`・`facts`、`git status`・`log`)だけを通す。`limited` なら許した用途の外に確認を出す。pandoc の直接実行は、出力先が `manuscript/` の外なら原稿への書き込みではなく書き出しの用途として扱う。
- 個人情報らしき入力は、送信前に止めて種類と行を示し、値は伏せる(照合の前に NFKC。Python が無ければ sed の表で全角の数字とハイフンの類をそろえる)。語の無い「ID: 数字」だけは誤検知とのかね合いで注意の注入にとどめる。住所は都道府県の後を伏せる。
- 合言葉の「合言葉は …」の形と、登録した鍵が導ける短い一行(全角も)は、送信前に止める。

### 3.2 ツールの窓の検知

- 窓ごとに写し(`~/.ryukoku-writing/state/<project>/windows/<tool_use_id>.json`)を取り、PostToolUse はそれと比べる。同じ呼び出しの中で共有の基準を作り直しても隠れない。
- 確認を求める(ask)呼び出しの窓は「保留」で、次のツール呼び出しまでに PostToolUse が来なければ(学生が断った)捨てる。学生のその後の編集を AI の変更として報告しない。
- 検知は AI 利用記録のほかに、プロジェクトの外の控え(state の `detections-witness.jsonl` と、フックから見えるときは `${CLAUDE_PLUGIN_DATA}/witness/`)にも書く。`rk check` と SessionStart は、控えにあって記録に無い検知を NG・警告にする(記録の行を消して連鎖を作り直しても見つかる)。
- 監視の対象: 原稿、`tools/`・`thinking/`・`disclosure/`・`.github/`・`.githooks/`・起動ファイル、`.ryukoku/config.yml`・`signers.json`・`style.yml`・`research/questions.md`、Claude Code の設定、`plugin-root`、信頼の写し、`pandoc/`、`sources/references.json`(既存の文献の著者・年の変更と削除)。`signoffs.jsonl`・`ai-use-log.jsonl`・検索の記録・`review/annotations-log.jsonl` は追記だけを許す。
- 署名つきの記録で説明できる変更(採用した提案、戻した変更、承認した規則、画面が署名のときに追記する開示の行)は報告しない。
- **AI が書いたファイル**: 窓の前にプロジェクトのファイルの inode・大きさ・mtime・ctime を控え、窓の後に変わったものと新しいものを、内容の SHA-256 と実際のパスで記録する。ctime は `touch -d` で戻せず、`mv`・`cp`・tar の展開は新しい inode か ctime になるので、mtime を古くしても抜けない。

### 3.3 署名と信頼の起点

- 合言葉 → PBKDF2-HMAC-SHA256 60 万回(署名者ごとの salt)→ Ed25519 の鍵。秘密鍵のファイルは無く、`signers.json` には公開鍵・salt・回数だけを置く。Ed25519 は標準ライブラリだけの実装で、RFC 8032 の試験ベクトルと、`cryptography` があればそれとの照合で試験する。
- 記録は (種類、対象、判断、内容のダイジェスト、detail、役割、鍵、時刻、方法、メモ) に署名し、`.ryukoku/signoffs.jsonl` に追記する。ダイジェストが変われば(署名の後に内容が変われば)無効になる。
- 合言葉は 10 文字以上で、同じ文字の繰り返し・数字だけ・よくある語が中心のものを拒み、3 語以上か 16 文字以上を求める(簡単な下限で、強さの測定ではない)。画面の署名は誤りが 5 回でロック(30 秒から倍々)。
- **CI の起点**: `git rev-list --max-parents=0` で根の commit がただ一つであることを確かめ(二つ以上なら何も信頼しない)、first-parent の鎖を根から辿って最初に現れた `signers.json` の署名者を起点にする(commit の日付は使わない)。その署名者が 2 人以上なら履歴の書き換えを疑い、どれも起点にしない。それ以外の鍵は、基準ブランチのものも PR やマージで入ったものも、起点から承認の鎖でつながらなければエラー。起点の指紋は CI の出力の先頭に出す。PR の作業ツリーの署名者は、最初の PR でも信頼しない。
- **Git なし**: 信頼の起点は `~/.ryukoku-writing/trust/<project>.json` で、端末の `./rk setup`・`./rk trust` だけが書く。起点の印の無い署名者は承認が要る。スクリプトが `register()` を呼んで足した署名者は「未承認の署名者の追加」になる。
- **失効と引き継ぎ**: 失効した鍵の承認は、時刻にかかわらず無効。例外は、失効の記録(失効させる鍵自身で署名した `successor`)が名指しする一つの鍵だけ。`./rk setup` で「知られた可能性がある」を選ぶと、今の合言葉で新しい鍵を承認し、続けて今までの鍵を失効させ、引き継ぎ先として新しい鍵を書く。忘れたときは承認できないので、新しい鍵自身が署名した起点の変更を `.ryukoku/root-changes.jsonl` に書き、CI は基準ブランチにあるその記録の鍵も起点に加え、「起点が変わった」と新しい指紋を出力の先頭に出す。**起点の変更を誰がしたかを道具は区別できない**ので、指導教員が学生と会って指紋を照らすことを前提にした。
- **main への push**: pre-push は端末での `yes` を求める(環境変数による抜け道は無い。AI のスクリプトが設定できるため)。フックは AI の main への push を deny、それ以外の push を ask にする。
- **道具と CI の変更**: `tools/`・起動ファイル・`.github/`・`.githooks/` が Plugin の同梱版(ローカル)か基準ブランチ(CI)と違えば、学生の `guarded` の署名が無い限り検査を通さない。CI は `git worktree add --detach .rk-base origin/<base>` の道具で PR を検査するので、PR の中で検査のコードを無効にしても基準の道具が落とす。

### 3.4 合言葉を受け取るコードの確認

- `./rk` の起動ファイルは全プロジェクトで同じ固定の内容で、Plugin の場所はプロジェクトの外(`~/.ryukoku-writing/plugin-root`)から読む。これは間接参照であり、同じ利用者のプログラムは書き換えられる。
- SessionStart(Claude Code から受け取る `CLAUDE_PLUGIN_ROOT`)と初期化が `plugin-root` を書き、`plugin-root.log` に場所・MANIFEST の要約・版を追記する。`plugin-root` が最後の記録と違えば(Claude Code の外で書き換えられた)、検知として AI 利用記録に残し、学生に伝えてから戻す。
- 人間用のコマンドと画面は、合言葉を求める前に場所と版を出し、自分の場所と MANIFEST の要約が最後の記録と同じか、同梱の MANIFEST と食い違いがないかを確かめ、違えば止まる。自分のコードがプロジェクトの中(`tools/`)にあれば動かない。端末の操作は本物の端末(/dev/tty)でだけ動く。
- 証拠ノートの起動の判定は basename ではなく実際のパスで行う。改名した写しや mtime を古くした写しは Plugin の外のコードとして ask(引数に `notebook` があれば deny)。背景(run_in_background)でも同じ照合をする。

### 3.5 確認なしで実行してよいコマンド(許可リスト)

`rklib/execgate.py` は bash の一部を真似た字句解析をする(一重・二重引用符、バックスラッシュ、行の継続、改行と `;` は区切り、`#` の注釈は語の頭だけで改行まで)。コマンド置換・バッククォート・プロセス置換・ヒアドキュメント・here-string・`$'…'`、括弧と波括弧(サブシェル・まとまり・関数の定義)、`case` は解析せず ask にする。単純なコマンドごとに次のどちらかなら確認なしで通し、それ以外は ask。

- (a) Plugin 同梱のコード: `python3`・`python`・`py`(名前だけで、無害な旗 `-B -I -u -E -s -S -O -OO -q -3` だけ)か `bash`・`sh` が、実際のパスが `CLAUDE_PLUGIN_ROOT` の中にあるファイルを実行するとき。プロジェクトの `tools/rk/…` は、`tools/rk` のすべてのファイルが Plugin の MANIFEST と内容のハッシュで一致するときだけ。`./rk` は、同梱の起動ファイルとバイト単位で同じで、`plugin-root` が Plugin を指すときだけ。前に環境変数の代入が付けば通さない。
- (b) 読み取りだけの決まったコマンド: `ls cat head tail wc grep egrep fgrep rg stat pwd diff cut tr nl paste comm join column sha256sum sha1sum md5sum basename dirname realpath readlink du df tree jq od echo printf true false test [ cd mkdir which type printenv date sort uniq file find env command git`。引数も照合する: `sort` の `--compress-program`・`-o`、`rg` の `--pre`、`find` の `-exec -execdir -ok -okdir -delete -fprint* -fls`、`date -s`、`tree -o`、`file -C -m`、`uniq` の出力ファイル、`env` と `command` の後ろのコマンドは ask。`git` は `status log diff show blame ls-files rev-parse` だけで、全体の旗は `-C --no-pager --no-optional-locks -P --literal-pathspecs` だけ(`-c --exec-path --git-dir --work-tree --namespace --ext-diff --textconv --output --config-env` は ask)。さらに、実際に使うリポジトリがこのプロジェクト自身の `<proj>/.git`(ディレクトリ)のときだけ通す(`-C`・`cd` の行き先から上へたどって判定。`.git` ファイル(gitdir:)や bare のリポジトリは ask)。`sed -n 'N,Mp' file`・`sed -n 'Np' file`(厳密に照合)と、`python3`・`pandoc`・`git`・`lualatex` などの `--version` だけの起動も通す。awk は ask。
- 出力のリダイレクトは、プロジェクトの中(`.git/`・`.githooks/`・`.github/` を除く)と `/dev/null` だけ。

理由文はコマンドを名指しし「Plugin の外のコードやコマンドを実行しうる」と書く。インタプリタで Plugin の外のコードを動かすときは「合言葉を入れる画面や端末を偽れる」、AI が書いた・変えたファイルを名指しするときはより強い文面にする。照合の道具が失敗したとき(最後の行 `scanned` が無い)と Python が無いときも ask(閉じる側に倒す)。保護したパスへの書き込みの deny は ask より先に判定する。`claude plugin|config|mcp|update|install` は deny。

### 3.6 提案の不変の検査(許可リスト)

`rklib/proposals.py` は、両方の行を許可した変換だけで正規形にし、行の数も含めて一字ずつ等しいときだけ通す。作成時と適用時の二度検査する。

- 許可する変換: (1) 英数字(U+FF10〜FF5A)と半角カナ(U+FF65〜FF9F)の全角半角、(2) 科目で選べる句読点の組「、」⇔「，」・「。」⇔「．」(数字に挟まれた点とカンマは句読点として扱わない。「１０．５」⇔「10.5」は全角半角としてだけ可)、(3) 日本語の文字・句読点に接する空白、行末の空白、行頭の全角空白(英語の語の間・記号の隣の空白と、行頭の半角の字下げはそのまま比べる)、(4) 全角・半角の ％（）：；！？(ただし `](`・`![`・`]:` になるときは別。リンク・画像・注の定義になるため)。
- 全角半角の変換でも、行頭(空白の後を含む)に Markdown の記号(`:`・`~`・`%`・`#`・`>`・`-`・`+`・`*`・`|`)ができる変換は拒否する。`％`→`%` は、`$…$`・`$$…$$` と raw TeX の行の中では拒否する(TeX では `%` は行コメント)。
- heading はこれに見出しの番号を足す。番号とみなすのは、見出しの先頭の `第N章/節/項`・`N`・`N.N`・`N.N.N` の後に空白が続き、その後が単位(年・年代・つ・個・倍・%・人・件 など)で始まらないときだけ。変えた後の番号は、道具が見出しの段と順番から計算した値と一致するときだけ受理する(AI は値を選べない)。
- citation はこれに「(著者 年)」⇔`[@key]` を足す(references.json の著者の姓と年が一致し、頁・接頭辞・接尾辞の語が同じ。引用の文中の位置も固定)。新しい引用も頁も足せない。
- diagram は front matter の設定行の追加・削除だけで、図の行は一字も変えない。
- NFKC 全体は使わない(㍻→平成、½→12、²→2 のような互換分解を通さないため)。見えない文字・形の似た別の文字は正規形に残るので、足せば必ず違いになる。

### 3.7 プロジェクトの外への書き込み

シェルの起動ファイル(`.bashrc`・`.profile`・`.zshrc`・`.zshenv` ほか、fish・PowerShell のプロファイル)、PATH 上のディレクトリと `~/.local/bin`・`~/bin`、自動起動(`~/.config/autostart`・`~/.config/systemd/user`・LaunchAgents)、`.envrc`、`.vscode/`、`.git/`・`.git` という名のファイル・`~/.gitconfig`・`~/.config/git/`・site-packages・`sitecustomize.py`・`usercustomize.py`・`.pth` への書き込みは、Write・Edit・Bash のすべてで deny。内容が Git や Python の設定の形(`[core]`・`[filter`・`fsmonitor`・`textconv`・`pager`・`sshCommand` など)の Write は場所を問わず ask。これら以外のプロジェクトの外への AI の書き込みは ask(セッションの一時ディレクトリ `$TMPDIR`・`/tmp` は除く。ただしプロジェクト自身がそこにある場合は除外しない)。`./rk` の起動ファイルは PATH から python を探すので、`~/.local/bin/python3` の差し替えを防ぐのが要点である。

### 3.8 Claude Code の設定

`.claude/` と `~/.claude/` への書き込みは全ツールで deny。`./rk check`・SessionStart・人間の段の最初の検査(`./rk setup` を含む)・CI は、`disableAllHooks: true` と、`enabledPlugins` でこの Plugin が false のものをエラーにする(`enabledPlugins` の書式は、`claude plugin disable` が `~/.claude/settings.json` に書いた内容で確かめた。開発時の観察)。削除の場合は設定が残らないので、`./rk check` は最後の SessionStart の記録の日付を出す。

### 3.9 コメントと追記だけの記録

すべてのコメントと返信に経路(`notebook` = 画面で入力・署名なし、`tty` = 端末の取り込み・署名あり、`agent-cli` = AI の道具)を記録して表示する。AI の道具からは必ず AI の名義で、確度は「要確認」。画面の API からのコメントは学生の名義だけ(指導教員の名義は 403。保管の層でも、指導教員の名義は端末の取り込みだけ)、表示と `annot list` に「本人確認なし」。作成・返信・解決・再オープンは `review/annotations-log.jsonl` に追記し(道具はコメントを消さない)、記録にあって annotations.json に無いコメントは `rk check` の NG。AI のコメントに書き換えの文の欄は無い。

### 3.10 一括の署名

鍵を作る前に、採用する hunk を原稿ごとに順に記憶の中で当て、位置を特定できないもの(原稿が変わった、同じ一括の別の提案が同じ行を変えた)と、同じ一括で採用する提案が変える節の署名を「署名しない」に分け、理由をつけて返す。結果は項目ごと(署名した・しなかった・失敗・未処理)で、画面は署名した項目を一覧から外す。位置を特定できない提案は一覧で「作り直しが要る」と出し、不採用しか選べない。

## 4. 脅威モデルと限界

| 相手 | 例 | この Plugin で |
|---|---|---|
| 取り違え・事故 | 「句読点を直して」で AI が原稿を書き換える。台帳を VERIFIED にする | フックが止める。署名が無いので検査が落ちる |
| 指示に従った回り道 | 変数の連結・base64・スクリプトのファイル・シンボリックリンク・patch・tar で原稿や問いを書く | 事前の照合は外れうる。多くは許可リストの外なので実行の前に確認が出る。許可されても窓の検知が拾い、連鎖の記録に残り、署名で判断するまで検査と CI が落ちる |
| 人間の確認の偽造 | スクリプトで署名者を足して署名する、PR で検査のコードを無効にする | 信頼されない署名者は落ちる(ローカル・CI)。CI は基準ブランチの道具で検査する |
| 合言葉の横取り | 合言葉を受け取るコードの差し替え、`plugin-root` の書き換え、偽の画面 | **Plugin のコードが動いている限り**、合言葉を求める前に場所と版を出し、Claude Code が記録した場所・MANIFEST と照らし、違えば止める。行き先の書き換えは、フックの deny、許可リストの外の実行の ask、窓の検知(`plugin-root` を監視)、次の SessionStart の照合(検知に残して戻す)で、起こりにくく・残るようにした。**偽のコード自身はこの確認をしないので、同じ利用者の権限のプログラムには止められない** |
| 同じ利用者の権限のプログラム(AI が書いて学生が実行を許したものを含む) | Plugin の写しと MANIFEST を作る、信頼の起点・検知の基準・控え・連鎖を作り直す、`disableAllHooks` を書く、ツールの外で後から書き込む | **止められない。** AI が書いたコードは実行の前に確認を求め、フックの拒否・変更の検知・二つ目の控え・設定の検査で痕跡を残す。GitHub の運用では信頼の起点が基準ブランチの最初の署名者にあり、利用者の PC の信頼の起点に依存しない。節の署名の画面は前回の署名からの差分を見せる |
| 合言葉の漏えい | 学生がチャットに合言葉を書く、他人に知られる | 「合言葉は …」の形と登録した鍵が導ける短い一行は送信前に止める(それ以外の形は止められないことがある)。漏れたら `./rk setup` で新しい鍵を登録し、今までの鍵を失効させる。ただし記録の時刻は署名者が書くので、漏れた合言葉で時刻をさかのぼった記録は作れる(GitHub では基準ブランチに入った記録の後ろへの追記として見える) |
| オフラインの総当たり | 公開鍵と salt から合言葉を推測する | PBKDF2 60 万回で遅くし、合言葉の下限を設ける(強さの保証ではない) |
| 学生自身 | 読まずに署名する | 止めない。署名は「読んで確かめた」という宣言で、画面は表示した項目にしか判断を選ばせない |

その他の限界:
- ツールの窓の検知は、AI のツールが動いている間に学生がエディタで保存した変更も「検知」に出す(誤検知)。学生は「自分の編集だった」を選んで署名する。許可されて長く動いている呼び出しの間に別の呼び出しが来ると、その窓の写しは残るが、共有の基準はその時点で作り直される。
- 実行の照合は許可リストなので、AI が書いたファイルの一覧は理由文の強さだけに使う。許可リストのコマンドが、学生の環境(環境変数、`~/.gitconfig` などの設定)を通して別のプログラムを動かす経路は、設定ファイルへの AI の書き込みを deny にすることで狭めたが、学生が自分で置いた設定は照合しない。設定を読む道具すべてを網羅したとは言い切れない。学生が確認で許可した実行は何でもできる。
- make・npm の scripts・Git のフックなど、間接に実行される設定は照合しない。
- Claude Code の設定でフックが止まっている間は、何も止めず記録もしない。後で検査が設定を見つけるが、止まっていた間の出来事は分からない。
- GitHub の `pull_request` のワークフローが PR の側で書き換えた定義で動くかは未確認(独立検証では、GitHub の一般的な仕様では PR の定義が動くと指摘された)。README では、PR が `.github/` を変えるときはその PR の CI を信用しないよう書いた。
- 代筆・問いの代行の依頼の検知は語彙による補助で、言い回しを変えると漏れる。最後の歯止めは、AI が原稿と問いに書けない仕組みである。
- `./rk` の起動ファイルは PATH から python を探す。setup で実パスを記録する設計は採らず、PATH 上と起動ファイルへの書き込みを両方止めることで主な経路を塞いだ。
- Windows では /dev/tty が無いので、人間用のコマンドは isatty に頼る(弱い)。Git Bash(mintty)上の Windows の Python で isatty が偽になる可能性は未確認。

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

採ったもの:
- **人間の判断は合言葉から毎回導く鍵の署名にする。** 秘密をディスクに置かないので、ファイルを読める AI にも偽造できない。端末の /dev/tty は、秘密に頼らない段差としてだけ残した。
- **提案と実行の照合は、どちらも拒否リストでなく許可リストにする。** 危険な形を列挙する方式は、独立検証で数値・不等号・矢印・頁の変更や、`find -exec`・`cp` の後の実行・`PYTHONPATH`・`BASH_ENV`・注釈の後の改行などで簡単に抜けた。
- **原稿への AI の書き込みは deny に固定する。** 確認(ask)で許す形では、学生が内容を見ずに許可を押せば AI の文が入る。設定でも戻せない。
- **信頼の起点と検知の基準はプロジェクトの外(`~/.ryukoku-writing`、`RK_STATE_HOME` で変更可)に置く。** プロジェクトの中に置くと、AI が消せる。

採らなかった案と理由:
- **確認コードや HMAC、画面の PIN と Cookie を人間の状態の裏づけにする**: 秘密がディスクにあり、ファイルを読める AI が偽造できる。画面の PIN は、AI が画面を起動するとき AI の標準出力に出るか、端末が無くて作れない。署名ごとに合言葉が要るので、PIN は守りを足さない。署名の無い書き込みは、コメント・返信・再オープン・検索記録の理由だけにした。
- **一括の採用・却下(残りを全部採用するキー、番号の範囲や all で選ぶ、画面の全選択)**: 一件ずつの確認を飛ばせる。各項目は表示してからでないと選べないことにした。
- **`${CLAUDE_PLUGIN_DATA}` に信頼の起点と基準を置く**: 学生の端末と AI の Bash からはこの変数が見えなかった(`claude -p` で `env | grep -c CLAUDE_PLUGIN_DATA` が 0。開発時の観察)。同じ場所を三者が使えるよう `~/.ryukoku-writing` にした。フックからは見えるので、検知の控えの「二つ目」としてそこにも書く。
- **Claude Code の Plugin の一覧のファイルと照らす**: Claude Code の内部のファイルの形に依存しないことにした(開発した環境にはそのファイルが無かった)。代わりに SessionStart のフックが受け取る `CLAUDE_PLUGIN_ROOT` を記録し、人間用のコードはそれと照らす。
- **画面と端末に、setup で決めた「合図の語」を出す**: 偽の画面は本物の画面の文言を写せる(同じ利用者の権限で Plugin のファイルを読める)ので、合図の語は偽物と本物を分けない。動いているコードの場所と版を出して照らすことにした。
- **起動ファイルに Plugin の場所を書き込む**: Plugin の更新で場所が変わり、commit された起動ファイルが PR の差分になる。場所はプロジェクトの外のファイルから読む。
- **PR の中の `tools/` の変更を指導教員のラベルで通す**: GitHub のラベルの条件の書き方を一次資料で確かめていない(未確認)。道具の更新は main で `./rk update-tools` に限った。
- **内容の修正案を提案ファイルにする**: 採用すれば AI の文が本文に入る(ガイドラインⅢ-4)。表記の揺れ(漢字とかな)も語の変更なので提案にしない。
- **Mermaid の timeline 図**: 構文を一次資料で確かめていない(未確認)。年表は flowchart で書いた。
- **ISBN-10 の検査、JaLC の API、NDL の isbn 索引**: 一次資料・実際の動作で確かめていない(未確認)ので実装しない。
- **gh でリポジトリを作る自動化**: gh のフラグを一次資料で確かめていない。`./rk setup` は手順を示すだけにした。
- **`cp manuscript/… build/…` の deny を緩める**(独立検証で誤検知と指摘された): Bash のコマンドに原稿のパスと書き込み系の操作が並ぶ形を止める規則によるもので、緩めない。原稿を読むには Read を使い、書き出しは `export` を使う。
- **git を初期化していないプロジェクトで `git status` を確認なしで通す**: 使うリポジトリがプロジェクトの `.git` のときだけ通す判定の結果で、確認が出るのは意図どおり。
- **起動ファイルが python を見つける方法の見直し(setup で実パスを記録)**: PATH 上と起動ファイルへの書き込みを両方止めれば主な経路は塞がるため、この版では採らず、限界として README に残した。
- **全角・半角の照合に NFKC 全体を使う**: 互換分解で内容が変わる(㍻→平成、½→12)。許可した変換だけを個別に書いた。

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
| レビューのコメントの層(Toulmin の配置、受容可能性・関連性・十分性)、誤謬名は判定でなく問いの見出し、事例選択の偏り | SEP「Informal Logic」https://plato.stanford.edu/entries/logic-informal/ 、IEP「Fallacies」https://iep.utm.edu/fallacy/ 、Geddes 1990, Political Analysis 2:131-150, DOI 10.1093/pan/2.1.131 。コード・ラベル・問いは作成者の言い換えで、試行も評定者間の一致の確認もしていない |
| 効くのは誤りとその理由を示し探索の方向を与えるフィードバック | Wisniewski, Zierer & Hattie 2020, Frontiers in Psychology 10:3087, DOI 10.3389/fpsyg.2019.03087 |
| 査読者は著者の論文を自分の好む書き方に書き直そうとしない | COPE, Ethical Guidelines for Peer Reviewers(2013)、DOI 10.24318/cope.2019.1.9 |
| APA・MLA の AI の利用の書き方 | APA「AI Contribution Statement Guide」https://apastyle.apa.org/instructional-aids/ai-contribution-statement.pdf 、MLA「Citing generative AI (updated and revised)」https://style.mla.org/citing-generative-ai-updated-revised/ 。Chicago は読めず未確認 |
| 開発時の観察(Claude Code 2.1.318、この環境) | Claude Code の Bash から `CLAUDE_PLUGIN_DATA`・`CLAUDE_PLUGIN_ROOT` が見えない。`claude -p` の SessionStart に model が来ない(model は transcript から読む)。eval で Bash を許すと、bubblewrap と socat が無いため実行が拒否される。`claude plugin disable` が `~/.claude/settings.json` に `"enabledPlugins": {"<plugin>@<marketplace>": false}` を書く(一時の HOME で観察)。`.claude/settings.local.json` の `disableAllHooks: true` で Plugin のフックが止まる(独立検証で `claude -p` により観察)。Monitor ツールが `command` を受け取る(この環境のツールの定義)。CiNii Books の項目名、NDL の `recordSchema=dcndl` と `creator=` の索引 |
| 未確認 | GitHub の `pull_request` のワークフローが PR の側の定義で動くか(独立検証は、一般的な仕様では動くと指摘)。Windows・macOS の実機、GitHub Actions 上の実行、lualatex による PDF、mmdc による図の画像化 |
