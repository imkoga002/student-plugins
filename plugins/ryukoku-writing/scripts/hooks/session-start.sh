#!/usr/bin/env bash
# SessionStart of ryukoku-writing. Prints nothing unless the session folder (or an ancestor) is a project, or a
# project sits one or two levels below it (then only a short "reopen Claude Code there" note).
# Inside a project: the digest of CONSTITUTION.md (the standing principles), the feedback language
# (stated in that language), the course AI policy and what it changes, waiting work, how to open the evidence
# notebook (absolute path of the installed plugin), first-run reminders, guideline re-check. Never fails the session.
set -u; set -f
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/lib.sh"
INPUT="$(cat 2>/dev/null || true)"
CWD="$(printf '%s' "$INPUT" | json_string_field cwd)"
BASE="$(project_dir "$CWD")"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$HERE/../.." && pwd)}"
HC="$PLUGIN_ROOT/scripts/rk/hookcore.py"
PROJ="$(marker_up "$BASE" 2>/dev/null || true)"
if [ -z "$PROJ" ]; then
  CH="$(child_project "$BASE" 2>/dev/null || true)"
  is_active "$CH" || exit 0
  PROJ="$CH"
  FB_LANG="$(cfg_get feedback_lang)"
  context_out SessionStart "$(t "[ryukoku-writing] このフォルダ($BASE)の下に論文のプロジェクト($CH)がある。Claude Code は、そのプロジェクトのフォルダで開き直すように学生に一度だけ伝える(このままでは AI 利用記録・変更の検知・調査の記録が一部働かない)。" "[ryukoku-writing] A thesis project ($CH) sits below this folder ($BASE). Tell the student once to reopen Claude Code in that project folder (otherwise parts of the AI-use log, change detection and research logging do not work).")"
  exit 0
fi
is_active "$PROJ" || exit 0
LANG_M="$(cfg_get manuscript_lang)"; [ -n "$LANG_M" ] || LANG_M=ja
FB_LANG="$(cfg_get feedback_lang)"; [ -n "$FB_LANG" ] || FB_LANG="$LANG_M"
POLICY="$(cfg_get ai_policy)"; [ -n "$POLICY" ] || POLICY=unknown
COURSE="$(cfg_get course_name)"; USES="$(cfg_get ai_allowed_uses)"; DISC="$(cfg_get disclosure_format)"
DEADLINE="$(cfg_get deadline)"; GCHK="$(cfg_get guideline_checked)"
MODEL="$(printf '%s' "$INPUT" | json_string_field model)"
ST=""
if have_python; then
  printf '{"type":"session","model":"%s","source":"%s"}' "$(printf '%s' "$MODEL" | json_escape)" "$(printf '%s' "$INPUT" | json_string_field source | LC_ALL=C tr -cd 'a-z')" \
    | pyrun -I -B "$HC" log "$PROJ" >/dev/null 2>&1
  SID="$(printf '%s' "$INPUT" | json_string_field session_id | LC_ALL=C tr -cd 'A-Za-z0-9_-' | head -c 64)"
  ST="$(pyrun -I -B "$HC" session "$PROJ" "$PLUGIN_ROOT" "$SID" 2>/dev/null || true)"
fi
num() { printf '%s' "$ST" | LC_ALL=C sed -n "s/.*\"$1\": \([0-9]*\).*/\1/p" | head -n 1; }
boolv() { printf '%s' "$ST" | LC_ALL=C grep -q "\"$1\": true" && echo yes || echo no; }

DIGEST="$(awk -v m="$( [ "$FB_LANG" = en ] && echo en || echo ja )" '
  $0 ~ "<!-- digest-" m ":start -->" {on=1; next}
  $0 ~ "<!-- digest-" m ":end -->" {on=0}
  on {print}' "$PLUGIN_ROOT/CONSTITUTION.md" 2>/dev/null)"
NB="python3 \"$PLUGIN_ROOT/scripts/rk/rk.py\" --project \"$PROJ\" notebook"

if [ "$FB_LANG" = en ]; then
C="[ryukoku-writing - unofficial; not a Ryukoku University tool. The university's, faculty's and instructor's instructions take precedence]
Write all feedback, explanations and questions to the student in English (feedback_lang: en), even though the skill texts are in Japanese. Manuscript language: $LANG_M.
Course: ${COURSE:-not set} / deadline: ${DEADLINE:-not set} / course AI policy: $POLICY / allowed uses: ${USES:-not recorded} / disclosure format: ${DISC:-not recorded}

