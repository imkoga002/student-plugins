#!/usr/bin/env bash
# PreToolUse guard of ryukoku-writing. An early-warning layer: the backbone is structural (signed human records,
# the tool-window change detection in msguard.py, `rk check` and CI). Active only for a project that carries
# .ryukoku/config.yml; the project is found from the TARGET path first (a session opened in a parent or child
# folder is covered), then from the session folder, then one or two levels below.
# Every decision says why and what to do instead.
#   deny : any AI write to manuscript/ (every tool, Bash and PowerShell included); writes to .ryukoku/ (settings,
#          signers, signed records, the AI-use log, approved style rules), the tools and launchers (tools/, rk,
#          rk.cmd, rk.ps1), research/questions.md, the search log, thinking/, disclosure/, review/annotations*, the
#          ledgers, data/raw/, the per-user state folder (~/.ryukoku-writing), Claude Code's settings and plugins
#          (.claude/ in the project and in the home folder) and the plugin itself; running a human-only command;
#          starting the evidence notebook from anywhere but the installed plugin (checked on the parsed command:
#          quotes and argument order do not matter); terminal emulation and detached jobs; calls to the notebook's
#          local API; git push to main/master.
#   ask  : running code the AI wrote (a script it wrote or changed, code given inline to an interpreter, a file
#          that changed during this session, or a file it cannot determine) - that code runs with the student's
#          rights and could do anything the student can, including faking the passphrase prompt; CI/Git-hook
#          files; any other git push; personal data in written content or queries; uses outside the course's
#          allowed AI uses (ai_policy: limited); background runs (run_in_background, Monitor).
# Every tool goes through this hook (matcher "*"). Read-only tools open no detection window; a tool this hook does
# not know opens one, and one that carries a "command" (PowerShell, Monitor, ...) is checked like Bash.
set -u; set -f
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/lib.sh"
INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0
TOOL="$(printf '%s' "$INPUT" | json_string_field tool_name)"
[ -n "$TOOL" ] || exit 0
case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit) KIND=write ;;
  Read|Grep|Glob|LS|NotebookRead) KIND=read ;;
  WebFetch|WebSearch|Task|Agent) KIND=$TOOL ;;
  Skill|TodoWrite|ToolSearch|AskUserQuestion|ExitPlanMode|EnterPlanMode|TaskStop|TaskOutput|SendMessage|ListSkills|SearchSkills|ListPlugins) KIND=none ;;
  Bash) KIND=shell ;;
  *) KIND=other; [ -n "$(printf '%s' "$INPUT" | json_string_field command)" ] && KIND=shell ;;
esac
[ "$KIND" = none ] && exit 0
TUID="$(printf '%s' "$INPUT" | json_string_field tool_use_id)"
SID="$(printf '%s' "$INPUT" | json_string_field session_id | LC_ALL=C tr -cd 'A-Za-z0-9_-' | head -c 64)"
CWD="$(printf '%s' "$INPUT" | json_string_field cwd)"
BASE="$(project_dir "$CWD")"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$HERE/../.." && pwd)}"
RK_HOOKCORE="$PLUGIN_ROOT/scripts/rk/hookcore.py"
PR_N="$(norm_path "$PLUGIN_ROOT")"; PR_N="${PR_N%/}"
NAME=ryukoku-writing

# ---- which project? (target path first)
FP=""; PROJ=""
case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit|Read)
    FP="$(printf '%s' "$INPUT" | json_string_field file_path)"
    [ -n "$FP" ] || FP="$(printf '%s' "$INPUT" | json_string_field notebook_path)"
    [ -n "$FP" ] && PROJ="$(project_for_path "$FP" "$BASE" 2>/dev/null || true)" ;;
  Grep|Glob)
    FP="$(printf '%s' "$INPUT" | json_string_field path)"
    [ -n "$FP" ] && PROJ="$(project_for_path "$FP/x" "$BASE" 2>/dev/null || true)" ;;
  *)
    [ "$KIND" = shell ] || { FP="$(printf '%s' "$INPUT" | json_string_field file_path)"; [ -n "$FP" ] || FP="$(printf '%s' "$INPUT" | json_string_field path)"; [ -n "$FP" ] && PROJ="$(project_for_path "$FP" "$BASE" 2>/dev/null || true)"; }
    CMD0="$(printf '%s' "$INPUT" | json_string_field command)"
    for tok in $(printf '%s' "$CMD0" | LC_ALL=C tr '"'"'"';|&<>()=' '        ' | LC_ALL=C tr -s ' \t\n' '\n\n\n' | LC_ALL=C grep -E '/|\\' | head -n 24); do
      PROJ="$(project_for_path "$tok/x" "$BASE" 2>/dev/null || true)"
      [ -n "$PROJ" ] && break
    done ;;
esac
SESSION_PROJ="$(find_session_project "$CWD" 2>/dev/null || true)"
[ -n "$PROJ" ] || PROJ="$SESSION_PROJ"
if ! is_active "$PROJ"; then
  # no project in sight (another folder, a glob or a variable in the command): still open a
  # detection window in every project this user has, so a write that reaches one of them is detected
  case "$KIND" in
    write|shell|other) [ -f "$RK_REG" ] && have_python && pyrun -I -B "$RK_HOOKCORE" preall "$TUID" run >/dev/null 2>&1 ;;
  esac
  exit 0
