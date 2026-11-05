#!/usr/bin/env bash
# PostToolUse of ryukoku-writing. Active only for a project with .ryukoku/config.yml. Fails open.
#  - msguard post: did manuscript/ change while this tool ran? -> provenance, paragraph by paragraph
#    (.ryukoku/provenance.jsonl), and the mechanical part of the verification as a note to the agent. Did a protected
#    file change? -> a detection in the chained AI-use log and a note; `rk check` fails until the student decides.
#  - one factual event in the chained AI-use log (no prompt text, no command lines; tool, area, target class).
#  - WebSearch, and WebFetch of a database search URL: an automatic search record in
#    research/search-log.jsonl (every search is logged). The question id and the reason are completed with `rk.py searchlog annotate`.
# The project of a detection window is the one PreToolUse opened it for (matched by tool_use_id over the projects
# this user has), so a session opened in another folder is covered too. Every tool comes
# here (matcher "*"); read-only tools are skipped.
set -u; set -f
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/lib.sh"
INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0
have_python || exit 0
TOOL="$(printf '%s' "$INPUT" | json_string_field tool_name)"
case "$TOOL" in
  Read|Grep|Glob|LS|NotebookRead|TodoWrite|ToolSearch|AskUserQuestion|ExitPlanMode|EnterPlanMode|TaskStop|TaskOutput|SendMessage|ListSkills|SearchSkills|ListPlugins) exit 0 ;;
esac
CWD="$(printf '%s' "$INPUT" | json_string_field cwd)"
BASE="$(project_dir "$CWD")"
PROJ=""
case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    FP="$(printf '%s' "$INPUT" | json_string_field file_path)"
    [ -n "$FP" ] || FP="$(printf '%s' "$INPUT" | json_string_field notebook_path)"
    [ -n "$FP" ] && PROJ="$(project_for_path "$FP" "$BASE" 2>/dev/null || true)" ;;
esac
[ -n "$PROJ" ] || PROJ="$(find_session_project "$CWD" 2>/dev/null || true)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$HERE/../.." && pwd)}"
HC="$PLUGIN_ROOT/scripts/rk/hookcore.py"
TUID="$(printf '%s' "$INPUT" | json_string_field tool_use_id)"
FULLCMD="$(printf '%s' "$INPUT" | json_string_field command)"
if ! is_active "$PROJ"; then
  # no project here: close the windows PreToolUse opened in the registered projects
  case "$TOOL" in
    WebFetch|WebSearch|Task|Agent|Skill) ;;
    *) [ -f "$RK_REG" ] && pyrun -I -B "$HC" postall "$TOOL" "$TUID" "" "$FULLCMD" "$(printf '%s' "$INPUT" | json_string_field file_path)" >/dev/null 2>&1 ;;
  esac
  exit 0
fi
FB_LANG="$(cfg_get feedback_lang)"; [ -n "$FB_LANG" ] || FB_LANG="$(cfg_get manuscript_lang)"
SID="$(printf '%s' "$INPUT" | json_string_field session_id | LC_ALL=C tr -cd 'A-Za-z0-9_-' | head -c 64)"