$DIGEST

How this project works:
- You never write manuscript/, research/questions.md, thinking/ or .ryukoku/. Notation/format fixes become proposal files (python3 tools/rk/rk.py propose ...); content issues become questions (rk.py annot flag), never rewritten text.
- Every human decision (accepting a proposal, VERIFIED, approving a style rule, resolving a comment, signing a section, the pre-submission check, the daily AI-use summary) is a signature made with the student's passphrase. Never ask for the passphrase and never let it be typed into the chat; it goes only into the student's terminal or the local evidence notebook.
- To let the student decide, start the evidence notebook with run_in_background: $NB
  then give the student the URL it prints. Terminal alternatives: ./rk apply, ./rk verify, ./rk changes, ./rk signoff (the student runs them)."
else
C="[ryukoku-writing 非公式。龍谷大学の公式の道具ではない。大学・学部・担当教員の指示が常に優先する]
学生への講評・説明・問いは日本語で書く(feedback_lang: ja)。原稿の言語: $LANG_M。
科目: ${COURSE:-未設定} / 締切: ${DEADLINE:-未設定} / 科目の AI 利用条件: $POLICY / 許可された用途: ${USES:-未記録} / 開示の形式: ${DISC:-未記録}

$DIGEST

このプロジェクトの仕組み:
- AI は manuscript/・research/questions.md・thinking/・.ryukoku/ に書かない。表記・書式の統一は提案ファイルにする(python3 tools/rk/rk.py propose ...)。内容への指摘は問いにする(rk.py annot flag)。書き換えた文は出さない。
- 人間の判断(提案の採否・VERIFIED・記法規則の承認・コメントの解決・節の署名・提出前の確認・日ごとの AI 利用の概要)は、すべて学生の合言葉による署名。合言葉を尋ねない。チャットに入れさせない。入れる場所は学生の端末とローカルの証拠ノートの画面だけ。
- 学生に判断してもらうときは、証拠ノートを run_in_background で起動し、表示される URL を伝える: $NB
  端末で決めるなら学生が ./rk apply・./rk verify・./rk changes・./rk signoff を実行する。"
fi

case "$POLICY" in
  prohibited) C="$C
$(t "!! この科目は AI 利用禁止と記録されている。原稿・調査・検証のツール操作はフックが止める。記録が正しいかをシラバスや教員の指示で確かめるよう促すだけにする(ガイドラインⅢ-3)。" "!! This course is recorded as AI-prohibited. The hooks block manuscript, research and verification operations. Only suggest that the student confirm the record with the syllabus or instructor (guideline III-3).")" ;;
  limited) C="$C
$(t "!! この科目の AI 利用は限定。許可された用途($USES)の外のツール操作には確認が出る。" "!! AI use is limited in this course. Tools outside the allowed uses ($USES) ask first.")" ;;
  *) [ "$POLICY" = unknown ] && C="$C
$(t "!! 科目の AI 利用条件が未確認。ガイドラインⅢ-3に従い、シラバスの確認か担当教員への相談を学生に一度促す。確かめたら学生が自分の端末で ./rk setup。" "!! The course AI policy is unknown. Following guideline III-3, suggest once that the student checks the syllabus or asks the instructor, then runs ./rk setup in their terminal.")" ;;
esac
if [ -n "$ST" ]; then
  SG="$(num signers)"; PD="$(num pending_detections)"; PH="$(num pending_hunks)"; OC="$(num open_comments)"
  [ "${SG:-0}" = 0 ] && C="$C
$(t "!! 署名者(合言葉)がこの PC で登録・信頼されていない。最初に学生が自分の端末で ./rk setup を一度実行する(合言葉の登録・科目条件・オプトアウト・Git)。それまで人間の判断は記録できない。" "!! No trusted signer (passphrase) on this computer. First the student runs ./rk setup once in their own terminal (passphrase, course policy, opt-out, Git). Until then no human decision can be recorded.")"
  C="$C