fi
FB_LANG="$(cfg_get feedback_lang)"; [ -n "$FB_LANG" ] || FB_LANG="$(cfg_get manuscript_lang)"
POLICY="$(cfg_get ai_policy)"; [ -n "$POLICY" ] || POLICY=unknown
USES="$(cfg_get ai_allowed_uses | LC_ALL=C tr 'A-Z' 'a-z')"
OUTSIDE=""
if [ "$(phys_dir "$BASE" 2>/dev/null || printf '%s' "$BASE")" != "$(phys_dir "$PROJ" 2>/dev/null || printf '%s' "$PROJ")" ]; then
  OUTSIDE="$(t " / Claude Code がプロジェクトの外($BASE)で開かれている。プロジェクトのフォルダ($PROJ)で開き直すと、記録と検知が正しく働く。" " / Claude Code is open outside the project ($BASE). Reopen it in the project folder ($PROJ) so recording and detection work properly.")"
fi

# ---- structural layer: remember the protected state before a tool that may write runs (only if it may run).
# MODE ask: the student is asked first; the window counts only if the tool really runs (a declined
# call leaves no window).
guard_pre() {
  case "$KIND" in
    write|shell|other)
      have_python && pyrun -I -B "$RK_HOOKCORE" pre "$PROJ" "$TUID" "${1:-run}" >/dev/null 2>&1 ;;
  esac
  return 0
}
ask_out() { guard_pre ask; pre_decide ask "$NAME: $1$OUTSIDE"; }
deny_out() { pre_decide deny "$NAME: $1$OUTSIDE"; }

WHY_MS="$(t "原稿(manuscript/)には AI は書き込まない設計。理由: 龍谷大学ガイドラインⅢ-4(生成AIの作成物を一部であっても自分の成果物にしない)と、人間が確認していない変更を提出物に入れないため。表記・書式の機械的な直しも同じ。代わりに、(1) 表記・書式の統一は 'python3 tools/rk/rk.py propose' で proposals/ に提案を置き、学生が証拠ノートの画面(または自分の端末の './rk apply')で一か所ずつ採否を決めて合言葉で署名する、(2) 内容への指摘は 'python3 tools/rk/rk.py annot flag' で問いの形のコメントにする(修正例は書かない)。" \
"AI never writes to manuscript/ in this project. Why: Ryukoku guideline III-4 (never present AI output, even in part, as your own) and no unreviewed change may enter the submission; this includes mechanical notation fixes. Instead: (1) put notation/format fixes in proposals/ with 'python3 tools/rk/rk.py propose'; the student decides each hunk in the evidence notebook (or './rk apply' in their own terminal) and signs with their passphrase; (2) raise content issues as questions with 'python3 tools/rk/rk.py annot flag' (no rewritten text).")"
WHY_HUMAN="$(t "このファイルは人間の判断の記録か、それを守る設定・道具(署名者、署名つきの記録、AI 利用記録、承認済みの記法、設定、検査の道具)。人間の判断は学生が合言葉で署名したときだけ記録される。AI が書くと人間の確認を装うか守りを外すことになるので止めた。学生には、証拠ノートの画面か './rk <コマンド>' を案内する。" \
"This file holds human decisions or what protects them (signers, signed records, the AI-use log, approved style rules, settings, checking tools). Human decisions are recorded only when the student signs with their passphrase. An AI write would impersonate a confirmation or remove a safeguard, so it is blocked. Point the student to the evidence notebook or './rk <command>'.")"

WHY_STARTUP="$(t "シェルの起動ファイル・PATH 上のディレクトリ(~/.local/bin など)・自動起動・エディタのタスク(.vscode)・.envrc は AI が書かない。学生が次に端末を開いたり ./rk を動かしたりしたときに、確認なしでコードが動いてしまうため(検証の新規の指摘 3)。" "The AI does not write shell startup files, directories on PATH (~/.local/bin, ...), autostart entries, editor tasks (.vscode) or .envrc: they would run code without a prompt the next time the student opens a terminal or runs ./rk.")"

