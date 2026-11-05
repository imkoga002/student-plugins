#!/usr/bin/env bash
# Stop of ryukoku-writing. Active only for a project with .ryukoku/config.yml. Honours stop_hook_active (no loops).
# Appends a turn marker to the chained AI-use log. If this turn produced a change detection or proposal files,
# keep the turn going once so the agent tells the student what to do next (the student decides, never the AI).
set -u; set -f
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/lib.sh"
INPUT="$(cat 2>/dev/null || true)"
CWD="$(printf '%s' "$INPUT" | json_string_field cwd)"
PROJ="$(find_session_project "$CWD" 2>/dev/null || true)"
is_active "$PROJ" || exit 0
printf '%s' "$INPUT" | json_bool_true stop_hook_active && exit 0
have_python || exit 0
FB_LANG="$(cfg_get feedback_lang)"; [ -n "$FB_LANG" ] || FB_LANG="$(cfg_get manuscript_lang)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$HERE/../.." && pwd)}"
R="$(pyrun -I -B "$PLUGIN_ROOT/scripts/rk/hookcore.py" stop "$PROJ" 2>/dev/null || true)"
W="$(printf '%s' "$R" | LC_ALL=C sed -n 's/.*"detections": \([0-9]*\).*/\1/p')"
PR="$(printf '%s' "$R" | LC_ALL=C sed -n 's/.*"proposal_runs": \([0-9]*\).*/\1/p')"
if [ "${W:-0}" -gt 0 ] 2>/dev/null; then
  printf '{"decision":"block","reason":"%s"}\n' "$(t "このターンのツール実行中に、原稿か守られているファイルが変わった(検知)。終える前に、学生に (1) 何が起きたか、(2) 証拠ノートの「変更の検知」か自分の端末の './rk changes' で差分を見て、残す・自分の編集だった・戻すを決めて署名する必要があること、(3) 決まるまで './rk check' と CI が失敗すること、を短く伝える。" "During this turn a tool call changed the manuscript or a protected file (detected). Before finishing, tell the student briefly (1) what happened, (2) that they review the diff in the evidence notebook ('Detected changes') or with './rk changes' and sign keep / mine / revert, (3) that './rk check' and CI fail until then." | json_escape)"
  exit 0
fi
if [ "${PR:-0}" -gt 0 ] 2>/dev/null; then
  printf '{"decision":"block","reason":"%s"}\n' "$(t "このターンで提案ファイルを作った。終える前に、学生に一、二文で伝える: 証拠ノート(画面。AI が起動してよい)の「提案」で一か所ずつ差分を見て採否を選び、最後に合言葉で署名する(端末なら './rk apply')。AI が原稿に直接書かない理由(ガイドラインⅢ-4)も一言。すでに伝えていれば、その旨を一行で述べて終えてよい。" "You created proposal files this turn. Before finishing, tell the student in one or two sentences: in the evidence notebook (you may start it) they look at each diff under 'Proposals', choose, and sign with their passphrase at the end (or './rk apply' in a terminal); and why the AI does not edit the manuscript directly (guideline III-4). If you already said so, say that in one line and finish." | json_escape)"
fi
exit 0