$(t "学生の判断を待っているもの: 提案 ${PH:-0} か所 / 未解決のコメント ${OC:-0} 件 / AI のツール実行中に検知した変更 ${PD:-0} 件" "Waiting for the student: ${PH:-0} proposal hunks / ${OC:-0} open comments / ${PD:-0} changes detected during AI tool calls")"
  [ "${PD:-0}" -gt 0 ] 2>/dev/null && C="$C
$(t "!! 検知した変更が未判断。最初に学生に伝え、証拠ノートの「変更の検知」か ./rk changes を案内する。" "!! Detected changes are undecided. Tell the student first and point to the notebook's 'Detected changes' or ./rk changes.")"
  [ "$(boolv optout_recorded)" = no ] && C="$C
$(t "初回の確認(一度だけ): 使っている AI サービスで、入力を学習に使わせない設定(オプトアウト)を確かめたかを学生に尋ね、記録は学生が ./rk setup か ./rk optout で行うと伝える(ガイドラインⅡ-2(1))。" "First-run question (once): ask whether the student checked their AI service's training opt-out; they record it with ./rk setup or ./rk optout (guideline II-2(1)).")"
  if printf '%s' "$ST" | LC_ALL=C grep -q '"plugin_root_changed": "'; then
    C="$C
$(t "!! ./rk の行き先(~/.ryukoku-writing/plugin-root)が、前回の記録の後に Claude Code の外で書き換えられていた。今は Claude Code の Plugin の場所に戻した。学生にそのまま伝え、AI 利用記録の検知(./rk changes)を見てもらう。その間に端末で合言葉を入れていたなら、./rk setup で新しい合言葉にする。" "!! The ./rk launcher target (~/.ryukoku-writing/plugin-root) had been changed outside Claude Code since the last record; it now points to Claude Code's plugin again. Tell the student plainly and ask them to review the detection (./rk changes); if they typed the passphrase in a terminal meanwhile, they register a new one with ./rk setup.")"
  fi
  MD="$(num missing_detections)"
  [ "${MD:-0}" -gt 0 ] 2>/dev/null && C="$C
$(t "!! この PC で記録した変更の検知 ${MD} 件が AI 利用記録から消えている(検知の行の削除の可能性)。学生に伝え、./rk check の結果を見てもらう。" "!! ${MD} change detections noted on this computer are missing from the AI-use log (lines removed?). Tell the student and ask them to look at ./rk check.")"
  if printf '%s' "$ST" | LC_ALL=C grep -q '"settings_problems": \["'; then
    C="$C
$(t "!! Claude Code の設定で、フックかこの Plugin が無効になっている(disableAllHooks / enabledPlugins)。無効の間は何も記録・検知されない。学生に伝え、設定を戻すよう案内する(AI は設定を書き換えない)。" "!! Claude Code settings disable hooks or this plugin (disableAllHooks / enabledPlugins). Nothing is recorded or detected while they are off. Tell the student and ask them to restore the settings (the AI does not edit settings).")"
  fi
  if printf '%s' "$ST" | LC_ALL=C grep -q '"tools_problems": \["'; then
    C="$C
$(t "!! プロジェクトの道具(tools/rk)が Plugin 同梱のものと違う。学生に伝え、Plugin を更新したなら学生が ./rk update-tools、心当たりがなければ git diff tools/ で調べるよう案内する。" "!! The project's tools/rk differ from the plugin's copy. Tell the student: after a plugin update they run ./rk update-tools; otherwise investigate with git diff tools/.")"
  fi
fi
if [ -n "$GCHK" ]; then
  D="$(days_since "$GCHK")"
  if [ -n "$D" ] && [ "$D" -gt 90 ] 2>/dev/null; then
    C="$C
$(t "ガイドラインの更新確認から ${D} 日経過(ガイドラインⅣ: 継続的に見直される)。'python3 tools/rk/rk.py guideline-check' の実行を学生に提案する(ネットワークを使う)。" "${D} days since the guideline was last checked (guideline IV: it is revised). Suggest 'python3 tools/rk/rk.py guideline-check' (uses the network).")"
  fi
fi
have_python || C="$C
$(t "注意: python3 が見つからない。署名・検査・変更の検知・提案は動かない(フックの事前確認は動く)。python3 を入れるよう学生に勧める。" "Note: python3 not found. Signing, checks, change detection and proposals do not work (the pre-checks still do). Suggest installing python3.")"
context_out SessionStart "$C"
exit 0
