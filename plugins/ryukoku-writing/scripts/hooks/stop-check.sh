#!/usr/bin/env bash
# Stop of ryukoku-writing. Active only for a project with .ryukoku/config.yml. Honours stop_hook_active (no loops).
# Appends a turn marker to the chained AI-use log. If this turn produced a change detection, an AI write to the
# manuscript or proposal files, keep the turn going once so the agent tells the student what happened and what to
# do next (the student decides, never the AI).
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
MW="$(printf '%s' "$R" | LC_ALL=C sed -n 's/.*"manuscript_writes": \([0-9]*\).*/\1/p')"
VR="$(printf '%s' "$R" | LC_ALL=C sed -n 's/.*"verification_runs": \([0-9]*\).*/\1/p')"
if [ "${W:-0}" -gt 0 ] 2>/dev/null; then
  printf '{"decision":"block","reason":"%s"}\n' "$(t "このターンのツール実行中に、守られているファイル(道具・設定・人間の記録など)が変わった(検知)。終える前に、学生に (1) 何が起きたか、(2) 証拠ノートの「変更の検知」か自分の端末の './rk changes' で差分を見て判断する必要があること、(3) 決まるまで './rk check' と CI が失敗すること、を短く伝える。" "During this turn a tool call changed a protected file (tools, settings, human records, ...; detected). Before finishing, tell the student briefly (1) what happened, (2) that they review the diff in the evidence notebook ('Detected changes') or with './rk changes' and decide, (3) that './rk check' and CI fail until then." | json_escape)"
  exit 0
fi
if [ "${MW:-0}" -gt 0 ] 2>/dev/null && [ "${VR:-0}" = 0 ]; then
  printf '{"decision":"block","reason":"%s"}\n' "$(t "このターンで原稿に書いた。終える前に、学生に短く示す: (1) どの節のどの段落を書いた・直したか(由来は .ryukoku/provenance.jsonl に自動で残った)、(2) 書き込みの直後に出た機械の照合の結果(引用の台帳の状態、引用のない断定、出典のない数字、主張カードとの食い違いの候補)、(3) 致命・重要の候補があれば claim-verifier で確かめるか、どう直すかの案。材料にない主張・数字・文献は足していないことも一言。すでに伝えていれば、その旨を一行で述べて終えてよい。" "You wrote in the manuscript this turn. Before finishing, show the student briefly: (1) which paragraphs of which section you wrote or revised (provenance was recorded automatically in .ryukoku/provenance.jsonl), (2) the mechanical check results shown after the write (ledger state of the citations, uncited assertions, figures without a source, candidates that differ from the claim card), (3) for fatal or major candidates, a claim-verifier check or a proposed fix. Say also that you added no claim, figure or source beyond the materials. If you already did, say so in one line and finish." | json_escape)"
  exit 0
fi
if [ "${PR:-0}" -gt 0 ] 2>/dev/null; then
  printf '{"decision":"block","reason":"%s"}\n' "$(t "このターンで提案ファイルを作った。終える前に、学生に一、二文で伝える: 証拠ノート(学生が自分の端末で ./rk notebook を実行して開く画面)の「提案」で一か所ずつ差分を見て、採用・不採用のボタンで決める(合言葉は要らない。端末なら './rk apply')。採用した変更は由来の記録に残る。すでに伝えていれば、その旨を一行で述べて終えてよい。" "You created proposal files this turn. Before finishing, tell the student in one or two sentences: in the evidence notebook (the student opens it with ./rk notebook in their terminal) they look at each diff under 'Proposals' and accept or reject it with a button (no passphrase; or './rk apply' in a terminal). Accepted changes are recorded as provenance. If you already said so, say that in one line and finish." | json_escape)"
fi
exit 0