deny_class() { # CLASS -> deny with the matching explanation
  case "$1" in
    manuscript) deny_out "$WHY_MS" ;;
    ryukoku|disclosure|statehome) deny_out "$WHY_HUMAN" ;;
    startup) deny_out "$WHY_STARTUP" ;;
    tools|plugin) deny_out "$(t "検査・記録の道具(tools/、./rk の起動ファイル、Plugin 本体、~/.ryukoku-writing)は AI が書き換えない。守りを外すことになり、学生が合言葉を入れるコードの行き先を変えられるため。" "The checking and recording tools (tools/, the ./rk launchers, the plugin itself, ~/.ryukoku-writing) are not modified by the AI: that would remove the safeguards and could redirect the code that receives the student's passphrase.")" ;;
    runconfig) deny_out "$(t "Git と Python の設定(.git/、~/.gitconfig、~/.config/git/、site-packages、sitecustomize・usercustomize、.pth)は AI が書かない。読み取りだけのコマンド(git log、python の起動)にも別のコードを実行させる設定になりうるため。" "Git and Python configuration (.git/, ~/.gitconfig, ~/.config/git/, site-packages, sitecustomize/usercustomize, .pth) is not written by the AI: it could make even read-only commands (git log, starting python) run other code.")" ;;
    claude) deny_out "$(t "Claude Code の設定と Plugin の置き場所(.claude/ と ~/.claude/)は AI が書き換えない。disableAllHooks や Plugin の無効化で、このプロジェクトの守り(フック)が全部止まるため。設定を変えるなら学生が自分で行う。" "Claude Code's settings and plugin folders (.claude/ and ~/.claude/) are not modified by the AI: disableAllHooks or disabling the plugin would stop every safeguard of this project. The student changes settings themselves.")" ;;
    questions) deny_out "$(t "research/questions.md は学生が自分の言葉で書く問いの一覧(ガイドラインⅢ-1)。調査はここにある問いの番号に結びつけてだけ行う。AI は問いを書かず、問いかけで学生が言葉にするのを助ける(rq-dialogue)。" "research/questions.md lists the student's own questions (guideline III-1); research is tied to these ids. The AI does not write them; it asks questions so the student can (rq-dialogue).")" ;;
    searchlog) deny_out "$(t "検索の記録は道具とフックが自動で書く。選んだ理由や問いの番号は 'python3 tools/rk/rk.py searchlog annotate <id> --reason ... --selected ...' で補う。" "The search log is written automatically by the tools and hooks. Add reasons and question ids with 'python3 tools/rk/rk.py searchlog annotate <id> --reason ... --selected ...'.")" ;;
    annotations) deny_out "$(t "review/annotations.json は画面と注釈の道具だけが書く。AI の返信・指摘は 'python3 tools/rk/rk.py annot reply|flag'(問いと確かめ方だけ。解決は学生が署名して付ける)。" "review/annotations.json is written only by the screen and the annotation tool. Reply or flag with 'python3 tools/rk/rk.py annot reply|flag' (questions and how-to-check only; only the student resolves, with a signature).")" ;;
    ledger) deny_out "$(t "台帳(sources/register.csv・claims.csv)は直接書き換えない。行の追加は 'python3 tools/rk/rk.py ledger add-source|add-claim'、機械の確認は 'rk.py refcheck check'(機械の列だけ)。VERIFIED などの人間の列は学生が原典を読み、署名して付ける。" "Do not edit the ledgers directly. Add rows with 'python3 tools/rk/rk.py ledger add-source|add-claim'; 'rk.py refcheck check' writes machine columns only. Human columns such as VERIFIED are set by the student, with a signature, after reading the source.")" ;;
    thinking) deny_out "$(t "thinking/ は学生自身が書く思考の記録(ガイドラインⅢ-1: 結果だけでなく過程)。AI が書くと過程の記録が偽りになる。問いを返して、学生に書いてもらう。" "thinking/ is the student's own record of their reasoning (guideline III-1). An AI-written entry would falsify it. Ask questions and let the student write.")" ;;
    raw) deny_out "$(t "data/raw/ は変更しない場所。取り込みは 'python3 tools/rk/rk.py data add <file> --url ... --provider ... --license ... --method ...'、加工は data/processed/ に出す。" "data/raw/ is immutable. Import with 'python3 tools/rk/rk.py data add <file> --url ... --provider ... --license ... --method ...'; write derived data to data/processed/.")" ;;
  esac
}

policy_reason() {
  case "$POLICY" in
    prohibited) t "この科目は .ryukoku/config.yml で『AI 利用禁止(ai_policy: prohibited)』と記録されている(ガイドラインⅢ-3: 担当教員の指示に従う)。原稿・調査・検証に関わる AI の操作は止める。記録が誤りなら、学生がシラバスや教員の指示を確かめて ./rk setup で直す。" "This course is recorded as 'AI use prohibited' (ai_policy: prohibited; guideline III-3: follow the instructor). AI operations on the manuscript, research and verification are blocked. If the record is wrong, the student corrects it with ./rk setup after checking the syllabus." ;;
    *) t "この科目の AI 利用条件(ai_policy: limited)で許可された用途(ai_allowed_uses: ${USES:-なし})に、この操作の用途『$1』が含まれていない。シラバスや教員の指示を確かめ、許可されているときだけ進める(ガイドラインⅢ-3)。" "This operation's use '$1' is not among the uses allowed for this course (ai_policy: limited, ai_allowed_uses: ${USES:-none}). Proceed only if the syllabus or instructor allows it (guideline III-3)." ;;
  esac
}
policy_gate() { # USE -> deny (prohibited) or ask (limited and USE not allowed)
  case "$POLICY" in
    prohibited) deny_out "$(policy_reason "$1")" ;;
    limited) case ",$(printf '%s' "$USES" | tr -d ' ')," in *",$1,"*) : ;; *) ask_out "$(policy_reason "$1")" ;; esac ;;
  esac
}