CTX=""
case "$TOOL" in
  WebFetch|WebSearch|Task|Agent|Skill) ;;
  *)
    SUM=""
    [ -n "$FULLCMD" ] && SUM="$(printf '%s' "$FULLCMD" | LC_ALL=C tr '\n\t' '  ' | LC_ALL=C sed -E 's/(appid|appId|api_key|key|token|mailto)=[^& ]*/\1=***/g' | LC_ALL=C head -c 160 | utf8_clean)"
    PFP="$(printf '%s' "$INPUT" | json_string_field file_path)"
    [ -n "$PFP" ] || PFP="$(printf '%s' "$INPUT" | json_string_field notebook_path)"
    if registered "$(phys_dir "$PROJ" 2>/dev/null || printf '%s' "$PROJ")"; then
      MG="$(pyrun -I -B "$HC" postall "$TOOL" "$TUID" "$SUM" "$FULLCMD" "$PFP" 2>/dev/null || true)"
    else
      MG="$(pyrun -I -B "$HC" post "$PROJ" "$TOOL" "$TUID" "$SUM" "$FULLCMD" "$PFP" 2>/dev/null || true)"
    fi
    NOTE="$(printf '%s' "$MG" | json_string_field note)"
    [ -n "$NOTE" ] && CTX="$NOTE"
    if printf '%s' "$MG" | LC_ALL=C grep -q '"entries": \["U-'; then
      CTX="${CTX:+$CTX
}$(t "[ryukoku-writing] このツールの実行中に、守られているファイル(道具・設定・人間の記録・由来の記録・問い・思考の記録)が変わった(検知: msguard)。AI はこれらに書かない設計なので、意図しない変更の可能性が高い。続ける前に学生にそのまま伝え、証拠ノートの「変更の検知」(または自分の端末の './rk changes')で、差分を見て判断するよう案内する。決まるまで './rk check' と CI は失敗する。検知: $(printf '%s' "$MG" | LC_ALL=C sed -e 's/"note": "[^"]*"//' | head -c 1500 | utf8_clean)" \
"[ryukoku-writing] While this tool ran, a protected file (tools, settings, human records, provenance, questions, thinking log) changed (detected by msguard). The AI does not write these, so this is probably unintended. Before continuing, tell the student plainly and ask them to review the diff in the evidence notebook ('Detected changes') or with './rk changes'. './rk check' and CI fail until then. Detected: $(printf '%s' "$MG" | LC_ALL=C sed -e 's/"note": "[^"]*"//' | head -c 1500 | utf8_clean)")"
    fi ;;
esac

ACTION=""; TARGET=""; AREA=""
case "$TOOL" in
  Write|Edit|MultiEdit|NotebookEdit)
    ACTION=write; AREA="$(path_class "$(rel_norm "$PROJ" "$(abs_of "$FP" "$BASE")")")"; TARGET="$AREA" ;;
  Bash)
    C="$(printf '%s' "$INPUT" | json_string_field command)"
    ACTION=run
    case "$C" in *rk.py*|*"./rk "*) AREA="$(printf '%s' "$C" | LC_ALL=C sed -n 's/.*rk\(\.py\)\{0,1\}"\{0,1\}[[:space:]]\{1,\}\([a-z-]*\).*/rk:\2/p' | head -n 1)" ;; *) AREA=shell ;; esac
    TARGET="$(printf '%s' "$C" | LC_ALL=C sed -n '1p' | LC_ALL=C sed -E 's/^[[:space:]]*//' | LC_ALL=C awk '{print $1}' | LC_ALL=C sed 's#.*/##' | LC_ALL=C tr -cd 'A-Za-z0-9._-' | head -c 40)" ;;
  WebFetch)
    U="$(printf '%s' "$INPUT" | json_string_field url)"
    HOST="$(printf '%s' "$U" | sed -e 's#^[a-zA-Z]*://##' -e 's#[/?#].*$##' | LC_ALL=C tr 'A-Z' 'a-z' | LC_ALL=C tr -cd 'a-z0-9.-')"
    ACTION=fetch; TARGET="$HOST"; AREA=web
    case "$HOST" in
      cir.nii.ac.jp|ci.nii.ac.jp|ndlsearch.ndl.go.jp|api.crossref.org|api.datacite.org|api.jstage.jst.go.jp|www.jstage.jst.go.jp|api.openalex.org|api.semanticscholar.org|www.e-stat.go.jp|api.e-stat.go.jp|kaken.nii.ac.jp|opac.ryukoku.ac.jp)
        RAWQ="$(printf '%s' "$U" | sed -E -n 's/.*[?&](q|query|query\.bibliographic|keyword|kw|title|search|words)=([^&#]*).*/\2/p' | head -n 1)"
        if [ -n "$RAWQ" ]; then
          Q="$(printf '%s' "$RAWQ" | pyrun -I -B -c 'import sys,urllib.parse;print(urllib.parse.unquote_plus(sys.stdin.read().strip())[:300])' 2>/dev/null)"
          [ -n "$Q" ] && pyrun -I -B "$HC" search "$PROJ" "$HOST" "$Q" >/dev/null 2>&1
        fi ;;
    esac ;;
  WebSearch)
    Q="$(printf '%s' "$INPUT" | json_string_field query | LC_ALL=C head -c 300 | utf8_clean)"
    ACTION=search; TARGET=WebSearch; AREA=web
    [ -n "$Q" ] && pyrun -I -B "$HC" search "$PROJ" "WebSearch" "$Q" >/dev/null 2>&1 ;;
  Task|Agent)
    ACTION=subagent; TARGET="$(printf '%s' "$INPUT" | json_string_field subagent_type | LC_ALL=C tr -cd 'A-Za-z0-9:_-')"; AREA=subagent ;;
  Skill)
    ACTION=skill; TARGET="$(printf '%s' "$INPUT" | json_string_field skill | LC_ALL=C tr -cd 'A-Za-z0-9:_-')"; AREA=skill ;;
  *) ACTION=run; AREA=other; TARGET="$(printf '%s' "$TOOL" | LC_ALL=C tr -cd 'A-Za-z0-9_:-' | head -c 60)" ;;
esac
printf '{"type":"event","session":"%s","tool":"Claude Code","model":"","action":"%s","target":"%s","area":"%s"}' \
  "$SID" "$ACTION" "$(printf '%s' "$TARGET" | json_escape)" "$(printf '%s' "$AREA" | json_escape)" \
  | pyrun -I -B "$HC" log "$PROJ" "$(printf '%s' "$INPUT" | json_string_field transcript_path)" >/dev/null 2>&1
[ -n "$CTX" ] && context_out PostToolUse "$CTX"
exit 0