case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    [ -n "$FP" ] || exit 0
    AFP="$(abs_of "$FP" "$BASE")"
    PFP="$(phys_dir "${AFP%/*}" 2>/dev/null)/${AFP##*/}" || PFP="$AFP"
    case "$(norm_path "$AFP")" in "$PR_N"/*) deny_class plugin ;; esac
    case "$(norm_path "$PFP")" in "$PR_N"/*) deny_class plugin ;; esac
    PPROJ="$(phys_dir "$PROJ" 2>/dev/null || printf '%s' "$PROJ")"
    REL="$(rel_norm "$PPROJ" "$PFP")"
    REL2="$(rel_norm "$PROJ" "$AFP")"
    case "/$REL/$REL2" in */../*|*/..) deny_out "$(t "'..' を含むパスは扱わない。プロジェクト内のパスで指定する。" "Paths containing '..' are not accepted; use a path inside the project.")" ;; esac
    C="$(path_class "$REL")"; [ "$C" = other ] && C="$(path_class "$REL2")"
    case "$C" in
      manuscript|ryukoku|tools|questions|searchlog|thinking|disclosure|annotations|ledger|raw|statehome|claude|runconfig) deny_class "$C" ;;
      startup) deny_out "$WHY_STARTUP" ;;
      ci) ask_out "$(t "CI や Git フックの変更は検査を弱めうる(CI は基準ブランチの道具で検査し、PR での変更はエラーになる)。変更点を学生が確かめる。" "Changing CI or Git hooks may weaken the checks (CI checks with the base branch's tools and flags such changes in a PR). The student should review it.")" ;;
      proposals) policy_gate format ;;
      research) policy_gate research ;;
      *)
        [ "$POLICY" = prohibited ] && policy_gate any
        # outside the project: a shell/boot/bin target is already "startup" (deny); anything else asks, except a
        # session temp dir (verification, new finding 3)
        NAFP="$(norm_path "$AFP")"; NPROJ="$(norm_path "$PROJ")"
        case "$NAFP/" in
          "$NPROJ"/*) : ;;
          *) is_session_tmp "$NAFP" "$NPROJ" || ask_out "$(t "プロジェクトの外への書き込み($AFP)。必要なときだけ許可する。" "A write outside the project ($AFP). Allow only if needed.")" ;;
        esac ;;
    esac
    if printf '%s' "$INPUT" | json_string_field content | LC_ALL=C grep -Eq '\[core\]|\[filter "|\[diff "|(^|[^a-z])(fsmonitor|sshCommand|textconv|hooksPath)[[:space:]]*=|(^|[^a-z])pager[[:space:]]*=[[:space:]]*[^|]|(^|[^a-z])(editor|external)[[:space:]]*='; then
      ask_out "$(t "書き込む内容が Git や Python の設定の形をしている(fsmonitor・textconv・pager・[filter] など)。読み取りだけのコマンドにも別のコードを実行させる設定になりうる。意図を確かめてから許可する。" "The content looks like Git or Python configuration (fsmonitor, textconv, pager, [filter], ...), which can make even a read-only command run other code. Confirm the intent before allowing.")"
    fi
    K="$(printf '%s' "$INPUT" | RK_HOOKCORE="$RK_HOOKCORE" pii_kinds)"
    [ -n "$K" ] && ask_out "$(t "書き込む内容に個人情報・秘密らしきもの($K)が含まれる。Git で公開されうる場所に置いてよいか、本当に必要かを確かめる(ガイドラインⅡ-2(1))。" "The content contains what looks like personal or secret data ($K). Confirm it is needed and safe to store where Git may publish it (guideline II-2(1)).")"
    guard_pre; exit 0 ;;

  Read|Grep|Glob|LS|NotebookRead)
    # prohibited course: no reading inside the project at all, whatever the path or pattern
    if [ "$POLICY" = prohibited ]; then
      if [ -z "$FP" ]; then policy_gate any; fi
      case "$(norm_path "$(abs_of "$FP" "$BASE")")/" in "$(norm_path "$PROJ")"/*) policy_gate any ;; esac
    fi
    exit 0 ;;

  WebFetch|WebSearch)
    policy_gate research
    K="$(printf '%s' "$INPUT" | RK_HOOKCORE="$RK_HOOKCORE" pii_kinds)"
    [ -n "$K" ] && ask_out "$(t "検索語または URL に個人情報・秘密らしきもの($K)が含まれる。外部に送ってよいか確かめる。" "The query or URL contains what looks like personal or secret data ($K). Confirm it may be sent outside.")"
    exit 0 ;;

  Task|Agent)
    ST="$(printf '%s' "$INPUT" | json_string_field subagent_type)"
    case "$ST" in
      *source-verifier*) policy_gate verify ;;
      *argument-reviewer*|*integrity-auditor*) policy_gate review ;;
      *) policy_gate research ;;
    esac
    exit 0 ;;

  *)
    if [ "$KIND" = other ]; then
      # an unknown tool (an MCP server, a newer built-in) that names a path: matched like Write
      for k in file_path path notebook_path; do
        UFP="$(printf '%s' "$INPUT" | json_string_field "$k")"
        [ -n "$UFP" ] || continue
        UA="$(abs_of "$UFP" "$BASE")"
        UPP="$(phys_dir "${UA%/*}" 2>/dev/null)/${UA##*/}" || UPP="$UA"
        case "$(norm_path "$UA")" in "$PR_N"/*) deny_class plugin ;; esac
        UC="$(path_class "$(rel_norm "$(phys_dir "$PROJ" 2>/dev/null || printf '%s' "$PROJ")" "$UPP")")"
        [ "$UC" = other ] && UC="$(path_class "$(rel_norm "$PROJ" "$UA")")"
        case "$UC" in
          manuscript|ryukoku|tools|questions|searchlog|thinking|disclosure|annotations|ledger|raw|statehome|claude|runconfig|startup) deny_class "$UC" ;;
        esac
      done
      guard_pre; exit 0
    fi
    CMD="$CMD0"
    [ -n "$CMD" ] || { guard_pre; exit 0; }
    # a command run from a folder inside the project is matched as if it named that folder (`echo x >> main.md`
    # with the session opened in manuscript/ is a manuscript write)
    CWDREL=""
    [ -n "$CWD" ] && CWDREL="$(rel_norm "$PROJ" "$(phys_dir "$CWD" 2>/dev/null || printf '%s' "$CWD")")"
    case "$CWDREL" in ""|/*|.) CWDREL="" ;; esac
    NC="$(norm_path "$CMD")"
    [ -n "$CWDREL" ] && NC="cd $CWDREL/ ; $NC"
    has() { printf '%s' "$NC" | LC_ALL=C grep -Eq -e "$1"; }
    WOPS='(^|[^a-z0-9_.-])(tee|cp|mv|dd|install|rsync|ln|truncate|rm|rmdir|touch|unlink|shred|patch|ed|ex|split|csplit)([[:space:]]|$)|sed[[:space:]]+(-[a-z]*i|--in-place)|perl[[:space:]]+-[a-z]*i|(python[0-9.]*|py|perl|ruby|node|nodejs|php|deno|bun|pwsh|powershell|osascript|bash|sh|zsh)[[:space:]]+(-[a-z]*[ec]([[:space:]]|$)|-command|--eval|-([[:space:]]|$))|awk[[:space:]]+-i|git[[:space:]]+(checkout|restore|apply|am|mv|rm|stash|reset)|(curl|wget|pandoc|iconv|unzip|tar|zip|7z)[^;|&]*([[:space:]]-o|--output|[[:space:]]-x)|of=|<<|set-content|add-content|out-file|new-item|copy-item|move-item|remove-item|rename-item|clear-content|tee-object|writealltext|appendalltext|-outfile'
    # pandoc writing its output outside manuscript/ is an export, not a manuscript write
    if has '(^|[[:space:]/;&|])pandoc[[:space:]]'; then
      POUT="$(printf '%s' "$NC" | LC_ALL=C sed -n -E 's/.*(^|[[:space:]])(-o|--output)([[:space:]]+|=)([^[:space:];|&]+).*/\4/p' | head -n 1)"
      case "/$POUT" in
        */manuscript/*) : ;;
        *) [ -n "$POUT" ] && NC="$(printf '%s' "$NC" | LC_ALL=C sed -E 's/(^|[[:space:]])(-o|--output)([[:space:]]+|=)[^[:space:];|&]+/ /g')" ;;
      esac
    fi
    touches() { # SEG_RE [NAME_RE]: NAME_RE (default SEG_RE) is the plain name used after ">" and "cd"
      local nm="${2:-$1}"
      has "$1" || return 1
      has "$WOPS" && return 0
      has ">[>|]?[[:space:]]*[\"']?[^[:space:]\"';|&]*($nm)" && return 0
      has "cd[[:space:]]+[^;&|]*($nm)" && has '>' && return 0
      return 1
    }
    SEG_MS='(^|[^a-z0-9_-])manuscript(/|[[:space:]"'"'"';|&)]|$)'
    RKCMD='(^|[^a-z0-9_.-])(rk|rk\.cmd|rk\.ps1|rk\.py)[[:space:]]+'
    NBCMD="python3 \"$PLUGIN_ROOT/scripts/rk/rk.py\" --project \"$PROJ\" notebook"
    NB_WHY="$(t "証拠ノートの画面は、インストールされた Plugin のコードから起動する(学生が合言葉を入れる画面なので、ほかの場所のコードに出させない)。起動するときは run_in_background で: $NBCMD" "Start the evidence notebook from the installed plugin only (the student types the passphrase there, so no other code may serve it). Start it with run_in_background: $NBCMD")"
    # what code would this command run? (shlex parse: quotes, argument order and cd do not matter)
    SCAN=""
    if have_python; then
      SCAN="$(printf '%s' "$CMD" | pyrun -I -B "$RK_HOOKCORE" cmdscan "$PROJ" "$PLUGIN_ROOT" "${CWD:-$BASE}" "$SID" 2>/dev/null || true)"
    fi
    if printf '%s\n' "$SCAN" | LC_ALL=C grep -q '^notebook_bad'; then deny_out "$NB_WHY"; fi
    if printf '%s\n' "$SCAN" | LC_ALL=C grep -q '^deny_write'; then
      deny_out "$(t "シェルの起動ファイル・PATH 上のディレクトリ・自動起動・Git や Python の設定・.git という名のファイルへの書き込みは、AI は行わない。学生が次に端末で ./rk を動かすときなどに、確認なしでコードが動いてしまうため。" "The AI does not write shell startup files, directories on PATH, autostart entries, Git/Python configuration, or a file named .git: they let code run without a prompt the next time the student uses the terminal.")"
    fi
    if printf '%s\n' "$SCAN" | LC_ALL=C grep -q '^claude_deny'; then
      deny_out "$(t "Claude Code の Plugin・設定・MCP の操作(claude plugin / config / mcp など)は AI が行わない。Plugin の無効化や削除、フックの停止で、このプロジェクトの守りが全部止まるため。必要なら学生が自分の端末で行う。" "Plugin, settings and MCP operations of Claude Code (claude plugin / config / mcp ...) are not run by the AI: disabling or removing the plugin, or turning hooks off, stops every safeguard of this project. The student does it in their own terminal if needed.")"
    fi
    if printf '%s\n' "$SCAN" | LC_ALL=C grep -q '^human'; then HUMAN_HIT=1; else HUMAN_HIT=0; fi
    # without python, the string form: the notebook only from the plugin's rk.py
    if [ -z "$RK_PY" ] && has "${RKCMD}[\"']?notebook"; then
      case "$NC" in
        *"$PR_N/scripts/rk/rk.py"*notebook*) : ;;
        *rk*notebook*) deny_out "$NB_WHY" ;;
      esac
    fi
    # human-only commands (any launcher or path)
    if [ "${HUMAN_HIT:-0}" = 1 ] || has "${RKCMD}[\"']?(setup|apply|verify|style|resolve|signoff|disclose|changes|optout|import-docx|sign|trust|update-tools|unattributed|review)[\"']?([[:space:]]|$)"; then
      deny_out "$(t "'./rk setup・apply・verify・style・resolve・signoff・disclose・changes・optout・import-docx・sign・trust・update-tools' は人間専用で、学生が自分の端末で実行し、合言葉を入れる。AI は実行せず、学生に、証拠ノートの画面(AI が起動してよい)か端末のコマンドと、その理由を案内する。AI が使えるのは 'rk.py check・status・facts' と機械の作業用コマンド。" "'./rk setup/apply/verify/style/resolve/signoff/disclose/changes/optout/import-docx/sign/trust/update-tools' are for the student at their own terminal, with their passphrase. Do not run them; point the student to the evidence notebook (you may start it) or the terminal command, and say why. The AI may use 'rk.py check/status/facts' and the machine subcommands.")"
    fi
    if has '(^|[^a-z0-9_.-])(script|expect|unbuffer|socat|tmux|screen|zpty|winpty|conpty)([[:space:]]|$)|import[[:space:]]+pty|from[[:space:]]+pty|pty\.(spawn|fork|openpty)|openpty|forkpty|pexpect'; then
      deny_out "$(t "端末を模擬する道具(script・expect・pty など)は、このプロジェクトでは AI が使わない。人間専用の経路(端末)を装えるため。" "Terminal emulators (script, expect, pty, ...) are not used by the AI here: they could pose as the human-only terminal channel.")"
    fi
    if has '(^|[^a-z0-9_.-])(nohup|setsid|disown|crontab|systemd-run|launchctl|schtasks)([[:space:]]|$)|(^|[;&|[:space:]])at[[:space:]]+(now|[0-9])'; then
      deny_out "$(t "切り離したバックグラウンド実行や予約実行は、AI のツール実行の外で原稿や記録を変えられるため、このプロジェクトでは使わない(必要なら run_in_background で。確認が出る)。" "Detached or scheduled jobs could change the manuscript or records outside the AI's tool window, so they are not used here (use run_in_background if needed; it asks first).")"
    fi
    if has 'hookcore|msguard'; then
      deny_out "$(t "変更の検知(msguard)の基準は、フックだけが扱う。AI が呼ぶと検知を外せるため止めた。" "Only the hooks run the change detection (msguard); calling it could defeat the detection.")"
    fi
    [ -n "$PR_N" ] && touches "$(printf '%s' "$PR_N" | sed 's/[.[\*^$()+?{|]/\\&/g')" && deny_class plugin
    touches 'scripts/rk|notebook/server|rklib/(sign|human|decide|setup|trust|ed25519|subjects)|\.claude/plugins' && deny_class plugin
    touches '\.ryuk' && deny_class ryukoku
    touches 'ryukoku-writing' && deny_class statehome
    touches '(^|[^a-z0-9_-])\.claude(/|[[:space:]"'"'"']|$)' '\.claude' && deny_class claude
    touches '(^|[^a-z0-9_-])\.git(/|[[:space:]"'"'"']|$)|\.gitconfig|\.gitmodules|\.config/git/|site-packages|(site|user)customize\.py|\.pth([[:space:]"'"'"']|$)|(^|/)(\.bashrc|\.bash_profile|\.bash_login|\.profile|\.zshrc|\.zprofile|\.zshenv|\.zlogin|\.inputrc|\.envrc|\.netrc|config\.fish|profile\.ps1)([[:space:]"'"'"']|$)|\.local/bin/|/\.config/(autostart|systemd)/|\.vscode/|library/launchagents/' '\.git|\.gitconfig|\.gitmodules|site-packages|customize\.py|\.pth|\.bashrc|\.profile|\.zshrc|\.zshenv|\.zprofile|\.envrc|\.netrc|config\.fish|profile\.ps1|\.local/bin|\.vscode|autostart|launchagents' && deny_class runconfig
    touches "$SEG_MS" manuscript && deny_class manuscript
    touches 'tools/rk(/|[[:space:]]|$)|tools/?([[:space:]]|$)|(^|[[:space:]/])rk(\.cmd|\.ps1)?([[:space:]]|$)' && deny_class tools
    touches 'questions\.md' && deny_class questions
    touches 'search-log\.jsonl' && deny_class searchlog
    touches '(^|[^a-z0-9_-])disclosure/' 'disclosure/' && deny_class disclosure
    touches 'review/annotations(-log)?\.json|annotations(-log)?\.json' && deny_class annotations
    touches 'sources/(register|claims)\.csv|(register|claims)\.csv' && deny_class ledger
    touches '(^|[^a-z0-9_-])thinking/' 'thinking/' && deny_class thinking
    touches 'data/raw' && deny_class raw
    if has '(127\.0\.0\.1|localhost|\[::1\]|0\.0\.0\.0):[0-9]+/api/'; then
      deny_out "$(t "証拠ノートのローカル API は人間がブラウザで使うもの。AI は 'python3 tools/rk/rk.py annot list|reply|flag' を使う(解決や VERIFIED は付けられない)。" "The notebook's local API is for the person in the browser. The AI uses 'python3 tools/rk/rk.py annot list|reply|flag' (it cannot resolve or verify).")"
    fi
    if has '(^|[;&|[:space:]])git([[:space:]]+-[^[:space:]]+)*[[:space:]]+(add|stage)([[:space:]]|$)' && has '\.ryukoku/cache|(^|[[:space:]/])\.cache/|api_cache|api-responses'; then
      deny_out "$(t "API 応答のキャッシュを git add しようとしている。API の応答は規約で保存が制限される(例: J-STAGE WebAPI 利用規約 第3条5項)。" "Trying to git add API caches; API terms restrict storing responses (e.g. J-STAGE WebAPI terms art. 3(5)).")"
    fi
    if has 'git[[:space:]].*(--no-verify|core\.hookspath)'; then
      ask_out "$(t "Git フックを飛ばす指定(--no-verify・core.hooksPath)がある。検査を外す理由を学生が確かめる。" "This skips Git hooks (--no-verify / core.hooksPath). The student should confirm why.")"
    fi
    if has '(^|[;&|[:space:]])git([[:space:]]+-[^[:space:]]+)*[[:space:]]+push([[:space:]]|$)'; then
      FORCE=0; TOMAIN=0
      has '[[:space:]]--force([[:space:]]|$)|--force-with-lease|--force-if-includes|[[:space:]]-[a-z]*f[a-z]*([[:space:]]|$)|[[:space:]]\+[a-z0-9_./-]+|[[:space:]]--mirror|[[:space:]]--delete' && FORCE=1
      has '(^|[[:space:]:+/])(main|master)([[:space:]]|$)' && TOMAIN=1
      BR="$(git -C "$PROJ" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
      if [ "$TOMAIN" = 0 ] && { [ "$BR" = main ] || [ "$BR" = master ]; } && ! has 'push[[:space:]]+[^-][^[:space:]]*[[:space:]]+[^[:space:]]+'; then TOMAIN=1; fi
      [ "$TOMAIN" = 1 ] && deny_out "$(t "AI は main/master(基準ブランチ)に push しない。基準ブランチは CI の信頼の起点(署名者と検査の道具)なので、学生が自分の端末で確かめてから push する。節の作業は、ブランチ → PR → 人間のレビュー → マージで進める。" "The AI does not push to main/master (the base branch): it is CI's trust root (signers and checking tools), so the student pushes it from their own terminal after checking. Section work goes branch -> PR -> human review -> merge.")"
      [ "$FORCE" = 1 ] && ask_out "$(t "強制 push は履歴を書き換え、署名や AI 利用記録の連鎖との対応を崩しうる。対象と理由を確かめる。" "A force push rewrites history and may break the link to signatures and the AI-use log chain. Confirm the target and reason.")"
      ask_out "$(t "git push。送る先(ブランチ)と中身を学生が確かめる。基準ブランチ(main)への push は AI からはしない。" "git push. The student checks the target branch and what is sent. The AI never pushes the base branch (main).")"
    fi
    if [ "$POLICY" != allowed ] && [ "$POLICY" != unknown ]; then
      if has "${RKCMD}(search|refcheck)|(^|[[:space:]/])(curl|wget)[[:space:]]"; then policy_gate research; fi
      if has "${RKCMD}(ledger|refcheck)"; then policy_gate verify; fi
      if has "${RKCMD}(propose|lint|export)|(^|[[:space:]/])pandoc[[:space:]]"; then policy_gate format; fi
      if has "${RKCMD}(annot|argmap|overlap)"; then policy_gate review; fi
      # prohibited: no shell work in the project except the read-only status commands (not even grep -r, globs
      # or python -c)
      if [ "$POLICY" = prohibited ] && ! has "${RKCMD}[\"']?(check|status|facts|help)|^(cd [^;]*; )?git[[:space:]]+(status|log)([[:space:]]|$)"; then policy_gate any; fi
    fi
    # the allow-list of what runs without asking: the plugin's own code and a fixed table of
    # read-only commands. Everything else - and anything that cannot be analysed - asks the student first.
    if [ -z "$RK_PY" ] || ! printf '%s\n' "$SCAN" | LC_ALL=C grep -q '^scanned'; then
      ask_out "$(t "このコマンドが何を実行するかを照合できなかった(Python 3 が無いか、照合の道具が動かなかった)。中身を確かめてから許可する。" "What this command runs could not be checked (no Python 3, or the checker failed). Allow only after reading it.")"
    fi
    EXEC="$(printf '%s\n' "$SCAN" | LC_ALL=C grep -E '^(ask|unparsed|outside_code|ai_file)' | head -n 8)"
    if [ -n "$EXEC" ]; then
      LIST="$(printf '%s\n' "$EXEC" | LC_ALL=C awk -F '\t' '{ k = $1; if (k == "ask") k = "許可リストの外"; else if (k == "unparsed") k = "解析できない書き方"; else if (k == "outside_code") k = "Plugin の外のコード"; else if (k == "ai_file") k = "AI が書いた・変えたファイル"; printf "%s: %s; ", k, $2 }')"
      LIST_EN="$(printf '%s\n' "$EXEC" | LC_ALL=C awk -F '\t' '{ k = $1; if (k == "ask") k = "not on the allow-list"; else if (k == "unparsed") k = "cannot be analysed"; else if (k == "outside_code") k = "code outside the plugin"; else if (k == "ai_file") k = "a file the AI wrote or changed"; printf "%s: %s; ", k, $2 }')"
      if printf '%s\n' "$EXEC" | LC_ALL=C grep -q '^ai_file'; then
        ask_out "$(t "AI が書いた・変えたファイルを実行しうるコマンド($LIST)。AI が書いたコードは学生の権限で何でもできる(原稿・記録・合言葉を受け取るコードや画面の書き換え、検知の消去も)。中身を自分で読んで、必要なときだけ許可する。" "This command may run a file the AI wrote or changed ($LIST_EN). Code written by the AI can do anything the student can (rewrite the manuscript, the records, the code or page that receives the passphrase, erase the detection). Read it yourself and allow only if needed.")"
      fi
      if printf '%s\n' "$EXEC" | LC_ALL=C grep -q '^outside_code'; then
        ask_out "$(t "Plugin の外のコードを実行する($LIST)。Plugin の外のコードは学生の権限で何でもでき、合言葉を入れる画面や端末を偽れる。中身を確かめ、必要なときだけ許可する。" "This runs code outside the plugin ($LIST_EN). It can do anything the student can, including faking the page or terminal where the passphrase is typed. Check it and allow only if needed.")"
      fi
      ask_out "$(t "このコマンドは、確認なしで通す許可リスト(Plugin 同梱の道具と、読み取りだけの決まったコマンド)の外にある($LIST)。Plugin の外のコードやコマンドを実行しうるので、中身を確かめ、必要なときだけ許可する。" "This command is outside the allow-list that runs without asking (the plugin's own tools and a fixed set of read-only commands) ($LIST_EN). It may run code or commands outside the plugin; check it and allow only if needed.")"
    fi
    if printf '%s' "$INPUT" | json_bool_true run_in_background || has '[^&]&[[:space:]]*$' || [ "$TOOL" = Monitor ]; then
      case "$NC" in
        *"$PR_N/scripts/rk/rk.py"*notebook*) printf '%s\n' "$SCAN" | LC_ALL=C grep -q '^notebook_ok' || [ -z "$SCAN" ] || ask_out "$NB_WHY" ;;
        *) ask_out "$(t "バックグラウンド実行。AI のツール実行の外で原稿が変わると、変更の検知が人間の編集と区別できない。必要な場合だけ許可する。" "Background execution: if the manuscript changes outside the AI's tool window, change detection cannot tell it from a human edit. Allow only if needed.")" ;;
      esac
    fi
    guard_pre; exit 0 ;;
esac
exit 0
